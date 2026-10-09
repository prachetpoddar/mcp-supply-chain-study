#!/usr/bin/env python3
"""
Re-measure the declared/materialized gap without flattening the install tree.

WHY THE FLAT MAP HAD TO GO
    install_gap.py and vuln_gap.py key every tree on package NAME, one version
    each. npm does not: when two parents demand incompatible ranges it installs
    both copies, nested. Flattening forces an arbitrary pick, and the pick is
    decided by traversal order. That made the deps.dev comparison unidentified,
    spanning 0.4% to 5.2% verdict difference across two legitimate flattenings
    of the same corpus.

THE FORMULATION THAT AVOIDS IT
    npm's placement algorithm decides WHERE a package lands on disk (hoist to
    the top when unambiguous, nest when not). It does not decide WHICH
    (name, version) pairs get installed. For an advisory question only the set
    matters, so this walks the edge closure and memoises on (name, version)
    rather than on name. Duplicates appear as distinct nodes; hoisting is never
    modelled because it cannot change the set.

    This is exact with respect to the question asked, not an approximation of
    npm's tree layout. It does not reproduce node_modules paths and is not
    meant to.

    Remaining approximations, unchanged from install_gap:
      - dist-tag edges cannot be time-travelled (12 of 63,258 edges)
      - optional edges are included without evaluating os/cpu, an upper bound
        for any single machine
      - cycles terminate via the (name, version) memo, matching npm's own
        dedupe of an already-satisfied identical resolution

    python3 nested_gap.py run [seconds]
    python3 nested_gap.py report
"""
import collections, datetime as dt, hashlib, json, os, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import install_gap as IG
import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("NESTED_STATE") or os.path.join(
    os.path.dirname(HERE), "data", "nested_gap_state.json")
ADVISORIES = os.environ.get("ADVISORIES") or os.path.join(
    os.path.dirname(HERE), "data", "advisories_npm.json")
# Results belong in data/ with everything else the release ships. This file used
# to write beside the code, which is why the figure it produced was not in the
# released data directory.
OUT = os.environ.get("NESTED_OUT") or os.path.join(
    os.path.dirname(HERE), "data", "nested_gap.json")
# The repository is organised into code/ and data/; this file lives in data/.
# The flat-layout path is kept as a fallback so an older checkout still runs.
TREES = os.path.join(os.path.dirname(HERE), "data", "resolved_trees_for_depsdev.json")
if not os.path.exists(TREES):
    TREES = os.path.join(HERE, "resolved_trees_for_depsdev.json")
CAP = 6000


def pair_walk(root, rv, cutoff, cap=CAP):
    """Edge closure keyed on (name, version), with npm's reuse rule.

    DEDUPE, added after ground-truth checking. npm does not resolve every edge
    independently: when a package is already placed at a version that satisfies
    a new range, npm reuses it and nests a second copy only on genuine conflict.
    Resolving each edge in isolation produces duplicates npm never installs, and
    those extra nodes carry extra advisories, so the tree over-reports.

    Measured case: @modelcontextprotocol/sdk peers zod at `^3.25 || ^4.0` and
    zod-to-json-schema peers it at `^3.25.28 || ^4`. One version satisfies both,
    npm installs one, edge-independent resolution installed two.

    Reuse is checked in BFS order, which is the order npm hoists in.
    """
    nodes, seen = set(), set()
    placed = collections.defaultdict(set)      # name -> versions already in tree
    q = collections.deque([(root, rv, "root")])
    opt_only, plat = set(), set()
    while q:
        if len(nodes) >= cap:
            return nodes, True
        name, spec, kind = q.popleft()
        if mcplib.classify_spec(spec) != "registry":
            continue
        # npm reuse: an already-placed version that satisfies this range wins
        reuse = None
        if placed.get(name) and mcplib.classify_spec(spec) == "registry":
            for cand in placed[name]:
                try:
                    ok = sv.satisfies(cand, (spec or "").strip(), loose=True)
                except (ValueError, TypeError, AttributeError):
                    ok = False          # unparseable range, not a programming error
                if ok:
                    reuse = cand
                    break
        if reuse is not None:
            continue
        try:
            v, meta = IG.resolve_at(name, spec, cutoff)
        except Exception:
            continue
        if v is None:
            continue
        key = (name, v)
        if key in nodes:
            continue
        placed[name].add(v)
        nodes.add(key)
        if kind == "optional":
            opt_only.add(key)
            if meta.get("os") or meta.get("cpu"):
                plat.add(key)
        # npm 7+ installs non-optional peerDependencies automatically. Omitting
        # them was measured against a real `npm install`: research-swarm
        # declares `agentic-flow` as a peer and the peer-free walk missed 392
        # of its 619 packages. Peers marked optional in peerDependenciesMeta
        # are NOT auto-installed and are excluded here.
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
                q.append((dn, dr, gk if kind != "optional" else "optional"))
    return nodes, False


def run(budget):
    trees = json.load(open(TREES))
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [t for t in trees if t["root_name"] not in s]
    print(f"{len(todo)} roots to walk of {len(trees)}")
    t0 = time.time()
    for i, t in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        name, ver = t["root_name"], t["root_version"]
        try:
            cut = (mcplib.npm_packument(name).get("time") or {}).get(ver)
            if not cut:
                s[name] = {"skip": "no publish time"}
                continue
            pub, tp = pair_walk(name, ver, cut)
            # LIVE_CUTOFF time-aligns the live arm with the advisory snapshot.
            # Resolving the live arm against today's registry while joining to a
            # month-old advisory export hides any advisory published since the
            # export, which biases the comparison toward phantom findings. Set
            # it to the export date to measure how much that costs.
            now, tn = pair_walk(name, ver, os.environ.get("LIVE_CUTOFF") or None)
        except Exception as e:
            s[name] = {"skip": repr(e)[:120]}
            continue
        s[name] = {"root_version": ver, "root_published": cut,
                   "published": sorted(f"{a}@@{b}" for a, b in pub),
                   "installed": sorted(f"{a}@@{b}" for a, b in now),
                   "truncated": bool(tp or tn)}
        if i % 20 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)} {name[:32]:32s} pub={len(pub):4d} now={len(now):4d} "
                  f"net={mcplib.STATS['net']}", flush=True)
    json.dump(s, open(STATE, "w"))
    print(f"\nwalked {sum(1 for v in s.values() if 'skip' not in v)} of {len(s)}")


def split(x):
    n, _, v = x.rpartition("@@")
    return n, v


def report():
    raw = json.load(open(STATE))
    s = {k: v for k, v in raw.items() if "skip" not in v and not v["truncated"]}
    n = len(s)
    adv = json.load(open(ADVISORIES))
    import nodesemver as sv

    def vids(name, ver):
        o = []
        for a in adv.get(name) or []:
            r = a.get("vulnerable_versions")
            if not r:
                continue
            try:
                if sv.satisfies(ver, r, loose=True, include_prerelease=True):
                    o.append((a.get("id"), a.get("severity")))
            except Exception:
                pass
        return o

    # severity per (package, advisory), first row wins; built once
    SEV_OF = {}
    for _nm, _rows in adv.items():
        for _r in _rows:
            SEV_OF.setdefault((_nm, _r.get("id")), _r.get("severity"))
    pf_phantom, pf_missed = collections.Counter(), collections.Counter()
    cross = collections.Counter()
    both_differ = both_same = single_node = pair_ph = pair_ms = 0
    age_rows = []
    snap = None
    try:
        snap = json.load(open(os.path.join(os.path.dirname(HERE), "data",
                                           "advisories_npm_meta.json")))
    except Exception:
        pass
    snap_at = (snap or {}).get("source_mtime_utc")

    dup_trees, dup_tot = 0, 0
    for v in s.values():
        c = collections.Counter(split(x)[0] for x in v["installed"])
        d = sum(1 for k, m in c.items() if m > 1)
        if d:
            dup_trees += 1
            dup_tot += d
    print(f"=== pair-keyed install sets, {n} trees "
          f"({len(raw)-n} skipped: no publish time or cap-truncated)\n")
    print(f"  trees containing a duplicated package: {dup_trees} = {100*dup_trees/n:.1f}%")
    print(f"  duplicated packages, total: {dup_tot}")
    npub = [len(v["published"]) for v in s.values()]
    nnow = [len(v["installed"]) for v in s.values()]
    print(f"  median nodes: published {statistics.median(npub):.0f}, "
          f"installed {statistics.median(nnow):.0f}")
    print(f"  total instances {sum(npub)} -> {sum(nnow)} = "
          f"{100*(sum(nnow)-sum(npub))/sum(npub):+.1f}%")

    moved = sum(1 for v in s.values()
                if {split(x)[0] for x in v["published"]} & {split(x)[0] for x in v["installed"]}
                and set(v["published"]) != set(v["installed"]))
    print(f"  trees whose install set differs: {moved} = {100*moved/n:.1f}%")

    SEV = ["critical", "high", "moderate", "low"]
    msev, psev = collections.Counter(), collections.Counter()
    m_tr = p_tr = differ = live_any = 0
    mt = collections.Counter()
    for v in s.values():
        p = {(split(x)[0], a) for x in v["published"] for a, _ in vids(*split(x))}
        q = {(split(x)[0], a) for x in v["installed"] for a, _ in vids(*split(x))}
        missed, phantom = q - p, p - q
        if q:
            live_any += 1
        if missed or phantom:
            differ += 1
        if missed:
            m_tr += 1
        if phantom:
            p_tr += 1
        cross[(bool(p), bool(q))] += 1
        if p and q:
            both_differ += (p != q)
            both_same += (p == q)
        if len(v["published"]) == 1 and len(v["installed"]) == 1:
            single_node += 1
        pair_ph += len({nm for nm, _ in phantom})
        pair_ms += len({nm for nm, _ in missed})
        if snap_at and v.get("root_published"):
            try:
                d = (dt.datetime.fromisoformat(snap_at.replace("Z", "+00:00"))
                     - dt.datetime.fromisoformat(
                         v["root_published"].replace("Z", "+00:00"))).days
                age_rows.append((d, len(phantom)))
            except Exception:
                pass
        # One finding per (package, advisory), counted once. The earlier version
        # incremented per matching advisory ROW, and OSV emits one row per
        # package-and-range group, so an advisory covering two version ranges of
        # the same package was counted twice. The tree-level rate above comes
        # from set differences and was never affected; the finding counts were,
        # and the figures this file published before today carry that inflation.
        for nm, a in missed:
            mt[nm] += 1
            msev[SEV_OF.get((nm, a))] += 1
            pf_missed[nm] += 1
        for nm, a in phantom:
            psev[SEV_OF.get((nm, a))] += 1
            pf_phantom[nm] += 1

    print(f"\n=== advisory verdict, frozen vs live, pair-keyed")
    print(f"  trees with a real finding when installed: {live_any} = {100*live_any/n:.1f}%")
    print(f"  verdict differs: {differ} = {100*differ/n:.1f}%")
    print(f"  MISSED  {m_tr} trees, {sum(msev.values())} findings, "
          + ", ".join(f"{k} {msev.get(k,0)}" for k in SEV))
    print(f"  PHANTOM {p_tr} trees, {sum(psev.values())} findings, "
          + ", ".join(f"{k} {psev.get(k,0)}" for k in SEV))
    print(f"  top missed: {mt.most_common(6)}")
    print(f"\n=== the crosstab, which is what a scanner's answer actually does")
    print(f"  frozen flags, live clean : {cross[(True, False)]} = "
          f"{100*cross[(True, False)]/n:.1f}%   <- the wrong-answer rate")
    print(f"  live flags, frozen clean : {cross[(False, True)]}")
    print(f"  both flag                : {cross[(True, True)]} "
          f"(advisory lists differ in {both_differ}, identical in {both_same})")
    print(f"  neither flags            : {cross[(False, False)]}")
    print(f"  trees with no dependencies at all: {single_node} of {n}; the rate among "
          f"trees with any dependency is {100*differ/max(n-single_node,1):.1f}%")
    print(f"  (tree, package) pairs: {pair_ph} phantom, {pair_ms} missed. One package "
          f"with many advisories yields many findings from one version move.")
    if age_rows:
        print("  by root age at the advisory snapshot:")
        for lo, hi, lbl in ((0, 30, "<=30d"), (31, 90, "31-90d"), (91, 180, "91-180d"),
                            (181, 365, "181-365d"), (366, 10**6, ">365d")):
            g = [c for d, c in age_rows if lo <= d <= hi]
            if g:
                gs = sorted(g)
                print(f"    {lbl:>9}: {len(g):3d} trees, "
                      f"{sum(1 for c in g if c):3d} with phantom "
                      f"({100*sum(1 for c in g if c)/len(g):.0f}%), "
                      f"median {gs[len(gs)//2]} findings")
    tot_ph = sum(pf_phantom.values())
    if tot_ph:
        top5 = sum(c for _, c in pf_phantom.most_common(5))
        print(f"  phantom findings concentrate: {len(pf_phantom)} packages carry them, "
              f"top five hold {100*top5/tot_ph:.0f}%")
        print(f"  top phantom packages: {pf_phantom.most_common(6)}")

    json.dump({"counting_unit": "one finding per (package, advisory id) per tree",
               "crosstab": {"frozen_flags_live_clean": cross[(True, False)],
                            "live_flags_frozen_clean": cross[(False, True)],
                            "both_flag": cross[(True, True)],
                            "both_flag_lists_differ": both_differ,
                            "both_flag_lists_identical": both_same,
                            "neither_flags": cross[(False, False)]},
               "wrong_answer_rate_pct": round(100*cross[(True, False)]/n, 1),
               "trees_without_dependencies": single_node,
               "rate_among_trees_with_dependencies_pct":
                   round(100*differ/max(n-single_node, 1), 1),
               "phantom_pairs_tree_package": pair_ph,
               "missed_pairs_tree_package": pair_ms,
               "phantom_by_root_age": [[d, c] for d, c in sorted(age_rows)],
               "live_cutoff": os.environ.get("LIVE_CUTOFF") or None,
               "advisory_snapshot": {
                   "file": os.path.basename(ADVISORIES),
                   "sha256": hashlib.sha256(open(ADVISORIES, "rb").read()).hexdigest(),
                   "source_mtime_utc": snap_at,
                   "basis": (snap or {}).get("basis")},
               "state_file": os.path.basename(STATE),
               "prerelease_join": "include_prerelease=True",
               "advisory_basis": os.path.basename(ADVISORIES),
               "phantom_by_package": dict(pf_phantom.most_common(20)),
               "phantom_packages": len(pf_phantom),
               "missed_by_package": dict(pf_missed.most_common(20)),
               "trees": n, "dup_trees": dup_trees, "dup_packages_total": dup_tot,
               "median_published": statistics.median(npub),
               "median_installed": statistics.median(nnow),
               "total_instance_delta_pct": round(100*(sum(nnow)-sum(npub))/sum(npub), 1),
               "trees_install_set_differs": moved,
               "trees_with_live_findings": live_any,
               "verdict_differs": differ,
               "missed_trees": m_tr, "missed_findings": sum(msev.values()),
               "missed_by_severity": dict(msev),
               "phantom_trees": p_tr, "phantom_findings": sum(psev.values()),
               "phantom_by_severity": dict(psev),
               "top_missed": mt.most_common(20)},
              open(OUT, "w"), indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    run(float(sys.argv[2]) if len(sys.argv) > 2 else 480) if m == "run" else report()
