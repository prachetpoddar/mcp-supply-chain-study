#!/usr/bin/env python3
"""
Re-measure the paper's tree-dependent rows on the corrected resolver.

WHY
    Rows 3 (deprecated package in tree) and 6 (install hook in tree), and the
    corresponding design-effect rows in 5.1, are computed over resolved
    dependency trees. Both arms were walked with a resolver carrying two errors
    found by validating against a real `npm install`:

      1. it took the highest version satisfying a range, where npm prefers a
         non-deprecated one and falls back only if nothing else satisfies
      2. it excluded peerDependencies, which npm 7+ auto-installs unless the
         package marks them optional in peerDependenciesMeta

    Error 1 is NOT direction-neutral for row 3. A resolver that over-selects
    deprecated versions inflates a "deprecated package in tree" rate by
    construction, so that row could be measuring the resolver rather than the
    ecosystem. Both arms carry the same bias, so it partly cancels in the
    contrast, but only to the extent the arms have similar deprecation rates,
    which is exactly what row 3 claims to measure. It has to be re-run.

    Error 2 inflates tree size, which raises row 6 in whichever arm has more
    peer declarations.

    Control arms are regenerated from the study's own seed (random.seed(2468)
    over frames3.json) and verified to reproduce the stored sample order, so
    this compares like with like and not a fresh draw.

    python3 rerun_tree_rows.py run [seconds]
    python3 rerun_tree_rows.py report
"""
import collections, json, os, random, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import install_gap as IG
import nested_gap as NG

STATE = "/tmp/mcpres/rerun_tree_rows.json"
HOOKS = ("preinstall", "install", "postinstall")


def arms():
    f = json.load(open("/tmp/mcpres/frames3.json"))
    random.seed(2468)
    return {"langchain": random.sample(f["keywords:langchain"]["names"], 120),
            "eslint-plugin": random.sample(f["keywords:eslint-plugin"]["names"], 120)}


def measure(nodes):
    dep = hook = 0
    for name, ver in nodes:
        try:
            m = mcplib.npm_packument(name)["versions"].get(ver, {}) or {}
        except Exception:
            continue
        if m.get("deprecated"):
            dep += 1
        s = m.get("scripts") or {}
        if any(s.get(h) for h in HOOKS):
            hook += 1
    return {"n_nodes": len(nodes), "deprecated": dep, "hooks": hook}


def run(budget):
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    t0 = time.time()
    for arm, names in arms().items():
        s.setdefault(arm, {})
        todo = [n for n in names if n not in s[arm]]
        print(f"{arm}: {len(todo)} to walk of {len(names)}")
        for i, n in enumerate(todo):
            if time.time() - t0 > budget:
                print("  budget reached")
                json.dump(s, open(STATE, "w"))
                return
            try:
                v, _ = IG.resolve_at(n, "latest", None)
                if v is None:
                    s[arm][n] = {"skip": "root unresolved"}
                    continue
                nodes, trunc = NG.pair_walk(n, v, None)
                r = measure(nodes)
                r["truncated"] = trunc
                s[arm][n] = r
            except Exception as e:
                s[arm][n] = {"skip": repr(e)[:100]}
            if i % 25 == 0:
                json.dump(s, open(STATE, "w"))
                print(f"  {i}/{len(todo)} net={mcplib.STATS['net']}", flush=True)
        json.dump(s, open(STATE, "w"))
    json.dump(s, open(STATE, "w"))
    print("done")


def report():
    s = json.load(open(STATE))
    ng = json.load(open("/tmp/mcpres/nested_gap.json"))

    def split(x):
        n, _, v = x.rpartition("@@")
        return n, v

    out = {}
    # MCP arm from the corrected pair-keyed walk
    mcp = []
    for root, g in ng.items():
        if "skip" in g or g["truncated"]:
            continue
        mcp.append(measure({split(x) for x in g["installed"]}))
    out["mcp"] = mcp
    for arm in ("eslint-plugin", "langchain"):
        out[arm] = [v for v in s.get(arm, {}).values()
                    if "skip" not in v and not v.get("truncated")]

    PAPER = {"mcp": {"dep": 18.1, "hook": 14.8, "med": 96},
             "eslint-plugin": {"dep": 20.4, "hook": 2.5, "med": 8},
             "langchain": {"dep": 25.6, "hook": 14.2, "med": 6}}
    print(f"{'arm':16s} {'n':>4s} {'median tree':>12s} "
          f"{'deprecated in tree':>20s} {'hook in tree':>14s}")
    print("-" * 72)
    res = {}
    for arm, rows in out.items():
        if not rows:
            continue
        n = len(rows)
        med = statistics.median([r["n_nodes"] for r in rows])
        dep = 100 * sum(1 for r in rows if r["deprecated"]) / n
        hook = 100 * sum(1 for r in rows if r["hooks"]) / n
        p = PAPER.get(arm, {})
        print(f"{arm:16s} {n:4d} {med:8.0f} (was {p.get('med','?')})  "
              f"{dep:8.1f}% (was {p.get('dep','?')})  {hook:6.1f}% (was {p.get('hook','?')})")
        res[arm] = {"n": n, "median_tree": med,
                    "deprecated_in_tree_pct": round(dep, 1),
                    "hook_in_tree_pct": round(hook, 1),
                    "paper_deprecated_pct": p.get("dep"), "paper_hook_pct": p.get("hook"),
                    "paper_median_tree": p.get("med")}
    json.dump({"note": "raw arm rates on the corrected resolver; the paper's MCP row 3 "
                       "is additionally coverage-corrected across strata, so the MCP "
                       "figure here is the raw sample rate and not directly the "
                       "published 18.1%",
               "arms": res}, open("rerun_tree_rows.json", "w"), indent=1)
    print("\nwrote rerun_tree_rows.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    run(float(sys.argv[2]) if len(sys.argv) > 2 else 600) if m == "run" else report()
