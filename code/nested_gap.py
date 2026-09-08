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
import collections, json, os, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import install_gap as IG
import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/nested_gap.json"
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
            now, tn = pair_walk(name, ver, None)
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
    adv = json.load(open("/tmp/mcpres/advisories.json"))
    import nodesemver as sv

    def vids(name, ver):
        o = []
        for a in adv.get(name) or []:
            r = a.get("vulnerable_versions")
            if not r:
                continue
            try:
                if sv.satisfies(ver, r, loose=True):
                    o.append((a.get("id"), a.get("severity")))
            except Exception:
                pass
        return o

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
        for nm, a in missed:
            mt[nm] += 1
            for r in adv.get(nm, []):
                if r.get("id") == a:
                    msev[r.get("severity")] += 1
        for nm, a in phantom:
            for r in adv.get(nm, []):
                if r.get("id") == a:
                    psev[r.get("severity")] += 1

    print(f"\n=== advisory verdict, frozen vs live, pair-keyed")
    print(f"  trees with a real finding when installed: {live_any} = {100*live_any/n:.1f}%")
    print(f"  verdict differs: {differ} = {100*differ/n:.1f}%")
    print(f"  MISSED  {m_tr} trees, {sum(msev.values())} findings, "
          + ", ".join(f"{k} {msev.get(k,0)}" for k in SEV))
    print(f"  PHANTOM {p_tr} trees, {sum(psev.values())} findings, "
          + ", ".join(f"{k} {psev.get(k,0)}" for k in SEV))
    print(f"  top missed: {mt.most_common(6)}")

    json.dump({"trees": n, "dup_trees": dup_trees, "dup_packages_total": dup_tot,
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
              open(os.path.join(HERE, "nested_gap.json"), "w"), indent=1)
    print("\nwrote nested_gap.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    run(float(sys.argv[2]) if len(sys.argv) > 2 else 480) if m == "run" else report()
