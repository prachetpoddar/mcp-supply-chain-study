#!/usr/bin/env python3
"""
Advisory consequence of the deps.dev / live-resolution gap.

vuln_gap.py answered this for a publish-time-frozen graph, which is the worst
case for staleness. This answers it for the graph a service actually serves:
deps.dev's published graph for each root's exact (name, version), against the
tree npm resolution materializes today.

Same two error directions, same asymmetry to watch for:
    MISSED   vulnerable in the live tree, clean in deps.dev's graph
    PHANTOM  vulnerable in deps.dev's graph, clean in the live tree

Advisory source is registry.npmjs.org/-/npm/v1/security/advisories/bulk, read
today for both arms, so the version delta is the only moving part.

    python3 vuln_gap_depsdev.py
"""
import collections, json, os, statistics, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nodesemver as sv

UP = "/mnt/user-data/uploads/MCPSupplyChainStudy/data"
HERE = os.path.dirname(os.path.abspath(__file__))
ADV = "/tmp/mcpres/advisories.json"
BULK = "https://registry.npmjs.org/-/npm/v1/security/advisories/bulk"
UA = {"Content-Type": "application/json",
      "User-Agent": "npm/10.0.0 mcp-supply-chain-study/0.4 (academic research)"}


def top_up(want):
    adv = json.load(open(ADV)) if os.path.exists(ADV) else {}
    todo = sorted(n for n in want if n not in adv)
    print(f"advisory cache: {len(adv)} held, {len(todo)} to fetch")
    for i in range(0, len(todo), 150):
        chunk = todo[i:i + 150]
        body = json.dumps({n: sorted(want[n]) for n in chunk}).encode()
        d = None
        for a in range(5):
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(BULK, data=body, headers=UA), timeout=60) as r:
                    d = json.load(r)
                break
            except Exception:
                time.sleep(2 ** a)
        for n in chunk:
            adv[n] = (d or {}).get(n, [])
        json.dump(adv, open(ADV, "w"))
        time.sleep(0.4)
    return adv


def vids(adv, name, ver):
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


def main():
    state = json.load(open(os.path.join(UP, "depsdev_state.json")))
    trees = {t["server"]: t["resolved"]
             for t in json.load(open(os.path.join(UP, "resolved_trees_for_depsdev.json")))}

    pairs = {}
    for srv, rec in state.items():
        if not rec.get("ok") or srv not in trees:
            continue
        pairs[srv] = (rec["nodes"], trees[srv])
    print(f"comparable servers: {len(pairs)}")

    want = collections.defaultdict(set)
    for dd, live in pairs.values():
        for m in (dd, live):
            for n, v in m.items():
                want[n].add(v)
    adv = top_up(want)

    SEV = ["critical", "high", "moderate", "low"]
    msev, psev = collections.Counter(), collections.Counter()
    mtree, ptree = collections.Counter(), collections.Counter()
    rows = []
    for srv, (dd, live) in pairs.items():
        p = {(n, a) for n, v in dd.items() for a, _ in vids(adv, n, v)}
        q = {(n, a) for n, v in live.items() for a, _ in vids(adv, n, v)}
        missed, phantom = q - p, p - q
        for n, a in missed:
            for rec in adv.get(n, []):
                if rec.get("id") == a:
                    msev[rec.get("severity")] += 1
        for n, a in phantom:
            for rec in adv.get(n, []):
                if rec.get("id") == a:
                    psev[rec.get("severity")] += 1
        for n in {n for n, _ in missed}:
            mtree[n] += 1
        for n in {n for n, _ in phantom}:
            ptree[n] += 1
        rows.append({"server": srv, "depsdev_findings": len(p), "live_findings": len(q),
                     "missed": len(missed), "phantom": len(phantom)})

    n = len(rows)
    differ = sum(1 for r in rows if r["missed"] or r["phantom"])
    m_tr = sum(1 for r in rows if r["missed"])
    p_tr = sum(1 for r in rows if r["phantom"])
    live_any = sum(1 for r in rows if r["live_findings"])

    def pc(x):
        return f"{100*x/n:.1f}%"

    print(f"\n=== advisory verdict: deps.dev published graph vs live resolution, n={n}\n")
    print(f"  servers with at least one real finding when installed: {live_any} = {pc(live_any)}")
    print(f"  servers where the two verdicts DIFFER:                 {differ} = {pc(differ)}\n")
    print(f"  MISSED  (vulnerable live, clean in deps.dev): {m_tr} servers = {pc(m_tr)}, "
          f"{sum(r['missed'] for r in rows)} findings")
    print("    by severity: " + ", ".join(f"{s} {msev.get(s,0)}" for s in SEV))
    print(f"  PHANTOM (vulnerable in deps.dev, clean live): {p_tr} servers = {pc(p_tr)}, "
          f"{sum(r['phantom'] for r in rows)} findings")
    print("    by severity: " + ", ".join(f"{s} {psev.get(s,0)}" for s in SEV))
    tp = sum(r["depsdev_findings"] for r in rows)
    tl = sum(r["live_findings"] for r in rows)
    print(f"\n  total findings: deps.dev {tp}, live {tl} ({100*(tl-tp)/tp:+.1f}%)" if tp else
          f"\n  total findings: deps.dev {tp}, live {tl}")
    print("\n  packages behind the most MISSED findings (distinct servers)")
    for k, c in mtree.most_common(8):
        print(f"    {c:4d} servers  {k}")
    print("  packages behind the most PHANTOM findings (distinct servers)")
    for k, c in ptree.most_common(8):
        print(f"    {c:4d} servers  {k}")

    json.dump({"servers": n, "servers_with_live_findings": live_any,
               "servers_verdict_differs": differ,
               "missed_servers": m_tr, "missed_findings": sum(r["missed"] for r in rows),
               "missed_by_severity": dict(msev),
               "phantom_servers": p_tr, "phantom_findings": sum(r["phantom"] for r in rows),
               "phantom_by_severity": dict(psev),
               "total_findings_depsdev": tp, "total_findings_live": tl,
               "top_missed_distinct_servers": mtree.most_common(25),
               "top_phantom_distinct_servers": ptree.most_common(25),
               "per_server": rows,
               "limits": ["advisory data read today for both arms",
                          "live arm includes optional deps without os/cpu evaluation",
                          "deps.dev graph fetched once; its crawl lag at fetch time is not "
                          "separately observable"]},
              open(os.path.join(HERE, "vuln_gap_depsdev.json"), "w"), indent=1)
    print("\nwrote vuln_gap_depsdev.json")


if __name__ == "__main__":
    main()
