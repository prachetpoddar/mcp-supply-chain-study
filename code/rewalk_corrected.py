#!/usr/bin/env python3
"""
Re-walk the 250 MCP server trees through the CORRECTED resolver.

WHY
    The repository holds two resolvers that disagree. install_gap.resolve_at
    implements npm's rule (the version tagged `latest` when it satisfies the
    range, then the highest non-deprecated satisfying version, then the highest
    satisfying version). mcplib.npm_resolve implements neither preference and
    goes straight to max_satisfying.

    validate_installs.py validates install_gap.resolve_at, so the 6,144 of 6,146
    figure covers that path only. walk250.jsonl was produced by mcplib.npm_walk,
    and the artifact proves it: it holds get-intrinsic@1.3.1 where the latest
    tag is 1.3.0, and koa-compose@4.2.0 where the clean 4.1.0 is latest. Neither
    corrected rule can produce either version.

    The published numbers do not move (row 3 of Section 6 is 43 of 250 trees
    under both rules). What is broken is reproducibility: the released code does
    not reproduce the released corpus. This script closes that.

SEPARATING THE RULE CHANGE FROM REGISTRY DRIFT
    A re-walk today mixes two effects. resolve_at takes a cutoff, so run it
    twice:

        python3 code/rewalk_corrected.py run 2026-09-07T12:24:00Z
        python3 code/rewalk_corrected.py run none
        python3 code/rewalk_corrected.py diff

    The dated run resolves against the registry as it stood when walk250 was
    built, so its difference from walk250 is the rule change alone. The undated
    run is today's state, and its difference from the dated run is drift.

    One approximation, inherited and counted rather than hidden: a packument
    keeps only today's dist-tag map, so a dated run still reads today's `latest`.
    install_gap counts those edges as tag_edges_approximated. Where the tag has
    moved since the cutoff the dated run is not a true time-travel, and the
    counter says how many edges that could touch.

    The walk is otherwise identical to the original: same roots, same
    include_optional=True, same include_peer=False, same node cap. One variable
    changes at a time.
"""
import collections, json, os, platform, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mcplib
import install_gap as IG

DATA = os.path.join(os.path.dirname(HERE), "data")
ROOTS = os.path.join(DATA, "mcp_roots.json")
ORIG = os.path.join(DATA, "walk250.jsonl")


def out_path(cutoff):
    tag = "asof" if cutoff else "today"
    return os.path.join(DATA, f"walk250_corrected_{tag}.jsonl")


def carry_over():
    """declared and direct came from stage-1 metadata in the original run, not
    from the walk. Carrying them across keeps the node set the only variable
    that changes between the two files."""
    out = {}
    if os.path.exists(ORIG):
        with open(ORIG) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if "pkgs" in d:
                    out[d["name"]] = (d.get("declared"), d.get("direct"))
    return out


ONLY = set()


def run(cutoff, budget):
    roots = json.load(open(ROOTS))
    carried = carry_over()
    path = out_path(cutoff)
    done = set()
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                # A zero-node record is a failure, not a result. Treating it as
                # done is how two empty trees survived into a comparison and
                # looked like the resolver shrinking the corpus.
                if d.get("pkgs") is not None and len(d["pkgs"]) == 0:
                    continue
                done.add(d["name"])
    todo = [r for r in roots if r not in done]
    if ONLY:
        todo = [r for r in roots if r in ONLY]
        print(f"restricted to {len(todo)} named roots; their existing records will be "
              f"superseded by the appended ones")
    # Record the interpreter and the semver library. This run exists to isolate
    # one variable, and a different nodesemver would silently be a second one.
    # node-semver exposes no __version__, so read the installed distribution.
    # The original study recorded neither, which is why this run cannot be made
    # byte-identical to walk250 and can only be made rule-identical.
    semver_ver = "unknown"
    try:
        from importlib.metadata import version as _dist_version
        semver_ver = _dist_version("node-semver")
    except Exception:
        try:
            semver_ver = getattr(mcplib.sv, "__version__", "unknown")
        except Exception:
            pass
    env = {"python": sys.version.split()[0], "executable": sys.executable,
           "platform": platform.platform(), "nodesemver": semver_ver,
           "nodesemver_path": getattr(mcplib.sv, "__file__", None)}
    json.dump(env, open(os.path.join(
        DATA, f"rewalk_env_{'asof' if cutoff else 'today'}.json"), "w"), indent=1)
    print(f"python   : {env['python']} at {env['executable']}")
    print(f"nodesemver: {env['nodesemver']}")
    print(f"cutoff   : {cutoff or 'none (today)'}")
    print(f"output   : {path}")
    print(f"{len(roots)} roots, {len(done)} already done, {len(todo)} to walk")

    # Delegate resolution to the corrected rule, leaving the rest of npm_walk
    # untouched: reuse on (name, version), non-registry classification, the
    # optional/peer split and the node cap all stay exactly as they were.
    original = mcplib.npm_resolve
    mcplib.npm_resolve = lambda name, spec, **kw: IG.resolve_at(name, spec, cutoff)
    t0 = time.time()
    try:
        with open(path, "a") as f:
            for i, name in enumerate(todo):
                if time.time() - t0 > budget:
                    print(f"  budget reached at {i}/{len(todo)}")
                    break
                try:
                    nodes, st = mcplib.npm_walk(name, "latest",
                                                include_optional=True, include_peer=False)
                except Exception as e:
                    f.write(json.dumps({"name": name, "error": type(e).__name__}) + "\n")
                    f.flush()
                    continue
                dec, dir_ = carried.get(name, (None, None))
                if dec is None:
                    for (n, v), m in nodes.items():
                        if n == name and m.get("kind") == "root":
                            dec = m.get("license")
                            break
                if dir_ is None:
                    dir_ = sum(1 for m in nodes.values() if m.get("depth") == 1)
                rec = {"name": name, "declared": dec, "direct": dir_,
                       "nodes": len(nodes),
                       "maxdepth": max((m["depth"] for m in nodes.values()), default=0),
                       "stats": dict(st),
                       "pkgs": {f"{k[0]}@@{k[1]}": {"license": m.get("license"),
                                                    "kind": m.get("kind"),
                                                    "deprecated": bool(m.get("deprecated")),
                                                    "nonregistry": m.get("nonregistry")}
                                for k, m in nodes.items()}}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                if i % 10 == 0:
                    print(f"  {i}/{len(todo)}  {name}", flush=True)
    finally:
        mcplib.npm_resolve = original
    print(f"\nresolver counters: {dict(IG.TAGSTATS)}")
    json.dump(dict(IG.TAGSTATS),
              open(os.path.join(DATA, f"rewalk_tagstats_{'asof' if cutoff else 'today'}.json"), "w"))
    remaining = len(roots) - len(load(path))
    print(f"{remaining} roots still to walk; re-run until this reports 0")


def load(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if "pkgs" in d:
                out[d["name"]] = d
    return out


def diff():
    orig = load(ORIG)
    asof = load(out_path("asof"))
    today = load(out_path(None))
    print(f"walk250.jsonl                    {len(orig)} trees")
    print(f"walk250_corrected_asof.jsonl     {len(asof)} trees")
    print(f"walk250_corrected_today.jsonl    {len(today)} trees")
    if not asof:
        print("\nthe dated run has not been done yet; nothing to compare")
        return

    def compare(a, b, la, lb):
        shared = set(a) & set(b)
        if not shared:
            print(f"\n{la} vs {lb}: no shared trees")
            return
        changed, node_delta = 0, 0
        moved = collections.Counter()
        for t in shared:
            pa, pb = set(a[t]["pkgs"]), set(b[t]["pkgs"])
            if pa != pb:
                changed += 1
                node_delta += len(pb) - len(pa)
                for k in pa - pb:
                    moved[k.rsplit("@@", 1)[0]] += 1
        print(f"\n{la} vs {lb}, over {len(shared)} shared trees")
        print(f"  trees whose node set changed : {changed}")
        print(f"  net node change              : {node_delta:+d}")
        print(f"  packages most often replaced : {moved.most_common(8)}")
        da = sum(1 for t in shared if any(v['deprecated'] for v in a[t]['pkgs'].values()))
        db = sum(1 for t in shared if any(v['deprecated'] for v in b[t]['pkgs'].values()))
        print(f"  trees containing a deprecated package: {da} -> {db}")

    compare(orig, asof, "walk250 (mcplib, no preference)", "corrected at the original date")
    if today:
        compare(asof, today, "corrected at the original date", "corrected today")
        compare(orig, today, "walk250", "corrected today")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "diff"
    if mode == "run":
        cut = sys.argv[2] if len(sys.argv) > 2 else "none"
        cutoff = None if cut in ("none", "None", "-") else cut
        budget = float(sys.argv[3]) if len(sys.argv) > 3 else 3000
        if len(sys.argv) > 4:
            ONLY = set(sys.argv[4].split(","))
        run(cutoff, budget)
    else:
        diff()
