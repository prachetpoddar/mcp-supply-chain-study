#!/usr/bin/env python3
"""
Measure the gap between a package's PUBLISHED dependency graph and the tree an
install actually materializes.

WHY THIS EXISTS
    Tools that answer "what does this server depend on" by querying a graph
    service for an exact (name, version) get the declared graph: the closure of
    dependency ranges as some snapshot resolved them. That is not what `npx` or
    `npm install` puts on disk. Four things live in the gap:

        1. semver ranges resolved at install time, not at publish time
        2. lockfile state
        3. platform-specific optional dependencies
        4. postinstall behaviour

    This script measures (1) and (3) directly, and reports (2) and (4) as
    counts, for the 250 MCP server configurations already walked.

METHOD FOR (1) -- RANGE DRIFT
    Walk each root twice from the same root version.

    NOTE ON WHAT THE FIRST ARM MODELS: freezing at publish time is a lockfile
    or an SBOM produced at release, not a graph service's answer -- a service
    resolves at its own crawl time and is far less stale. This arm therefore
    bounds the staleness component rather than estimating it.

      as-published   at every edge, resolve the range against only versions
                     whose registry publish time is <= the root version's own
                     publish time. This is the graph as it stood the day the
                     root shipped -- what a lockfile committed then, or a
                     published-graph snapshot taken then, would contain.

      as-installed   resolve against all versions. This is what an install
                     today materializes, and is the existing walk.

    The delta is the drift a published-graph answer cannot see. It is measured
    per tree in three classes, deliberately kept apart rather than netted:

      added        packages the install pulls in that the published graph has
                   no node for at all -- new transitive dependencies acquired
                   through a range since the root shipped
      dropped      packages in the published graph that the install no longer
                   materializes
      moved        same package, different version

    LIMIT, STATED: npm packuments record the CURRENT dist-tag mapping only, so
    a `latest` or other tag specifier cannot be time-travelled exactly. Under
    cutoff those resolve to the highest non-prerelease version published at or
    before the cutoff. Ranges -- which are the overwhelming majority of edges --
    are exact. Edges resolved by tag are counted and reported separately so the
    approximation is visible rather than buried.

METHOD FOR (3) -- PLATFORM / OPTIONAL
    The existing walk includes optionalDependencies without evaluating os/cpu
    constraints, so it is an upper bound on any one machine. This counts, per
    tree, the nodes reachable only through an optional edge and how many of
    those declare an os or cpu constraint -- the mass that is present on some
    machines and absent on others, which no single published-graph answer and
    no single lockfile represents.

    python3 install_gap.py run [seconds]
    python3 install_gap.py report
"""
import collections, json, os, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/install_gap.json"
TREES = os.path.join(HERE, "resolved_trees_for_depsdev.json")
CAP = 1500

TAGSTATS = collections.Counter()


def ptime(name):
    """{version: iso publish time} from the packument."""
    return mcplib.npm_packument(name).get("time", {}) or {}


def resolve_at(name, spec, cutoff):
    """Resolve `spec` using only versions published at or before `cutoff`.

    cutoff=None means resolve against everything (today's install).

    DEPRECATION HANDLING, added after ground-truth checking against a real
    `npm install`. npm's npm-pick-manifest does not simply take the highest
    version satisfying a range: it prefers a non-deprecated one and falls back
    to a deprecated version only when nothing else satisfies. Skipping this
    matters because deprecated versions are disproportionately the vulnerable
    ones, so a plain max-satisfying resolver systematically over-selects them
    and invents findings a real install never has.

    Verified empirically: `@whiskeysockets/baileys@^6.6.0` has 6.17.16 as the
    highest satisfying version (minor 17 sorts above 7), it is deprecated for a
    spoofing zero-day, and npm installs 6.7.24 instead. An exact pin of
    6.17.16 is still honoured, so the preference applies to ranges only."""
    d = mcplib.npm_packument(name)
    tags, vers, tm = d.get("dist-tags", {}), d.get("versions", {}), d.get("time", {}) or {}
    s = (spec or "latest").strip()

    if cutoff is None:
        avail = list(vers)
    else:
        avail = [v for v in vers if tm.get(v) and tm[v] <= cutoff]
    if not avail:
        return None, {}

    def live(v):
        return not (vers.get(v) or {}).get("deprecated")

    if s in tags:
        # dist-tag: cannot be time-travelled, packuments keep only today's map
        TAGSTATS["tag_edges"] += 1
        if cutoff is None:
            v = tags[s]
        else:
            TAGSTATS["tag_edges_approximated"] += 1
            plain = [v for v in avail if "-" not in v] or avail
            try:
                v = sv.max_satisfying(plain, "*", loose=True)
            except Exception:
                v = None
    elif s in vers:
        v = s if (cutoff is None or (tm.get(s) and tm[s] <= cutoff)) else None
    else:
        TAGSTATS["range_edges"] += 1
        plain = [v for v in avail if "-" not in v] or avail

        def pick(cands):
            try:
                return sv.max_satisfying(cands, s, loose=True)
            except Exception:
                return None

        def sat(x):
            try:
                return sv.satisfies(x, s, loose=True)
            except Exception:
                return False

        # npm-pick-manifest's real order, established by ground-truth install:
        #   1. the version tagged `latest`, IF it satisfies the range. npm takes
        #      it even when a higher version exists. n8n-workflow tags 2.16.0 as
        #      latest while 2.38.1 sits under `beta`, and `npm install` of a
        #      package peering on `*` materialises 2.16.0, not 2.38.1.
        #   2. otherwise the highest non-deprecated satisfying version
        #   3. otherwise the highest satisfying version at all
        lat = tags.get("latest")
        v = None
        if lat and lat in avail and sat(lat):
            v = lat
            TAGSTATS["latest_tag_preferred"] += 1
        if v is None:
            v = pick([x for x in plain if live(x)])
        if v is None:
            v = pick(plain)
            if v is not None:
                TAGSTATS["fell_back_to_deprecated"] += 1
        if v is None:
            v = pick([x for x in avail if live(x)]) or pick(avail)
    if v is None:
        return None, {}
    return v, vers.get(v, {})


def walk_at(root, root_version, cutoff, cap=CAP):
    """BFS from an exact root version, resolving every edge at `cutoff`.

    Returns {name: version} plus per-tree counters. Mirrors mcplib.npm_walk's
    edge handling (optional included, peer excluded) so the two arms differ
    only in the cutoff."""
    nodes, seen_edge = {}, set()
    q = collections.deque([(root, root_version, "root")])
    st = collections.Counter()
    optional_only = set()
    while q and len(nodes) < cap:
        name, spec, kind = q.popleft()
        if mcplib.classify_spec(spec) != "registry":
            st["nonregistry"] += 1
            continue
        try:
            v, meta = resolve_at(name, spec, cutoff)
        except Exception:
            st["unresolved"] += 1
            continue
        if v is None:
            st["unresolved"] += 1
            continue
        if name in nodes:
            continue
        nodes[name] = v
        if kind == "optional":
            optional_only.add(name)
            if meta.get("os") or meta.get("cpu"):
                st["platform_constrained"] += 1
        for gk, deps in (("prod", meta.get("dependencies") or {}),
                         ("optional", meta.get("optionalDependencies") or {})):
            for dn, drange in deps.items():
                e = (name, v, dn, drange)
                if e in seen_edge:
                    continue
                seen_edge.add(e)
                q.append((dn, drange, gk if kind != "optional" else "optional"))
    st["nodes"] = len(nodes)
    st["truncated"] = 1 if len(nodes) >= cap else 0
    st["optional_only"] = len(optional_only)
    return nodes, st


def run(budget):
    trees = json.load(open(TREES))
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [t for t in trees if t["root_name"] not in s]
    print(f"{len(todo)} roots to measure of {len(trees)}")
    t0 = time.time()
    for i, t in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        name, ver = t["root_name"], t["root_version"]
        try:
            tm = ptime(name)
            cutoff = tm.get(ver)
            if not cutoff:
                s[name] = {"skip": "no publish time for root version"}
                continue
            pub, pst = walk_at(name, ver, cutoff)
            now, nst = walk_at(name, ver, None)
        except Exception as e:
            s[name] = {"skip": repr(e)[:120]}
            continue
        added = sorted(set(now) - set(pub))
        dropped = sorted(set(pub) - set(now))
        moved = sorted(k for k in (set(pub) & set(now)) if pub[k] != now[k])
        s[name] = {
            "root_version": ver, "root_published": cutoff,
            "published_versions": pub, "installed_versions": now,
            "n_published": len(pub), "n_installed": len(now),
            "added": added, "dropped": dropped, "moved": moved,
            "n_added": len(added), "n_dropped": len(dropped), "n_moved": len(moved),
            "optional_only_installed": nst["optional_only"],
            "platform_constrained": nst["platform_constrained"],
            "truncated": bool(nst["truncated"] or pst["truncated"]),
            "unresolved_published": pst["unresolved"], "unresolved_installed": nst["unresolved"],
        }
        if i % 10 == 0:
            json.dump({"trees": s, "edge_stats": dict(TAGSTATS)}, open(STATE, "w"))
            print(f"  {i}/{len(todo)} {name[:34]:34s} pub={len(pub):4d} now={len(now):4d} "
                  f"+{len(added)} -{len(dropped)} ~{len(moved)}  "
                  f"cache={mcplib.STATS['cache_hit']} net={mcplib.STATS['net']}", flush=True)
    json.dump({"trees": s, "edge_stats": dict(TAGSTATS)}, open(STATE, "w"))
    ok = sum(1 for v in s.values() if "skip" not in v)
    print(f"\nmeasured {ok} of {len(s)} attempted")


def pct(x, n):
    return f"{100*x/n:.1f}%" if n else "n/a"


def report():
    raw = json.load(open(STATE))
    s = {k: v for k, v in raw["trees"].items() if "skip" not in v and not v["truncated"]}
    n = len(s)
    print(f"=== install gap, {n} MCP server trees "
          f"({len(raw['trees'])-n} skipped: unresolvable root or cap-truncated)\n")

    changed = [v for v in s.values() if v["n_added"] or v["n_dropped"] or v["n_moved"]]
    print(f"trees where the installed tree differs from the published graph: "
          f"{len(changed)}/{n} = {pct(len(changed), n)}")

    npub = [v["n_published"] for v in s.values()]
    nnow = [v["n_installed"] for v in s.values()]
    print(f"  median packages, published graph : {statistics.median(npub):.0f}")
    print(f"  median packages, installed today : {statistics.median(nnow):.0f}")
    tot_pub, tot_now = sum(npub), sum(nnow)
    print(f"  total instances {tot_pub} -> {tot_now} = "
          f"{100*(tot_now-tot_pub)/tot_pub:+.1f}%")

    for key, label in (("n_added", "added   (install pulls in, published graph has no node)"),
                       ("n_dropped", "dropped (published graph has, install does not)"),
                       ("n_moved", "moved   (same package, different version)")):
        vals = [v[key] for v in s.values()]
        hit = sum(1 for x in vals if x)
        print(f"\n  {label}")
        print(f"    trees affected: {hit}/{n} = {pct(hit, n)}   "
              f"median among affected: {statistics.median([x for x in vals if x]) if hit else 0:.0f}   "
              f"total: {sum(vals)}")

    # how much of a typical installed tree is invisible to a published-graph answer
    fr = [(v["n_added"] + v["n_moved"]) / v["n_installed"] for v in s.values() if v["n_installed"]]
    fr.sort()
    print(f"\n  share of the installed tree a published-graph answer gets wrong "
          f"(added or moved):")
    print(f"    median {100*statistics.median(fr):.1f}%   p90 {100*fr[int(.9*len(fr))]:.1f}%   "
          f"max {100*fr[-1]:.1f}%")

    print(f"\n=== platform / optional mass (present on some machines, absent on others)")
    oo = [v["optional_only_installed"] for v in s.values()]
    pc = [v["platform_constrained"] for v in s.values()]
    print(f"  trees with any optional-only package: {sum(1 for x in oo if x)}/{n} = "
          f"{pct(sum(1 for x in oo if x), n)}")
    print(f"  optional-only packages, total {sum(oo)}, median among affected "
          f"{statistics.median([x for x in oo if x]) if any(oo) else 0:.0f}")
    print(f"  of those, declaring an os/cpu constraint: {sum(pc)}")

    es = raw.get("edge_stats", {})
    tot_e = es.get("range_edges", 0) + es.get("tag_edges", 0)
    print(f"\n=== edge resolution (approximation visibility)")
    print(f"  range edges (exact under cutoff)  : {es.get('range_edges', 0)} = "
          f"{pct(es.get('range_edges', 0), tot_e)}")
    print(f"  dist-tag edges (approximated)     : {es.get('tag_edges', 0)} = "
          f"{pct(es.get('tag_edges', 0), tot_e)}")

    top = collections.Counter()
    for v in s.values():
        top.update(v["added"])
    print(f"\n=== packages most often acquired after publication")
    for pkgname, c in top.most_common(12):
        print(f"    {c:4d} trees  {pkgname}")

    out = {
        "trees_measured": n,
        "trees_differing": len(changed),
        "trees_differing_pct": round(100 * len(changed) / n, 1) if n else None,
        "median_nodes_published": statistics.median(npub),
        "median_nodes_installed": statistics.median(nnow),
        "total_instance_delta_pct": round(100 * (tot_now - tot_pub) / tot_pub, 1),
        "added_trees": sum(1 for v in s.values() if v["n_added"]),
        "dropped_trees": sum(1 for v in s.values() if v["n_dropped"]),
        "moved_trees": sum(1 for v in s.values() if v["n_moved"]),
        "added_total": sum(v["n_added"] for v in s.values()),
        "dropped_total": sum(v["n_dropped"] for v in s.values()),
        "moved_total": sum(v["n_moved"] for v in s.values()),
        "wrong_share_median_pct": round(100 * statistics.median(fr), 1),
        "wrong_share_p90_pct": round(100 * fr[int(.9 * len(fr))], 1),
        "optional_only_total": sum(oo),
        "platform_constrained_total": sum(pc),
        "edge_stats": es,
        "top_added": top.most_common(25),
        "limits": ["dist-tag edges cannot be time-travelled; approximated by highest "
                   "non-prerelease version at or before cutoff, counted above",
                   "cap-truncated trees excluded from all statistics",
                   "optional edges included without evaluating os/cpu, so the installed "
                   "arm is an upper bound for any single machine",
                   "none of the 250 source configurations pins a version, so there is no "
                   "lockfile state to model"],
    }
    json.dump(out, open(os.path.join(HERE, "install_gap.json"), "w"), indent=1)
    print("\nwrote install_gap.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    run(float(sys.argv[2]) if len(sys.argv) > 2 else 480) if m == "run" else report()
