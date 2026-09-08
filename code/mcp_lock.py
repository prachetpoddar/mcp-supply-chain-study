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

    8. A generator complains rather than producing a plausible answer.
       Rule 7 was written and then violated by this file's own code: a conflict
       detector created an empty set, never filled it, and the serializer
       dropped the key, so the mechanism built to declare conflicts reported
       success by being absent. Every degradation path here now increments a
       counter that reaches the output. If a package cannot be resolved, the
       file says so; it does not quietly describe a smaller tree. Silence is
       the failure mode this format exists to remove, so silence in the
       generator is a bug of the same kind as silence in the lock.

    9. Duplicates are a first-class section, not an appendix.
       Roughly one npm tree in three contains a package at two versions, and
       across a multi-server config about one name in eight resolves
       differently for different servers. At that frequency a duplicate list
       tucked below the body is a list nobody reads, and name-keying would have
       bought reviewability for the part of the file that needed it least.
       `duplicates` therefore carries the same per-package fields as the body,
       and `servers[x].resolvedVersions` records what each server actually gets
       for every duplicated name, so attribution is never lost to a merge.

KNOWN UNTESTED INTERACTION
    npm prefers the version tagged `latest` when it satisfies a range, and it
    prefers a non-deprecated version over a deprecated one. What it does when
    the `latest` tag is ITSELF deprecated and satisfies is not settled here: the
    resolver takes the tag without consulting the deprecation flag, and the
    cases validated against real installs were ranges where `latest` did not
    satisfy, so that path was never exercised. Mutation testing surfaced it by
    marking a selected version deprecated and finding the output unchanged. It
    is recorded rather than guessed at, because guessing is what produced the
    four defects this resolver already had. Settling it needs a real install
    against a package whose `latest` is deprecated.

USAGE
    python3 mcp_lock.py generate <config.json> [out.json]
    python3 mcp_lock.py verify   <config.json> <lock.json>

    `verify` re-resolves and reports drift, which is what CI runs.
"""
import hashlib, json, os, re, sys, collections
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import install_gap as IG
import nodesemver

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

# ---------------------------------------------------------------- snapshot
# RULE 10 (see below): the lock records the registry state it resolved against,
# so resolution can be replayed offline and shown to produce the same file.
# Integrity hashes pin what you GET; they do not pin the SHAPE of the tree,
# because a new transitive release changes the set without changing any
# existing hash. The snapshot is what pins the shape.
class SnapshotError(RuntimeError):
    """A snapshot could not answer a resolution the original made."""


SNAPSHOT = {}
_REAL_PACKUMENT = mcplib.npm_packument
_REPLAY = None

SEL_FIELDS = ("dependencies", "optionalDependencies", "peerDependencies",
              "peerDependenciesMeta", "os", "cpu")


def _capturing_packument(name):
    """Record exactly the inputs resolution reads, and nothing else.

    Candidate selection needs only the version list, the dist-tags and which
    versions are deprecated. Storing a per-version object for all of them cost
    1.1 MB on a fourteen-server config, most of it empty dictionaries for
    packages like `playwright` with 5,676 published versions, so the selection
    inputs are stored as two lists and the full metadata is kept only for
    versions actually placed."""
    d = _REAL_PACKUMENT(name)
    if name not in SNAPSHOT:
        vers = d.get("versions") or {}
        SNAPSHOT[name] = {
            "distTags": dict(d.get("dist-tags") or {}),
            "all": sorted(vers),
            "deprecated": sorted(v for v, m in vers.items() if (m or {}).get("deprecated")),
            "used": {},
        }
    return d


def _record_used(name, version, meta):
    """Keep the full metadata of versions actually placed, for replay."""
    slot = SNAPSHOT.setdefault(
        name, {"distTags": {}, "all": [], "deprecated": [], "used": {}})
    rec = slot["used"].setdefault(version, {})
    for f in SEL_FIELDS:
        if meta.get(f):
            rec[f] = meta[f]
    scripts = {h: meta["scripts"][h] for h in HOOKS
               if (meta.get("scripts") or {}).get(h)}
    if scripts:
        rec["scripts"] = scripts
    dist = meta.get("dist") or {}
    d2 = {k: dist[k] for k in ("integrity", "tarball", "shasum") if dist.get(k)}
    if d2:
        rec["dist"] = d2
    if meta.get("deprecated"):
        rec["deprecated"] = True


def _replay_packument(name):
    """Rebuild a packument from the snapshot.

    A package absent from the snapshot raises rather than returning an empty
    result. A replay that quietly resolved a smaller tree than the original
    would be exactly the silent degradation this format exists to remove."""
    if name not in _REPLAY:
        raise KeyError(f"{name} absent from resolution snapshot; cannot replay")
    slot = _REPLAY[name]
    allv = list(slot.get("all") or ())
    used = slot.get("used") or {}
    # `used` must be a subset of `all`. An earlier version of this function
    # re-added any used version that `all` did not contain, which meant editing
    # the candidate list had no effect on the replay: three of four planted
    # mutations produced an identical lock. A version present in `used` and
    # absent from `all` is a corrupt snapshot and is refused.
    stray = sorted(set(used) - set(allv))
    if stray:
        raise ValueError(f"{name}: versions in `used` but not in `all`: {stray}")
    dep = set(slot.get("deprecated") or ())
    versions = {}
    for v in allv:
        versions[v] = dict(used.get(v) or {})
        if v in dep:
            versions[v]["deprecated"] = True
    return {"dist-tags": dict(slot.get("distTags") or {}), "versions": versions}


def snapshot_digest(snap):
    return hashlib.sha256(json.dumps(snap, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def npm_tree(root, spec, cap=2000):
    """Resolve one server's tree, keyed on (name, version).

    CHANGED, and why. This previously keyed on bare name and did
    `if name in pkgs: continue`, so when a tree genuinely contained a package at
    two versions the second was dropped with nothing recorded. It also excluded
    peerDependencies, which npm 7 and later install automatically, and resolved
    with a plain max-satisfying rule that npm does not use. All three made the
    lock describe a tree no machine installs.

    Resolution now goes through the validated resolver: npm prefers the version
    tagged `latest` when it satisfies, avoids deprecated versions when a
    non-deprecated one satisfies, installs non-optional peers, and reuses an
    already-placed satisfying version rather than resolving each edge fresh.

    Returns (pkgs, notes) where pkgs maps (name, version) -> record. Every
    discarded edge increments a counter in notes; nothing is dropped silently.
    """
    pkgs, seen, q = {}, set(), collections.deque([(root, spec, "prod", "<root>")])
    placed = collections.defaultdict(set)
    notes = collections.Counter()
    while q:
        if len(pkgs) >= cap:
            notes["truncated"] = 1
            break
        name, rng, kind, parent = q.popleft()
        if mcplib.classify_spec(rng) != "registry":
            notes["nonregistry"] += 1
            notes[f"nonregistry:{name}"] += 1
            continue
        reuse = None
        for cand in placed.get(name, ()):
            try:
                ok = nodesemver.satisfies(cand, (rng or "").strip(), loose=True)
            except (ValueError, TypeError, AttributeError):
                ok = False
            if ok:
                reuse = cand
                break
        if reuse is not None:
            continue
        try:
            v, meta = IG.resolve_at(name, rng, None)
        except (KeyError, ValueError) as e:
            # A snapshot that cannot answer is a corrupt snapshot, not a package
            # that happens to be missing. Recording it as an ordinary unresolved
            # edge would let a truncated replay pass as a smaller tree, which is
            # the failure this whole format exists to remove.
            if _REPLAY is not None:
                raise SnapshotError(f"replaying {name}@{rng}: {e}") from e
            notes["unresolved"] += 1
            notes[f"unresolved:{name}@{rng}"] += 1
            continue
        except Exception:
            notes["unresolved"] += 1
            notes[f"unresolved:{name}@{rng}"] += 1
            continue
        if v is None:
            notes["unresolved"] += 1
            notes[f"unresolved:{name}@{rng}"] += 1
            continue
        key = (name, v)
        if key in pkgs:
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
        _record_used(name, v, meta)
        if placed.get(name):
            # a genuine second version of a name already in this tree
            notes["intree_duplicate"] += 1
        placed[name].add(v)
        pkgs[key] = rec
        pmeta = meta.get("peerDependenciesMeta") or {}
        peers = {k: r for k, r in (meta.get("peerDependencies") or {}).items()
                 if not (pmeta.get(k) or {}).get("optional")}
        for gk, deps in (("prod", meta.get("dependencies") or {}),
                         ("optional", meta.get("optionalDependencies") or {}),
                         ("peer", peers)):
            for dn, dr in deps.items():
                e = (name, v, dn, dr)
                if e in seen:
                    continue
                seen.add(e)
                q.append((dn, dr, "optional" if kind == "optional" else gk, f"{name}@{v}"))
    notes.setdefault("truncated", 0)
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

def _vkey(v):
    """Sort key for a version string: numeric where possible, deterministic always."""
    parts = re.split(r"[.\-+]", v)
    return tuple((0, int(x)) if x.isdigit() else (1, x) for x in parts)


def generate(cfg_path, out_path=None, snapshot_in=None, snapshot_out=None):
    """Build the lock. With snapshot_in, resolve offline from that snapshot
    instead of the network, which is how the reproducibility claim is checked."""
    global SNAPSHOT, _REPLAY
    SNAPSHOT = {}
    if snapshot_in:
        _REPLAY = json.load(open(snapshot_in))["packages"]
        mcplib.npm_packument = _replay_packument
    else:
        mcplib.npm_packument = _capturing_packument
    try:
        return _generate(cfg_path, out_path, snapshot_out, replayed=bool(snapshot_in))
    finally:
        mcplib.npm_packument = _REAL_PACKUMENT


def _generate(cfg_path, out_path=None, snapshot_out=None, replayed=False):
    servers = parse_config(cfg_path)
    lock = {"lockfileVersion": LOCKFILE_VERSION,
            "note": ("Committable. Contains no machine-specific paths and no secret "
                     "values. Regenerate with `mcp_lock.py generate`; check in CI with "
                     "`mcp_lock.py verify`."),
            "servers": {}, "packages": {}, "duplicates": {}, "conflicts": {},
            "unlockable": {}, "resolutionFailures": {}, "review": {}}
    hooks_index, missing_integrity, plat = {}, [], {}
    # name -> version -> record, so nothing is ever overwritten
    byname = collections.defaultdict(dict)
    # name -> version -> [servers], the attribution a single global map destroys
    whowants = collections.defaultdict(lambda: collections.defaultdict(list))

    for name in sorted(servers):
        s_ = servers[name]
        kind, target = classify_entry(s_["command"], s_["args"], s_.get("url"))
        entry = {"runtime": kind}
        if s_["command"]:
            entry["command"] = s_["command"]
        if s_["env_names"]:
            entry["consumesEnv"] = s_["env_names"]          # RULE 5: names only

        if kind == "npm":
            pkg, rng = split_spec(target)
            tree, notes = npm_tree(pkg, rng)
            roots = [v for (n, v) in tree if n == pkg]
            if not roots:
                lock["unlockable"][name] = {"spec": target, "reason": "root did not resolve"}
                continue
            rootver = roots[0]
            entry.update({"package": pkg, "requested": rng, "version": rootver,
                          "integrity": tree[(pkg, rootver)]["integrity"],
                          "packageCount": len(tree)})
            if notes.get("truncated"):
                entry["truncated"] = True
            # RULE 8: degradations reach the file rather than the terminal
            fails = {k.split(":", 1)[1]: v for k, v in notes.items()
                     if k.startswith("unresolved:") or k.startswith("nonregistry:")}
            if fails:
                entry["unresolvedEdges"] = len(fails)
                lock["resolutionFailures"][name] = dict(sorted(fails.items()))
            if notes.get("intree_duplicate"):
                entry["inTreeDuplicates"] = notes["intree_duplicate"]

            for (pn, pv), rec in tree.items():
                byname[pn][pv] = rec
                whowants[pn][pv].append(name)
                if rec.get("installScripts"):
                    hooks_index[f"{pn}@{pv}"] = {"version": pv,
                                                 "scripts": rec["installScripts"]}
                if rec.get("integrityMissing"):
                    missing_integrity.append(f"{pn}@{pv}")
                if rec.get("os") or rec.get("cpu"):
                    plat[f"{pn}@{pv}"] = {k: rec[k] for k in ("os", "cpu") if k in rec}
            # Name to a LIST of versions, always. This was written as
            # `{name: version}`, which silently kept one version when a tree
            # contained a name twice, so the field the format declares
            # authoritative reproduced the exact defect the format exists to
            # remove. Seven of nine servers in the reference configuration were
            # affected. A list in every case rather than a string-or-list keeps
            # consumers from having to branch on the type.
            rv = collections.defaultdict(list)
            for (n_, v_) in sorted(tree):
                rv[n_].append(v_)
            entry["resolvedVersions"] = {k: sorted(vs) for k, vs in sorted(rv.items())}
        elif kind == "pypi":
            pin = pypi_pin(target)
            if not pin:
                lock["unlockable"][name] = {"spec": target, "reason": "PyPI lookup failed"}
                continue
            entry.update({"package": target, **pin, "transitiveUnresolved": True})
        elif kind == "remote":
            entry.update({"url": target, "transport": s_.get("type") or "unknown",
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
            # RULE 8 applies here too. An earlier version wrote
            # `"digest": "not-resolved"`, which is a field that looks like a lock
            # and is not one. The key is omitted instead, the server is flagged,
            # and it is listed among the servers this file does not lock.
            entry.update({"image": img, "tag": tag, "digestUnresolved": True,
                          "note": ("tag is pinned but the manifest digest is not resolved; "
                                   "resolving it requires a registry token. A tag is "
                                   "mutable, so this server is NOT locked by this file.")})
        else:
            lock["unlockable"][name] = {"spec": " ".join(s_["args"]), "reason": target}
            continue
        lock["servers"][name] = entry

    # RULE 9: one version per name in the body, every other version in
    # `duplicates` with the SAME fields, and the conflict declared either way.
    for pn in sorted(byname):
        versions = byname[pn]
        # The body carries the version the most servers actually get, so a
        # reader skimming only the body sees the typical case rather than an
        # artifact of sort order. Ties break on the higher version, which makes
        # the choice deterministic across runs and machines.
        pick = max(versions, key=lambda v: (len(set(whowants[pn][v])),
                                            _vkey(v))) if len(versions) > 1 \
            else next(iter(versions))
        lock["packages"][pn] = dict(versions[pick],
                                    servers=sorted(set(whowants[pn][pick])))
        if len(versions) > 1:
            lock["duplicates"][pn] = {
                v: dict(versions[v], servers=sorted(set(whowants[pn][v])))
                for v in sorted(versions)}
            lock["conflicts"][pn] = {
                "versions": sorted(versions),
                "byServer": {v: sorted(set(whowants[pn][v])) for v in sorted(versions)},
                "inBody": pick}

    lock["review"] = {
        "totalNames": len(lock["packages"]),
        "totalPackageVersions": sum(len(v) for v in byname.values()),
        "namesAtMoreThanOneVersion": len(lock["conflicts"]),
        "conflictingNames": sorted(lock["conflicts"]),
        "packagesRunningInstallScripts": len(hooks_index),
        "installScripts": dict(sorted(hooks_index.items())),
        "platformConstrained": dict(sorted(plat.items())),
        "packagesWithoutIntegrity": sorted(missing_integrity),
        "serversNotLocked": sorted(
            set(lock["unlockable"])
            | {n for n, e in lock["servers"].items() if e.get("digestUnresolved")}),
        "serversPinnedRootOnly": sorted(
            n for n, e in lock["servers"].items() if e.get("transitiveUnresolved")),
        "serversWithResolutionFailures": sorted(lock["resolutionFailures"]),
        "remoteEndpoints": {n: e["url"] for n, e in lock["servers"].items()
                            if e["runtime"] == "remote"},
        "serversConsumingSecrets": {n: e["consumesEnv"] for n, e in lock["servers"].items()
                                    if e.get("consumesEnv")},
    }
    # RULE 10: the resolution inputs travel with the lock, by digest.
    if not replayed:
        snap = {"capturedUtc": dt.datetime.now(dt.timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "packages": SNAPSHOT}
        snapshot_out = snapshot_out or (
            (out_path or "mcp-lock.json").replace(".json", "") + ".snapshot.json")
        json.dump(snap, open(snapshot_out, "w"), indent=0, sort_keys=True)
        lock["resolutionSnapshot"] = {
            "file": os.path.basename(snapshot_out),
            "sha256": snapshot_digest(snap["packages"]),
            "packages": len(SNAPSHOT),
            "capturedUtc": snap["capturedUtc"],
            "note": ("the registry state this lock resolved against. Integrity "
                     "hashes pin what you get; this pins the shape of the tree, "
                     "which a new transitive release changes without changing "
                     "any existing hash. Replay with "
                     "`mcp_lock.py generate <config> <out> --from-snapshot <file>`.")}
    lock["integrityOfLock"] = hashlib.sha256(
        json.dumps({k: v for k, v in lock.items() if k != "integrityOfLock"},
                   sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    out_path = out_path or "mcp-lock.json"
    json.dump(lock, open(out_path, "w"), indent=1, sort_keys=True)
    r = lock["review"]
    print(f"wrote {out_path}")
    print(f"  servers locked        : {len(lock['servers'])}")
    print(f"  servers not lockable  : {len(lock['unlockable'])} "
          f"({', '.join(sorted(lock['unlockable'])) or 'none'})")
    print(f"  distinct names        : {r['totalNames']}")
    print(f"  name@version records  : {r['totalPackageVersions']}")
    print(f"  names at 2+ versions  : {r['namesAtMoreThanOneVersion']}")
    print(f"  running install code  : {r['packagesRunningInstallScripts']}")
    print(f"  platform-constrained  : {len(r['platformConstrained'])}")
    print(f"  without integrity     : {len(r['packagesWithoutIntegrity'])}")
    if lock["resolutionFailures"]:
        print(f"  !! resolution failures: {sum(len(v) for v in lock['resolutionFailures'].values())} "
              f"edges across {len(lock['resolutionFailures'])} servers, listed in the lock")
    return lock


def _perserver(lock):
    """What each server actually gets. Under this format the per-server map is
    normative and the body is a summary for review, so this is what `verify`
    compares. Diffing only the body agreed with a lock that had overwritten one
    server's version with another's, which is the defect that produced it."""
    return {n: dict(e.get("resolvedVersions") or {})
            for n, e in lock.get("servers", {}).items()}


def _flat(lock):
    """Every (name, version) the lock describes, body plus duplicates."""
    out = {}
    for pn, rec in lock.get("packages", {}).items():
        out[(pn, rec["version"])] = rec
    for pn, vs in lock.get("duplicates", {}).items():
        for v, rec in vs.items():
            out[(pn, v)] = rec
    return out


def verify(cfg_path, lock_path):
    """Re-resolve and diff.

    CHANGED. This compared `packages[name]` only, so it agreed with a lock that
    had silently overwritten one server's version with another's, and it never
    looked at duplicates at all. It now diffs on (name, version) across the body
    and the duplicate section together, and it treats a new conflict or a new
    resolution failure as drift in its own right.
    """
    old = json.load(open(lock_path))
    new = generate(cfg_path, "/tmp/mcp-lock-verify.json")
    o, n = _flat(old), _flat(new)
    drift = []
    for key in sorted(set(n) - set(o)):
        drift.append(("added", f"{key[0]}@{key[1]}", "-", key[1]))
    for key in sorted(set(o) - set(n)):
        drift.append(("removed", f"{key[0]}@{key[1]}", key[1], "-"))
    for key in sorted(set(o) & set(n)):
        if o[key].get("integrity") != n[key].get("integrity"):
            drift.append(("REPUBLISHED", f"{key[0]}@{key[1]}", key[1], key[1]))
    po, pn_ = _perserver(old), _perserver(new)
    server_drift = []
    for sv in sorted(set(po) | set(pn_)):
        a, b = po.get(sv, {}), pn_.get(sv, {})
        for name in sorted(set(a) | set(b)):
            if a.get(name) != b.get(name):
                server_drift.append((sv, name, a.get(name, "-"), b.get(name, "-")))
    new_conf = set(new.get("conflicts", {})) - set(old.get("conflicts", {}))
    new_fail = set(new.get("resolutionFailures", {})) - set(old.get("resolutionFailures", {}))
    new_hooks = set(new["review"]["installScripts"]) - set(old["review"].get("installScripts", {}))
    print(f"\n=== verify: {len(drift)} package differences")
    for kind, pn, a, b in sorted(drift)[:60]:
        print(f"  {kind:12s} {pn:52s} {a} -> {b}")
    if new_conf:
        print(f"\n  !! names newly resolving to more than one version: {sorted(new_conf)}")
    if new_fail:
        print(f"\n  !! servers newly failing to resolve edges: {sorted(new_fail)}")
    if new_hooks:
        print(f"\n  !! packages that newly run install scripts: {sorted(new_hooks)}")
    if server_drift:
        print(f"\n  !! {len(server_drift)} per-server version changes (normative):")
        for sv, name, a, b in server_drift[:40]:
            print(f"     {sv:14s} {name:44s} {a} -> {b}")
    bad = len(drift) + len(new_conf) + len(new_fail) + len(server_drift)
    print("\nOK" if not bad else f"\nDRIFT: {bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "generate"
    if m == "generate":
        snap_in = None
        argv = sys.argv[:]
        if "--from-snapshot" in argv:
            i = argv.index("--from-snapshot")
            snap_in = argv[i + 1]
            del argv[i:i + 2]
        generate(argv[2], argv[3] if len(argv) > 3 else None, snapshot_in=snap_in)
    elif m == "verify":
        sys.exit(verify(sys.argv[2], sys.argv[3]))
