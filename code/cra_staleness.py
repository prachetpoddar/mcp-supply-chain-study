#!/usr/bin/env python3
"""
Unmaintained components in resolved dependency trees: rows 1 to 3 of
PREREGISTRATION-2.md, plus the deprecation discriminator added after them.

WHY THIS FILE EXISTS AT ALL
    The first pass computed these rows in an ad-hoc shell session. Nothing that
    produced a published number existed as a reviewable artifact, and that is
    precisely how the error below survived to be reported.

WHAT THE FIRST PASS GOT WRONG, AND WHAT IS DIFFERENT HERE

    1. ADVISORY MATCHING WAS NAME-LEVEL. The pre-registration defines an
       unfixed advisory as one "affecting the installed version". The first pass
       matched on package name, so any advisory anywhere in a package's history
       counted. That put `colors` in the numerator on an advisory affecting
       >=1.4.1 while 1.0.3 is installed, and `rc` on three enumerated compromised
       builds none of which is the installed 1.2.8. `rc` alone supplied 15 of the
       17 trees reported. Matching here evaluates the installed version against
       each advisory's ranges and enumerated versions.

    2. DEPTH FANNED OUT TO EVERY VERSION OF A DEPENDENCY NAME. A tree can hold
       one name at two versions; the traversal added an edge to both regardless
       of the declared range, and since depth is a shortest path that can only
       shrink it. Edges are now resolved against the range. Measured effect: 868
       node instances were shallower than the truth, by up to 3 edges, and no
       conclusion moves.

    3. THE CLOCK WAS NOT RECORDED. Ages came from wall-clock at build time and
       the timestamp was never written to the output, so the figures could not be
       reproduced. `as_of` is now stamped into the result and can be overridden.

    4. THE DISCRIMINATOR WAS ALREADY IN THE CACHE. Row 2 asks how to tell
       abandoned from finished. It used an OSV proxy that yields two packages
       under its own definition, while npm's own per-version `deprecated` flag
       sat unread in the same file. A package whose every published version is
       deprecated is not a proxy for abandonment; it is the publisher saying so.
       That row was added AFTER rows 1 to 3 had been seen, which is recorded here
       and in the pre-registration rather than presented as though planned.

    5. ROW 3 REPORTED ONLY THE MEDIAN. The pre-registration asks for the
       distribution too. The median cannot move on this corpus: 59% of nodes sit
       at depth 2 or 3. The distribution is reported, and so is a name-level cut
       that clears the pre-registered bar and was NOT adopted, because the
       pre-registration fixes the unit as the node instance.

    python3 cra_staleness.py [--as-of YYYY-MM-DDTHH:MM:SSZ]
"""
import collections, datetime as dt, json, os, statistics, sys
import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
TREES = "/tmp/mcpres/nested_gap.json"
PACK = "/tmp/mcpres/component_packuments_full.json"
OSV = "/mnt/user-data/uploads/MCPSupplyChainStudy/data/osv_latency_state.json"
OUT = os.path.join(HERE, "cra_staleness.json")
TH = (180, 365, 730)


def split(e):
    i = e.rfind("@@")
    return e[:i], e[i + 2:]


def load():
    s = json.load(open(TREES))
    trees = {}
    for name, v in s.items():
        # `installed`, not `published`: the question is what an install
        # materialises today. The two differ in 175 of 250 trees.
        arr = v.get("installed") or []
        if arr:
            trees[name] = ((name, v.get("root_version")), [split(e) for e in arr])
    return trees, json.load(open(PACK)), json.load(open(OSV))


def satisfies(ver, rng):
    try:
        return sv.satisfies(ver, (rng or "*").strip(), loose=True)
    except Exception:
        return False


def depth_map(rootpair, rows, pk):
    """Shortest edge distance from the root, edges resolved against the range."""
    byname = collections.defaultdict(set)
    for n, v in rows:
        byname[n].add(v)
    have = {(n, v) for n, v in rows}
    if rootpair not in have:
        return {}, len(have), 0
    d = {rootpair: 0}
    q = collections.deque([rootpair])
    dangling = 0
    while q:
        cur = q.popleft()
        n, v = cur
        meta = ((pk.get(n) or {}).get("deps") or {}).get(v) or {}
        for grp in ("d", "o", "p"):
            for dn, rng in (meta.get(grp) or {}).items():
                cands = byname.get(dn)
                if not cands:
                    dangling += 1
                    continue
                # only versions the declared range actually admits
                sat = [c for c in cands if satisfies(c, rng)]
                if not sat:
                    dangling += 1          # name present, no version admitted
                    sat = []
                for dv in sat:
                    if (dn, dv) not in d:
                        d[(dn, dv)] = d[cur] + 1
                        q.append((dn, dv))
    return d, len(have) - len(d), dangling


def advisory_hits(pk_names, osv, installed):
    """name -> (affects_installed, unfixed) under the pre-registered definition."""
    aff, unf = set(), set()
    for n, vers in installed.items():
        recs = osv.get(n)
        if not isinstance(recs, list):
            continue
        for rec in recs:
            mine = [a for a in (rec.get("affected") or [])
                    if (a.get("package") or {}).get("name") == n]
            if not mine:
                continue
            hit = False
            for a in mine:
                enum = set(a.get("versions") or [])
                if vers & enum:
                    hit = True
                    break
                for r in (a.get("ranges") or []):
                    if r.get("type") not in ("SEMVER", "ECOSYSTEM"):
                        continue
                    intro = fixed = last = None
                    for ev in r.get("events") or []:
                        intro = ev.get("introduced", intro)
                        fixed = ev.get("fixed", fixed)
                        last = ev.get("last_affected", last)
                    for ver in vers:
                        try:
                            if intro not in (None, "0") and sv.lt(ver, intro, loose=True):
                                continue
                            if fixed and not sv.lt(ver, fixed, loose=True):
                                continue
                            if last and sv.gt(ver, last, loose=True):
                                continue
                        except Exception:
                            continue
                        hit = True
                        break
                    if hit:
                        break
            if not hit:
                continue
            aff.add(n)
            has_fix = any(ev.get("fixed") for a in mine
                          for r in (a.get("ranges") or [])
                          for ev in (r.get("events") or []))
            if not has_fix:
                unf.add(n)
    return aff, unf


def main():
    as_of = None
    if "--as-of" in sys.argv:
        as_of = sys.argv[sys.argv.index("--as-of") + 1]
    now = (dt.datetime.fromisoformat(as_of.replace("Z", "+00:00")) if as_of
           else dt.datetime.now(dt.timezone.utc))
    trees, pk, osv = load()

    age, no_date = {}, []
    for n, v in pk.items():
        t = v.get("latest_release")
        if not t:
            no_date.append(n)
            continue
        age[n] = (now - dt.datetime.fromisoformat(t.replace("Z", "+00:00"))).days

    nodes, unreach, dangling = [], 0, 0
    installed = collections.defaultdict(set)
    for root, (rootpair, rows) in trees.items():
        dm, un, dg = depth_map(rootpair, rows, pk)
        unreach += un
        dangling += dg
        for (n, v) in rows:
            installed[n].add(v)
            nodes.append({"tree": root, "name": n, "version": v,
                          "depth": dm.get((n, v)), "age": age.get(n)})

    names = set(installed)
    ing = collections.Counter(r["name"] for r in nodes)
    fully_dep = {n for n in names
                 if (pk.get(n, {}).get("deprecated")
                     and set(pk[n]["deps"]) == set(pk[n]["deprecated"]))}
    aff, unf = advisory_hits(names, osv, installed)

    res = {"as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "trees": len(trees), "node_instances": len(nodes),
           "distinct_names": len(names),
           "names_without_release_date": len(no_date),
           "nodes_unreachable_from_root": unreach,
           "dangling_edges": dangling,
           "thresholds_days": list(TH), "rows": {}}

    def q(v, p):
        v = sorted(v)
        return v[min(len(v) - 1, int(p * len(v)))]

    for t in TH:
        stale = {n for n in names if age.get(n, 0) > t}
        fresh = names - stale
        si = [r for r in nodes if r["name"] in stale]
        sd = [r["depth"] for r in si if r["depth"] is not None]
        fd = [r["depth"] for r in nodes if r["name"] in fresh and r["depth"] is not None]
        # name-level sensitivity, computed and NOT adopted (unit is the node)
        nm = collections.defaultdict(list)
        for r in nodes:
            if r["depth"] is not None:
                nm[r["name"]].append(r["depth"])
        nsd = [statistics.mean(v) for n, v in nm.items() if n in stale]
        nfd = [statistics.mean(v) for n, v in nm.items() if n in fresh]
        res["rows"][t] = {
            "row1_stale_names": [len(stale), round(100 * len(stale) / len(names), 1)],
            "row1_stale_node_instances": [len(si), round(100 * len(si) / len(nodes), 1)],
            "row1_trees_with_stale": len({r["tree"] for r in si}),
            "row1_median_ingestion_stale": statistics.median([ing[n] for n in stale]),
            "row1_median_ingestion_fresh": statistics.median([ing[n] for n in fresh]),
            "row2_fully_deprecated_stale": len(stale & fully_dep),
            "row2_advisory_affecting_installed_stale": len(stale & aff),
            "row2_unfixed_stale": len(stale & unf),
            "row2_unfixed_fresh": len(fresh & unf),
            "row3_median_depth_stale": statistics.median(sd),
            "row3_median_depth_fresh": statistics.median(fd),
            "row3_p90_depth_stale": q(sd, .9), "row3_p90_depth_fresh": q(fd, .9),
            "row3_share_depth_ge5_stale": round(100 * sum(1 for x in sd if x >= 5) / len(sd), 1),
            "row3_share_depth_ge5_fresh": round(100 * sum(1 for x in fd if x >= 5) / len(fd), 1),
            "row3_NOT_ADOPTED_name_level_median_diff":
                round(statistics.median(nsd) - statistics.median(nfd), 2),
        }
    res["deprecation"] = {
        "fully_deprecated_names": len(fully_dep),
        "node_instances": sum(ing[n] for n in fully_dep),
        "trees_touched": len({r["tree"] for r in nodes if r["name"] in fully_dep}),
        "most_ingested": [[n, ing[n]] for n in sorted(fully_dep, key=lambda x: -ing[x])[:8]],
    }
    res["advisories"] = {"names_with_advisory_affecting_installed": len(aff),
                         "names_unfixed": sorted(unf)}
    json.dump(res, open(OUT, "w"), indent=1)

    print(f"as of {res['as_of']}   {res['trees']} trees, {res['node_instances']} nodes, "
          f"{res['distinct_names']} names")
    print(f"unreachable {unreach}, dangling edges {dangling}, names without a date {len(no_date)}\n")
    print(f"{'thr':>5} {'stale names':>16} {'stale nodes':>16} {'trees':>7} "
          f"{'med ingest s/f':>15} {'dep&stale':>10} {'unfix s/f':>10} "
          f"{'med depth s/f':>14} {'>=5 depth s/f':>14}")
    for t in TH:
        r = res["rows"][t]
        print(f"{t:>4}d {r['row1_stale_names'][0]:>6} ={r['row1_stale_names'][1]:>5.1f}% "
              f"{r['row1_stale_node_instances'][0]:>7} ={r['row1_stale_node_instances'][1]:>5.1f}% "
              f"{r['row1_trees_with_stale']:>7} "
              f"{r['row1_median_ingestion_stale']:>7.0f}/{r['row1_median_ingestion_fresh']:<7.0f} "
              f"{r['row2_fully_deprecated_stale']:>10} "
              f"{r['row2_unfixed_stale']:>4}/{r['row2_unfixed_fresh']:<5} "
              f"{r['row3_median_depth_stale']:>6.1f}/{r['row3_median_depth_fresh']:<7.1f} "
              f"{r['row3_share_depth_ge5_stale']:>6.1f}/{r['row3_share_depth_ge5_fresh']:<7.1f}")
    d = res["deprecation"]
    print(f"\ndeprecation: {d['fully_deprecated_names']} names every version deprecated, "
          f"{d['node_instances']} instances, {d['trees_touched']} of {res['trees']} trees "
          f"({100*d['trees_touched']/res['trees']:.1f}%)")
    print("  most ingested:", d["most_ingested"][:6])
    print(f"advisories affecting an installed version: {res['advisories']['names_with_advisory_affecting_installed']} names; "
          f"unfixed: {res['advisories']['names_unfixed']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
