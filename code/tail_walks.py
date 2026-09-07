#!/usr/bin/env python3
"""
Walk a sample of the packages the original frame could not see, so rows 3 and 6
get the same coverage correction as rows 1, 2, 4 and 5.

Rows 3 (deprecated dependency in tree) and 6 (install hook in tree) were
measured on stratum A only, the 63.7% score-ordered slice. Row 5 showed what
that does: single-version publication read 25.2% on stratum A and 45.2% once
the population was enumerated to 95.1%. Rows 3 and 6 are tree-shaped rather
than metadata-shaped, so the direction of the bias is not obvious in advance,
which is the reason to measure rather than assume.

Sample: 250 drawn from strata B and C combined, in proportion to their sizes.

    python3 tail_walks.py fetch [seconds]
    python3 tail_walks.py report
"""
import json, math, os, random, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/tail_walks_state.json"
N, SEED = 250, 20260907
HOOKS = ("preinstall", "install", "postinstall")


def sample():
    comp = set(json.load(open(os.path.join(HERE, "npm_frame_complete.json"))))
    wide = set(json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json"))))
    orig = set()

    def collect(o):
        if isinstance(o, dict):
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for x in o:
                if isinstance(x, str):
                    orig.add(x)
                elif isinstance(x, dict) and "name" in x:
                    orig.add(x["name"])
                else:
                    collect(x)

    collect(json.load(open(os.path.join(HERE, "mcp-substitutability.json"))))
    tail = sorted((wide - orig) | (comp - wide))
    random.Random(SEED).shuffle(tail)
    return tail[:N]


def load():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def fetch(budget):
    s, t0 = load(), time.time()
    todo = [n for n in sample() if n not in s]
    print(f"tail walks: {len(todo)} remaining of {N}")
    for i, n in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}"); break
        try:
            nodes, _ = mcplib.npm_walk(n, "latest")
            dep = sum(1 for v in nodes.values() if v.get("deprecated"))
            hook = 0
            for (nm, ver) in nodes:
                if ver.startswith(("NON-REGISTRY", "UNRESOLVED")):
                    continue
                try:
                    m = mcplib.npm_packument(nm)["versions"].get(ver, {})
                except Exception:
                    continue
                sc = m.get("scripts") or {}
                if any(h in sc for h in HOOKS):
                    hook += 1
            s[n] = {"nodes": len(nodes), "deprecated": dep, "hooks": hook}
        except Exception as e:
            s[n] = {"error": type(e).__name__}
        if i % 10 == 0:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)}  cache={mcplib.STATS['cache_hit']} net={mcplib.STATS['net']}", flush=True)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if "error" not in v)
    print(f"done: {ok} ok, {len(s)-ok} errors")


def report():
    POP, NA = 8238, 5250
    comp = set(json.load(open(os.path.join(HERE, "npm_frame_complete.json"))))
    NBC = len(comp) - NA
    ND = POP - len(comp)
    rows = [v for v in load().values() if "error" not in v]
    n = len(rows)
    if not n:
        print("no data yet"); return

    v2 = json.load(open(os.path.join(HERE, "mcp-study-v2-data.json")))
    walk = [json.loads(l) for l in open("/tmp/mcpres/walk250.jsonl")]
    aA_dep = sum(1 for r in walk if any(p.get("deprecated") for p in r["pkgs"].values()))
    nA = len(walk)
    vd = json.load(open(os.path.join(HERE, "mcp-variance-dimensions.json")))
    hooks_A = vd["install_scripts"]

    tail_dep = sum(1 for r in rows if r["deprecated"] > 0)
    tail_hook = sum(1 for r in rows if r["hooks"] > 0)
    med = sorted(r["nodes"] for r in rows)[n // 2]

    print(f"strata: A={NA} B+C={NBC} unreached={ND} of {POP}\n")
    print(f"{'metric':26s} {'stratum A':>12s} {'tail B+C':>12s} {'corrected':>10s} {'bounds':>16s}")
    print("-" * 82)
    out = {"median_tree_tail": med, "median_tree_A": sorted(r["nodes"] for r in walk)[nA // 2]}
    for label, a, na, b, nb in [
        ("deprecated in tree", aA_dep, nA, tail_dep, n),
        ("install hook in tree", int(round(0.156 * 250)), 250, tail_hook, n),
    ]:
        pA, pT = a / na, b / nb
        obs = NA * pA + NBC * pT
        corr = obs / (NA + NBC)
        lo, hi = obs / POP, (obs + ND) / POP
        print(f"{label:26s} {100*pA:11.1f}% {100*pT:11.1f}% {100*corr:9.1f}% [{100*lo:5.1f},{100*hi:5.1f}]")
        out[label] = {"A": [a, na], "tail": [b, nb], "corrected": round(100 * corr, 1),
                      "bounds": [round(100 * lo, 1), round(100 * hi, 1)]}
    print(f"\nmedian tree size: stratum A {out['median_tree_A']}, tail {med}")
    json.dump(out, open(os.path.join(HERE, "rows_3_6_corrected.json"), "w"), indent=1)
    print("wrote rows_3_6_corrected.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 480) if m == "fetch" else report()
