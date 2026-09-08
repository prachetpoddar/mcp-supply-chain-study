#!/usr/bin/env python3
"""
Does the published-graph / installed-tree gap change the VULNERABILITY answer?

WHY THIS EXISTS
    install_gap.py shows the two graphs contain nearly the same packages
    (+1.3% instances) but frequently at different versions (69.2% of trees,
    median 16 packages moved). Node counts are therefore a bad way to judge
    whether the gap matters. Advisories are keyed on version ranges, so a
    scanner that resolves a package's transitive graph from a published-graph
    service and queries an advisory database across the flattened set is asking
    about versions that may not be the ones on disk.

    This measures the consequence directly: for each of the 250 MCP server
    trees, the advisory verdict computed from the published graph versus the
    verdict computed from the versions an install materializes today.

    The two error directions are reported separately and are not symmetric:

      MISSED     vulnerable at the installed version, not vulnerable at the
                 published-graph version. The scanner reports clean and the
                 machine is not. This is the direction that matters.
      PHANTOM    vulnerable at the published-graph version, not at the
                 installed version. The scanner reports a finding the machine
                 does not have.

WHAT THE "PUBLISHED GRAPH" ARM IS, PRECISELY
    It is the tree obtained by freezing every range at the root version's own
    publish date. That models a lockfile committed at release, or an SBOM
    generated at release and scanned later -- which is the artifact the EU CRA
    regime asks vendors to produce and ship.

    It is NOT a model of a graph service such as deps.dev, which resolves
    ranges at ITS crawl time, only days or weeks stale rather than the full age
    of the root. Publish-time freezing is therefore the WORST CASE for the
    staleness component of that gap: these numbers bound it, they do not
    estimate it. Measuring the crawl-lag component specifically requires
    querying the service itself.

SOURCE
    registry.npmjs.org/-/npm/v1/security/advisories/bulk -- the endpoint
    `npm audit` itself uses, carrying GitHub Advisory Database records with
    explicit `vulnerable_versions` ranges. Chosen over a third-party graph
    service deliberately: the point of the measurement is that the registry is
    the ground truth for what installs, so the advisory source should be the
    registry's own too.

LIMITS, STATED
    Advisory data is read TODAY for both arms. This isolates the version delta
    as the only moving part; it does not model advisories published after a
    root shipped, which is a separate and additive effect.
    Trees truncated at the walk cap are excluded.
    The installed arm includes optional dependencies without evaluating os/cpu,
    so it is an upper bound for any one machine.

    python3 vuln_gap.py fetch [seconds]
    python3 vuln_gap.py report
"""
import collections, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
GAP = "/tmp/mcpres/install_gap.json"
ADV = "/tmp/mcpres/advisories.json"
BULK = "https://registry.npmjs.org/-/npm/v1/security/advisories/bulk"
UA = {"Content-Type": "application/json",
      "User-Agent": "npm/10.0.0 mcp-supply-chain-study/0.4 (academic research)"}
BATCH = 150


def load_gap():
    raw = json.load(open(GAP))
    return {k: v for k, v in raw["trees"].items()
            if "skip" not in v and not v["truncated"]}


def fetch(budget):
    trees = load_gap()
    want = collections.defaultdict(set)
    for v in trees.values():
        for m in ("published_versions", "installed_versions"):
            for name, ver in v[m].items():
                want[name].add(ver)
    adv = json.load(open(ADV)) if os.path.exists(ADV) else {}
    todo = sorted(n for n in want if n not in adv)
    print(f"{len(want)} distinct packages, {len(todo)} not yet queried")
    t0 = time.time()
    for i in range(0, len(todo), BATCH):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        chunk = todo[i:i + BATCH]
        body = json.dumps({n: sorted(want[n]) for n in chunk}).encode()
        for a in range(5):
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(BULK, data=body, headers=UA), timeout=60) as r:
                    d = json.load(r)
                break
            except Exception:
                if a == 4:
                    d = None
                time.sleep(2 ** a)
        if d is None:
            print(f"  chunk {i} failed, skipping")
            continue
        for n in chunk:
            adv[n] = d.get(n, [])
        json.dump(adv, open(ADV, "w"))
        hits = sum(1 for n in chunk if adv[n])
        print(f"  {i+len(chunk)}/{len(todo)}  packages with advisories in this chunk: {hits}",
              flush=True)
        time.sleep(0.5)
    json.dump(adv, open(ADV, "w"))
    print(f"\nadvisory records held for {len(adv)} packages, "
          f"{sum(1 for v in adv.values() if v)} of which have at least one")


def vulnerable(adv, name, ver):
    """Advisories from `adv` whose vulnerable_versions range contains `ver`."""
    out = []
    for a in adv.get(name) or []:
        rng = a.get("vulnerable_versions")
        if not rng:
            continue
        try:
            if sv.satisfies(ver, rng, loose=True):
                out.append((a.get("id") or a.get("title"), a.get("severity")))
        except Exception:
            continue
    return out


SEV = ["critical", "high", "moderate", "low"]


def report():
    trees, adv = load_gap(), json.load(open(ADV))
    n = len(trees)
    rows, missed_sev, phantom_sev = [], collections.Counter(), collections.Counter()
    missed_pkg, phantom_pkg = collections.Counter(), collections.Counter()

    for root, v in trees.items():
        pub, now = v["published_versions"], v["installed_versions"]
        pv = {p: set(x for x, _ in vulnerable(adv, p, ver)) for p, ver in pub.items()}
        nv = {p: set(x for x, _ in vulnerable(adv, p, ver)) for p, ver in now.items()}
        pset = {(p, a) for p, s in pv.items() for a in s}
        nset = {(p, a) for p, s in nv.items() for a in s}
        missed = nset - pset
        phantom = pset - nset
        for p, a in missed:
            missed_pkg[p] += 1
            for rec in adv.get(p, []):
                if (rec.get("id") or rec.get("title")) == a:
                    missed_sev[rec.get("severity")] += 1
        for p, a in phantom:
            phantom_pkg[p] += 1
            for rec in adv.get(p, []):
                if (rec.get("id") or rec.get("title")) == a:
                    phantom_sev[rec.get("severity")] += 1
        rows.append({"root": root, "n_published_findings": len(pset),
                     "n_installed_findings": len(nset),
                     "missed": len(missed), "phantom": len(phantom)})

    any_find = sum(1 for r in rows if r["n_installed_findings"])
    differ = sum(1 for r in rows if r["missed"] or r["phantom"])
    m_tr = sum(1 for r in rows if r["missed"])
    p_tr = sum(1 for r in rows if r["phantom"])

    def pc(x):
        return f"{100*x/n:.1f}%"

    print(f"=== advisory verdict, published graph vs installed tree, n={n} MCP servers\n")
    print(f"  trees with at least one advisory finding when installed: {any_find} = {pc(any_find)}")
    print(f"  trees where the two verdicts DIFFER:                     {differ} = {pc(differ)}\n")
    print(f"  MISSED  (vulnerable installed, clean in published graph): "
          f"{m_tr} trees = {pc(m_tr)}, {sum(r['missed'] for r in rows)} findings")
    print(f"    by severity: " + ", ".join(f"{s} {missed_sev.get(s,0)}" for s in SEV))
    print(f"  PHANTOM (vulnerable in published graph, clean installed):  "
          f"{p_tr} trees = {pc(p_tr)}, {sum(r['phantom'] for r in rows)} findings")
    print(f"    by severity: " + ", ".join(f"{s} {phantom_sev.get(s,0)}" for s in SEV))

    tot_p = sum(r["n_published_findings"] for r in rows)
    tot_n = sum(r["n_installed_findings"] for r in rows)
    print(f"\n  total findings: published graph {tot_p}, installed tree {tot_n} "
          f"({100*(tot_n-tot_p)/tot_p:+.1f}%)")
    print(f"  net movement understates the error: {sum(r['missed'] for r in rows)} missed and "
          f"{sum(r['phantom'] for r in rows)} phantom findings partly cancel in the total")

    print(f"\n  packages behind the most MISSED findings (count is findings, not trees)")
    for p, c in missed_pkg.most_common(10):
        print(f"    {c:4d} findings  {p}")

    json.dump({"trees": n, "trees_with_findings_installed": any_find,
               "trees_verdict_differs": differ,
               "missed_trees": m_tr, "missed_findings": sum(r["missed"] for r in rows),
               "missed_by_severity": dict(missed_sev),
               "phantom_trees": p_tr, "phantom_findings": sum(r["phantom"] for r in rows),
               "phantom_by_severity": dict(phantom_sev),
               "total_findings_published": tot_p, "total_findings_installed": tot_n,
               "top_missed_packages_findings": missed_pkg.most_common(25),
               "top_phantom_packages_findings": phantom_pkg.most_common(25),
               "per_tree": rows,
               "interpretation": ("the published-graph arm freezes ranges at the root's "
                                  "publish date, modelling a lockfile or SBOM produced at "
                                  "release; it is the worst case for staleness and bounds "
                                  "rather than estimates the crawl-lag gap of a graph service"),
               "limits": ["advisory data read today for both arms, isolating the version "
                          "delta; advisories published after a root shipped are a separate "
                          "and additive effect",
                          "cap-truncated trees excluded",
                          "optional dependencies included without os/cpu evaluation"]},
              open(os.path.join(HERE, "vuln_gap.json"), "w"), indent=1)
    print("\nwrote vuln_gap.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 480) if m == "fetch" else report()
