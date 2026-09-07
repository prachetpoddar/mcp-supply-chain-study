#!/usr/bin/env python3
"""Resolve MCP server launch commands to concrete, licensed components."""
import json, re, sys, urllib.request, urllib.parse, concurrent.futures as cf, collections

NPM = "https://registry.npmjs.org/"
PYPI = "https://pypi.org/pypi/{}/json"
UA = {"User-Agent": "mcp-resolver-prototype/0.1 (evaluation)"}

def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

# ---------- 1. parse launch commands into package specs ----------
def parse_server(name, cfg):
    """Return dict describing what this server actually pulls."""
    out = {"server": name, "transport": None, "ecosystem": None,
           "identifier": None, "requested": None, "pinned": False, "note": None}
    if cfg.get("type") in ("http", "sse", "ws") or cfg.get("url"):
        out.update(transport="remote", note="remote endpoint; no local artifact")
        return out
    cmd = (cfg.get("command") or "").strip()
    args = [a for a in cfg.get("args", []) if isinstance(a, str)]
    out["transport"] = "stdio"
    if cmd in ("npx", "pnpm", "bunx", "yarn"):
        rest = [a for a in args if not a.startswith("-")]
        if not rest:
            out["note"] = "no package argument found"; return out
        spec = rest[0]
        m = re.match(r"^(@[^/]+/[^@]+|[^@][^@]*)(?:@(.+))?$", spec)
        ident, ver = (m.group(1), m.group(2)) if m else (spec, None)
        out.update(ecosystem="npm", identifier=ident, requested=ver or "latest",
                   pinned=bool(ver) and ver not in ("latest", "*", "next"))
    elif cmd in ("uvx", "pipx", "uv"):
        rest = [a for a in args if not a.startswith("-")]
        if rest and rest[0] == "run": rest = rest[1:]
        if not rest:
            out["note"] = "no package argument found"; return out
        spec = rest[0]
        m = re.match(r"^([A-Za-z0-9._-]+)(?:[=@]=?(.+))?$", spec)
        ident, ver = (m.group(1), m.group(2)) if m else (spec, None)
        out.update(ecosystem="pypi", identifier=ident, requested=ver or "latest",
                   pinned=bool(ver))
    elif cmd == "docker":
        imgs = [a for a in args if "/" in a or ":" in a]
        img = imgs[-1] if imgs else None
        tag = img.split(":")[-1] if img and ":" in img else "latest"
        out.update(ecosystem="oci", identifier=img, requested=tag,
                   pinned=bool(img) and img.count("@sha256:") > 0)
    else:
        out.update(ecosystem="local", identifier=" ".join([cmd]+args)[:60],
                   note="local script; not a registry artifact")
    return out

# ---------- 2. resolve + walk the dependency tree ----------
_npm_cache = {}
def npm_packument(name):
    if name not in _npm_cache:
        _npm_cache[name] = get(NPM + urllib.parse.quote(name, safe="@"))
    return _npm_cache[name]

def npm_pick(name, spec):
    d = npm_packument(name)
    tags, vers = d.get("dist-tags", {}), d.get("versions", {})
    if spec in tags: v = tags[spec]
    elif spec in vers: v = spec
    else: v = tags.get("latest")
    return v, vers.get(v, {})

def walk_npm(root, spec, max_nodes=400):
    """BFS the runtime dependency graph. Returns {(name,ver): meta}."""
    seen, queue, edges = {}, collections.deque([(root, spec)]), collections.defaultdict(set)
    while queue and len(seen) < max_nodes:
        name, s = queue.popleft()
        try: v, meta = npm_pick(name, s)
        except Exception as e:
            seen[(name, "UNRESOLVED")] = {"error": f"{type(e).__name__}"}; continue
        if v is None or (name, v) in seen: continue
        seen[(name, v)] = {"license": meta.get("license"),
                           "deprecated": bool(meta.get("deprecated")),
                           "dist": (meta.get("dist") or {}).get("tarball")}
        for dep, drange in (meta.get("dependencies") or {}).items():
            edges[(name, v)].add(dep)
            if not any(k[0] == dep for k in seen):
                queue.append((dep, "latest"))
    return seen, edges

def pypi_resolve(name, spec):
    d = get(PYPI.format(urllib.parse.quote(name)))
    info = d.get("info", {})
    v = info.get("version") if spec in (None, "latest") else spec
    lic = info.get("license") or None
    # PEP 639 / classifier fallback
    if not lic or len(lic) > 60:
        cls = [c for c in info.get("classifiers", []) if c.startswith("License ::")]
        lic = cls[-1].split("::")[-1].strip() if cls else lic
    return v, {"license": lic, "requires_dist": info.get("requires_dist") or []}

# ---------- main ----------
cfg = json.load(open(sys.argv[1]))
servers = cfg.get("mcpServers") or cfg.get("servers") or {}
parsed = [parse_server(n, c) for n, c in servers.items()]

results = []
for p in parsed:
    r = dict(p)
    if p["ecosystem"] == "npm":
        try:
            v, meta = npm_pick(p["identifier"], p["requested"])
            r.update(resolved_version=v, declared_license=meta.get("license"),
                     tarball=(meta.get("dist") or {}).get("tarball"))
        except Exception as e:
            r.update(resolved_version=None, error=f"{type(e).__name__}: {e}")
    elif p["ecosystem"] == "pypi":
        try:
            v, meta = pypi_resolve(p["identifier"], p["requested"])
            r.update(resolved_version=v, declared_license=meta.get("license"))
        except Exception as e:
            r.update(resolved_version=None, error=f"{type(e).__name__}: {e}")
    results.append(r)

json.dump(results, open("/tmp/mcpres/servers.json", "w"), indent=1)

W = 46
print(f"{'server':12s} {'eco':6s} {'identifier':38s} {'pin':4s} {'resolved':13s} license")
print("-"*118)
for r in results:
    print(f"{r['server']:12s} {str(r.get('ecosystem')):6s} {str(r.get('identifier'))[:38]:38s} "
          f"{'yes' if r.get('pinned') else 'NO':4s} {str(r.get('resolved_version'))[:13]:13s} "
          f"{str(r.get('declared_license'))[:40]}")

# ---------------- transitive walk ----------------
import json, sys, urllib.request, urllib.parse, collections, time
sys.path.insert(0,'/tmp/mcpres')
NPM="https://registry.npmjs.org/"; UA={"User-Agent":"mcp-resolver-prototype/0.1 (evaluation)"}
cache={}
def packument(n):
    if n not in cache:
        req=urllib.request.Request(NPM+urllib.parse.quote(n,safe='@'),headers=UA)
        with urllib.request.urlopen(req,timeout=30) as r: cache[n]=json.load(r)
    return cache[n]
def pick(n,spec):
    d=packument(n); t=d.get("dist-tags",{}); v=d.get("versions",{})
    ver = t[spec] if spec in t else (spec if spec in v else t.get("latest"))
    return ver, v.get(ver,{})
def walk(root,spec,cap=600):
    seen={}; edges=collections.defaultdict(set); q=collections.deque([(root,spec,0)]); errs=[]
    while q and len(seen)<cap:
        n,s,d=q.popleft()
        if any(k[0]==n for k in seen): continue
        try: ver,meta=pick(n,s)
        except Exception as e: errs.append((n,type(e).__name__)); continue
        if ver is None: errs.append((n,"no-version")); continue
        seen[(n,ver)]={"license":meta.get("license"),"depth":d,
                       "deprecated":bool(meta.get("deprecated")),
                       "tarball":(meta.get("dist") or {}).get("tarball")}
        for dep in (meta.get("dependencies") or {}):
            edges[(n,ver)].add(dep)
            if not any(k[0]==dep for k in seen): q.append((dep,"latest",d+1))
    return seen,edges,errs

servers=json.load(open('/tmp/mcpres/servers.json'))
targets=[s for s in servers if s.get('ecosystem')=='npm' and s.get('resolved_version')]
allpkgs={}; per={}
t0=time.time()
for s in targets:
    seen,edges,errs=walk(s['identifier'], s['requested'])
    per[s['server']]={"nodes":len(seen),"maxdepth":max((m['depth'] for m in seen.values()),default=0),"errors":len(errs)}
    for k,v in seen.items(): allpkgs.setdefault(k,v)
    print(f"  {s['server']:12s} {s['identifier'][:40]:40s} -> {len(seen):4d} packages, depth {per[s['server']]['maxdepth']}, {len(errs)} errors  ({time.time()-t0:.0f}s)")
json.dump({f"{k[0]}@{k[1]}":v for k,v in allpkgs.items()},open('/tmp/mcpres/tree.json','w'),indent=1)
json.dump(per,open('/tmp/mcpres/per_server.json','w'),indent=1)
print(f"\nUNION of distinct packages across {len(targets)} MCP servers: {len(allpkgs)}")
print(f"elapsed {time.time()-t0:.0f}s, registry requests {len(cache)}")
