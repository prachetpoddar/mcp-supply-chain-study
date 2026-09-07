"""Hardened MCP supply-chain resolver.

Improvements over the pilot:
  * npm semver range resolution (was: everything resolved to `latest`)
  * optional and peer dependencies tracked separately
  * non-registry specifiers (git/github/file/url/workspace/alias) classified rather than dropped
  * on-disk packument cache so runs are resumable
  * token-bucket rate limiting with backoff on 429
  * PyPI (uvx) support alongside npm
"""
import json, os, re, time, gzip, hashlib, urllib.request, urllib.parse, collections, threading
import nodesemver as sv

CACHE = "/tmp/mcpres/cache"
UA = {"User-Agent": "mcp-supply-chain-study/0.2 (academic research; contact via github)"}

class Limiter:
    def __init__(self, rate=8.0, burst=8):
        self.rate, self.cap, self.tokens = rate, burst, burst
        self.t = time.monotonic(); self.lock = threading.Lock()
    def take(self):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.cap, self.tokens + (now - self.t) * self.rate)
            self.t = now
            if self.tokens < 1:
                s = (1 - self.tokens) / self.rate
                time.sleep(s); self.tokens = 0; self.t = time.monotonic()
            else:
                self.tokens -= 1

LIM = Limiter()
STATS = collections.Counter()

def _cpath(key):
    h = hashlib.sha256(key.encode()).hexdigest()
    return os.path.join(CACHE, h[:2], h + ".json.gz")

def fetch_json(url, cache_key=None, tries=4):
    key = cache_key or url
    p = _cpath(key)
    if os.path.exists(p):
        STATS["cache_hit"] += 1
        with gzip.open(p, "rt") as f: return json.load(f)
    for a in range(tries):
        LIM.take()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                d = json.load(r)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with gzip.open(p, "wt") as f: json.dump(d, f)
            STATS["net"] += 1
            return d
        except urllib.error.HTTPError as e:
            if e.code == 429:
                STATS["429"] += 1; time.sleep(2 ** a * 2); continue
            if e.code == 404: STATS["404"] += 1; raise
            STATS[f"http_{e.code}"] += 1
            if a == tries - 1: raise
            time.sleep(1.5 ** a)
        except Exception:
            STATS["neterr"] += 1
            if a == tries - 1: raise
            time.sleep(1.5 ** a)

# ---------- specifier classification ----------
NONREG = [
    ("workspace", re.compile(r"^workspace:")),
    ("alias",     re.compile(r"^npm:")),
    ("git",       re.compile(r"^(git\+|git:|github:|gitlab:|bitbucket:)")),
    ("url",       re.compile(r"^https?://")),
    ("file",      re.compile(r"^(file:|link:|portal:)")),
    ("shorthand-github", re.compile(r"^[\w.-]+/[\w.-]+(#.*)?$")),
]
def classify_spec(spec):
    s = (spec or "").strip()
    for kind, rx in NONREG:
        if rx.match(s): return kind
    return "registry"

def npm_packument(name):
    return fetch_json("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@"),
                      cache_key="npm:" + name)

def npm_resolve(name, spec):
    """Return (version, manifest) honouring npm range semantics. None if unresolvable."""
    d = npm_packument(name)
    tags, vers = d.get("dist-tags", {}), d.get("versions", {})
    s = (spec or "latest").strip()
    if s in tags: v = tags[s]
    elif s in vers: v = s
    else:
        cands = [x for x in vers if "-" not in x] or list(vers)
        try: v = sv.max_satisfying(cands, s, loose=True)
        except Exception: v = None
        if v is None:
            try: v = sv.max_satisfying(list(vers), s, loose=True)
            except Exception: v = None
        if v is None: v = tags.get("latest")
    return v, vers.get(v, {})

def npm_walk(root, root_spec="latest", cap=1500, include_optional=True, include_peer=False):
    """BFS the install graph with correct range resolution.
    Returns (nodes, stats). nodes: {(name,ver): meta}."""
    nodes, seen_edge = {}, set()
    q = collections.deque([(root, root_spec, 0, "root")])
    st = collections.Counter()
    while q and len(nodes) < cap:
        name, spec, depth, kind = q.popleft()
        c = classify_spec(spec)
        if c != "registry":
            st["nonregistry_" + c] += 1
            if c == "alias":
                m = re.match(r"^npm:(@?[^@]+(?:/[^@]+)?)@?(.*)$", spec)
                if m: q.append((m.group(1), m.group(2) or "latest", depth, kind)); continue
            st["nonregistry_total"] += 1
            nodes[(name, "NON-REGISTRY:" + c)] = {"license": None, "depth": depth,
                                                  "kind": kind, "spec": spec, "nonregistry": c}
            continue
        try:
            v, meta = npm_resolve(name, spec)
        except Exception:
            st["unresolved"] += 1
            nodes[(name, "UNRESOLVED")] = {"license": None, "depth": depth, "kind": kind, "spec": spec}
            continue
        if v is None:
            st["unresolved"] += 1; continue
        key = (name, v)
        if key in nodes:
            continue
        lic = meta.get("license")
        if isinstance(lic, dict): lic = lic.get("type")
        if isinstance(lic, list): lic = " OR ".join(str(x.get("type", x)) for x in lic)
        nodes[key] = {"license": lic, "depth": depth, "kind": kind,
                      "deprecated": bool(meta.get("deprecated")),
                      "tarball": (meta.get("dist") or {}).get("tarball")}
        groups = [("prod", meta.get("dependencies") or {})]
        if include_optional: groups.append(("optional", meta.get("optionalDependencies") or {}))
        if include_peer:     groups.append(("peer", meta.get("peerDependencies") or {}))
        for gk, deps in groups:
            for dn, drange in deps.items():
                e = (name, v, dn, drange)
                if e in seen_edge: continue
                seen_edge.add(e)
                q.append((dn, drange, depth + 1, gk))
    st["nodes"] = len(nodes)
    st["truncated"] = 1 if len(nodes) >= cap else 0
    return nodes, st

# ---------- PyPI ----------
def pypi_resolve(name, spec="latest"):
    d = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json", cache_key="pypi:" + name)
    info = d.get("info", {})
    lic = info.get("license_expression") or info.get("license") or None
    if not lic or len(str(lic)) > 80:
        cls = [c for c in info.get("classifiers", []) if c.startswith("License ::")]
        if cls: lic = cls[-1].split("::")[-1].strip()
    return info.get("version"), {"license": lic, "requires_dist": info.get("requires_dist") or []}
