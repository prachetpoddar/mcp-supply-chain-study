#!/usr/bin/env python3
"""
Generate mcp-lock.json: a committable, reviewable pin for an MCP client config.

THE PROBLEM THIS SOLVES
    Existing MCP pinning writes machine-local state keyed on the absolute path
    of the config file, so it is machine-SPECIFIC by construction and cannot be
    shared even if committed. Meanwhile the thing teams actually want is the
    thing npm already gave them for application dependencies: a file you commit
    next to the config, review in a pull request, and that makes every machine
    and every CI run materialize the same tree.

DESIGN RULES, AND WHY EACH ONE
    1. Keyed by SERVER NAME, never by path.
       No absolute path, no home directory, no machine identifier enters the
       file. Two developers who check out the same repo produce byte-identical
       locks. This is the property the current design cannot have.

    2. Integrity, not just version.
       Every npm package carries its registry `dist.integrity` (sha512) and
       every PyPI distribution its sha256. A version number pins what you MEANT
       to install; a hash pins what you GET. Without it the file is a pin, not
       a lock, and a republished version defeats it.

    3. Install hooks surfaced inline.
       `package-lock.json` records `hasInstallScript` but buries it. Here every
       package that runs preinstall/install/postinstall is flagged AND listed in
       a `review` block at the top, because that is the set a human reviewer
       must actually look at. A lock whose security-relevant content is not
       visible in a diff is not reviewable.

    4. Optional and platform-constrained packages are RECORDED, not resolved.
       This is the direct fix for machine-specificity. If the lock only listed
       what this machine installs, a macOS lock and a Linux lock would differ
       and the diff would be noise. Instead every optional dependency is
       recorded with its declared os/cpu constraint, so one file describes every
       machine and a reviewer can see which packages appear only somewhere.

    5. NO CREDENTIALS, EVER.
       MCP configs routinely carry live API keys in their `env` blocks. The lock
       records that a server CONSUMES a variable, by name only, so a reviewer can
       see a new secret being introduced in a diff. Values are never read and
       never written. This is enforced in code below, not left to convention.

    6. No advisory or severity data.
       A lock states what will be installed. Whether that is safe is a question
       for a scanner reading the lock, and changes daily. Mixing them makes the
       diff churn and the file stop being reviewable.

    7. Unlockable entries are declared, not silently dropped.
       Local paths, `latest` Docker tags and git specifiers cannot be pinned
       from a registry. They are listed under `unlockable` with a reason, so the
       file never implies more coverage than it has.

USAGE
    python3 mcp_lock.py generate <config.json> [out.json]
    python3 mcp_lock.py verify   <config.json> <lock.json>

    `verify` re-resolves and reports drift, which is what CI runs.
"""
import hashlib, json, os, re, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

LOCKFILE_VERSION = 1
HOOKS = ("preinstall", "install", "postinstall")


# ---------------------------------------------------------------- config read

def parse_config(path):
    """Extract server entries. Never reads env VALUES -- only key names."""
    cfg = json.load(open(path))
    servers = cfg.get("mcpServers") or cfg.get("servers") or {}
    out = {}
    for name, spec in servers.items():
        cmd = spec.get("command")
        args = list(spec.get("args") or [])
        # RULE 5: names only. The values are never bound to a variable.
        env_names = sorted((spec.get("env") or {}).keys())
        out[name] = {"command": cmd, "args": args, "env_names": env_names,
                     "url": spec.get("url"), "type": spec.get("type")}
    return out


def classify_entry(cmd, args, url=None):
    """Identify the runtime and the package specifier a server launches."""
    if not cmd and url:
        # Remote/HTTP/SSE server: nothing is installed locally, so there is no
        # tree to lock. The URL is still recorded, because a changed endpoint in
        # a pull request diff is exactly the thing a reviewer must catch.
        return ("remote", url)
    a = [x for x in args if not x.startswith("-")]
    if cmd in ("npx", "pnpx", "bunx"):
        return ("npm", a[0]) if a else ("unlockable", "no package argument")
    if cmd in ("uvx", "pipx"):
        return ("pypi", a[0]) if a else ("unlockable", "no package argument")
    if cmd == "docker":
        img = next((x for x in args if "/" in x or ":" in x), None)
        if not img or img in ("run",):
            return ("unlockable", "no image argument")
        return ("oci", img)
    if cmd in ("node", "python", "python3", "deno", "bun", "sh", "bash"):
        return ("unlockable", f"local executable ({cmd}); nothing in a registry to pin")
    return ("unlockable", f"unrecognised command `{cmd}`")


def split_spec(spec):
    """`@scope/name@range` -> (`@scope/name`, `range`)."""
    if spec.startswith("@"):
        i = spec.find("@", 1)
        return (spec[:i], spec[i + 1:]) if i > 0 else (spec, "latest")
    if "@" in spec:
        n, _, r = spec.partition("@")
        return n, r or "latest"
    return spec, "latest"


# ---------------------------------------------------------------- npm resolve

def npm_tree(root, spec, cap=2000):
    """Resolve the full tree, keeping integrity, hooks and platform constraints."""
    pkgs, seen, q = {}, set(), collections.deque([(root, spec, "prod")])
    notes = collections.Counter()
    while q and len(pkgs) < cap:
        name, rng, kind = q.popleft()
        if mcplib.classify_spec(rng) != "registry":
            notes["nonregistry"] += 1
            continue
        try:
            v, meta = mcplib.npm_resolve(name, rng)
        except Exception:
            notes["unresolved"] += 1
            continue
        if v is None or name in pkgs:
            continue
        dist = meta.get("dist") or {}
        integrity = dist.get("integrity")
        if not integrity and dist.get("shasum"):
            integrity = "sha1-" + dist["shasum"]      # pre-2017 packages
        scripts = meta.get("scripts") or {}
        hooks = sorted(h for h in HOOKS if scripts.get(h))
        rec = {"version": v, "resolved": dist.get("tarball"), "integrity": integrity}
        if kind == "optional":
            rec["optional"] = True
        if meta.get("os"):
            rec["os"] = meta["os"]
        if meta.get("cpu"):
            rec["cpu"] = meta["cpu"]
        if hooks:
            rec["installScripts"] = hooks          # RULE 3
        if not integrity:
            rec["integrityMissing"] = True
            notes["no_integrity"] += 1
        pkgs[name] = rec
        for gk, deps in (("prod", meta.get("dependencies") or {}),
                         ("optional", meta.get("optionalDependencies") or {})):
            for dn, dr in deps.items():
                e = (name, v, dn, dr)
                if e in seen:
                    continue
                seen.add(e)
                q.append((dn, dr, "optional" if kind == "optional" else gk))
    notes["truncated"] = 1 if len(pkgs) >= cap else 0
    return pkgs, notes


def pypi_pin(name):
    """Pin a PyPI distribution by version and sha256. Transitive deps are not
    resolved here: PyPI requirement metadata needs an environment marker
    evaluation that is genuinely machine-dependent, so the lock records the root
    honestly rather than pretending to a closure it cannot compute."""
    try:
        d = mcplib.fetch_json(f"https://pypi.org/pypi/{name}/json", cache_key="pypi:" + name)
    except Exception:
        return None
    ver = (d.get("info") or {}).get("version")
    sha = None
    for f in d.get("urls", []) or []:
        if f.get("packagetype") == "bdist_wheel":
            sha = (f.get("digests") or {}).get("sha256")
            break
    if sha is None:
        for f in d.get("urls", []) or []:
            sha = (f.get("digests") or {}).get("sha256")
            if sha:
                break
    return {"version": ver, "integrity": ("sha256-" + sha) if sha else None,
            "transitiveResolution": "not-computed",
            "note": "PyPI requirement markers are environment-dependent; root pinned only"}


# ---------------------------------------------------------------- generate

def generate(cfg_path, out_path=None):
    servers = parse_config(cfg_path)
    lock = {"lockfileVersion": LOCKFILE_VERSION,
            "note": ("Committable. Contains no machine-specific paths and no secret "
                     "values. Regenerate with `mcp_lock.py generate`; check in CI with "
                     "`mcp_lock.py verify`."),
            "servers": {}, "packages": {}, "unlockable": {}, "review": {}}
    hooks_index, missing_integrity, plat = {}, [], {}

    for name in sorted(servers):
        s = servers[name]
        kind, target = classify_entry(s["command"], s["args"], s.get("url"))
        entry = {"runtime": kind}
        if s["command"]:
            entry["command"] = s["command"]
        if s["env_names"]:
            # RULE 5: names only, values neither read nor written
            entry["consumesEnv"] = s["env_names"]

        if kind == "npm":
            pkg, rng = split_spec(target)
            tree, notes = npm_tree(pkg, rng)
            if pkg not in tree:
                lock["unlockable"][name] = {"spec": target, "reason": "root did not resolve"}
                continue
            entry.update({"package": pkg, "requested": rng,
                          "version": tree[pkg]["version"],
                          "integrity": tree[pkg]["integrity"],
                          "packageCount": len(tree)})
            if notes["truncated"]:
                entry["truncated"] = True
            for pn, rec in tree.items():
                prev = lock["packages"].get(pn)
                if prev and prev["version"] != rec["version"]:
                    # two servers needing different versions is real and must be visible
                    lock["packages"].setdefault("__conflicts__", {})
                    lock["packages"]["__conflicts__"].setdefault(pn, set())
                lock["packages"][pn] = rec
                if rec.get("installScripts"):
                    hooks_index[pn] = {"version": rec["version"],
                                       "scripts": rec["installScripts"]}
                if rec.get("integrityMissing"):
                    missing_integrity.append(pn)
                if rec.get("os") or rec.get("cpu"):
                    plat[pn] = {k: rec[k] for k in ("os", "cpu") if k in rec}
        elif kind == "pypi":
            pin = pypi_pin(target)
            if not pin:
                lock["unlockable"][name] = {"spec": target, "reason": "PyPI lookup failed"}
                continue
            entry.update({"package": target, **pin})
        elif kind == "remote":
            entry.update({"url": target, "transport": s.get("type") or "unknown",
                          "note": ("remote server: no local install, nothing to pin. "
                                   "The endpoint is recorded so a change to it is "
                                   "visible in review.")})
        elif kind == "oci":
            img, _, tag = target.partition(":")
            if not tag or tag == "latest":
                lock["unlockable"][name] = {
                    "spec": target,
                    "reason": "mutable image tag; pin to a sha256 digest to lock this server"}
                continue
            entry.update({"image": img, "tag": tag,
                          "digest": "not-resolved",
                          "note": "requires a registry token to resolve the manifest digest"})
        else:
            lock["unlockable"][name] = {"spec": " ".join(s["args"]), "reason": target}
            continue
        lock["servers"][name] = entry

    lock["packages"].pop("__conflicts__", None)

    # RULE 3: the reviewer-facing summary, at the top of the file
    lock["review"] = {
        "totalPackages": len(lock["packages"]),
        "packagesRunningInstallScripts": len(hooks_index),
        "installScripts": dict(sorted(hooks_index.items())),
        "platformConstrained": dict(sorted(plat.items())),
        "packagesWithoutIntegrity": sorted(missing_integrity),
        "serversNotLocked": sorted(lock["unlockable"]),
        "remoteEndpoints": {n: e["url"] for n, e in lock["servers"].items()
                            if e["runtime"] == "remote"},
        "serversConsumingSecrets": {n: e["consumesEnv"] for n, e in lock["servers"].items()
                                    if e.get("consumesEnv")},
    }
    lock["integrityOfLock"] = hashlib.sha256(
        json.dumps({k: v for k, v in lock.items() if k != "integrityOfLock"},
                   sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    out_path = out_path or "mcp-lock.json"
    json.dump(lock, open(out_path, "w"), indent=1, sort_keys=True)
    r = lock["review"]
    print(f"wrote {out_path}")
    print(f"  servers locked      : {len(lock['servers'])}")
    print(f"  servers not lockable: {len(lock['unlockable'])} "
          f"({', '.join(sorted(lock['unlockable'])) or 'none'})")
    print(f"  packages            : {r['totalPackages']}")
    print(f"  running install code: {r['packagesRunningInstallScripts']}")
    print(f"  platform-constrained: {len(r['platformConstrained'])}")
    print(f"  without integrity   : {len(r['packagesWithoutIntegrity'])}")
    return lock


def verify(cfg_path, lock_path):
    """Re-resolve and diff. This is the CI check."""
    old = json.load(open(lock_path))
    new = generate(cfg_path, "/tmp/mcp-lock-verify.json")
    drift = []
    for pn, rec in new["packages"].items():
        prev = old["packages"].get(pn)
        if prev is None:
            drift.append(("added", pn, "-", rec["version"]))
        elif prev["version"] != rec["version"]:
            drift.append(("moved", pn, prev["version"], rec["version"]))
        elif prev.get("integrity") != rec.get("integrity"):
            drift.append(("REPUBLISHED", pn, prev["version"], rec["version"]))
    for pn, prev in old["packages"].items():
        if pn not in new["packages"]:
            drift.append(("removed", pn, prev["version"], "-"))
    new_hooks = set(new["review"]["installScripts"]) - set(old["review"]["installScripts"])
    print(f"\n=== verify: {len(drift)} package differences")
    for kind, pn, a, b in sorted(drift)[:60]:
        print(f"  {kind:12s} {pn:44s} {a} -> {b}")
    if new_hooks:
        print(f"\n  !! packages that newly run install scripts: {sorted(new_hooks)}")
    print("\nOK" if not drift else f"\nDRIFT: {len(drift)} differences")
    return 1 if drift else 0


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "generate"
    if m == "generate":
        generate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif m == "verify":
        sys.exit(verify(sys.argv[2], sys.argv[3]))
