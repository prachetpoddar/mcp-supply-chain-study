#!/usr/bin/env python3
"""
Re-run the coverage correction for rows 3 and 6 on the validated resolver.

WHY
    rows_3_6_corrected.json combined a stratum A rate with a tail (B+C) rate,
    both measured with mcplib.npm_walk. That walker carried three errors, each
    found by comparing against a real `npm install` rather than against our own
    logic:

      1. it ignored the `latest` dist-tag, taking the highest satisfying
         version instead. npm prefers the version tagged latest whenever it
         satisfies the range, even when a higher one exists.
      2. it took deprecated versions when a non-deprecated one satisfied
      3. it excluded peerDependencies, which npm 7+ auto-installs unless the
         package marks them optional

    Both arms carried all three, so the correction combined two biased rates.
    The stratum A arm is re-measured here from the pair-keyed corrected walk,
    and the tail arm is re-walked over the identical 250-package sample, drawn
    with the original seed so the comparison is like for like.

    Weighting is unchanged from tail_walks.py: a stratified estimate over the
    reached strata, with Manski bounds over the unreached stratum D. The one
    thing this does NOT inherit is that script's hardcoded 0.156 hook rate for
    stratum A, which is recomputed from the walk here.

    python3 rerun_strata.py fetch [seconds]
    python3 rerun_strata.py report
"""
import json, os, random, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import install_gap as IG
import nested_gap as NG
import tail_walks

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/rerun_strata.json"
HOOKS = ("preinstall", "install", "postinstall")
POP, NA = 8238, 5250


def measure(nodes):
    dep = hook = 0
    for nm, ver in nodes:
        try:
            m = mcplib.npm_packument(nm)["versions"].get(ver, {}) or {}
        except Exception:
            continue
        if m.get("deprecated"):
            dep += 1
        sc = m.get("scripts") or {}
        if any(sc.get(h) for h in HOOKS):
            hook += 1
    return {"nodes": len(nodes), "deprecated": dep, "hooks": hook}


def fetch(budget):
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    names = tail_walks.sample()
    todo = [n for n in names if n not in s]
    print(f"tail re-walk: {len(todo)} remaining of {len(names)}")
    t0 = time.time()
    for i, n in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        try:
            v, _ = IG.resolve_at(n, "latest", None)
            if v is None:
                s[n] = {"error": "unresolved"}
            else:
                nodes, trunc = NG.pair_walk(n, v, None)
                r = measure(nodes)
                r["truncated"] = trunc
                s[n] = r
        except Exception as e:
            s[n] = {"error": type(e).__name__}
        if i % 20 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)} net={mcplib.STATS['net']}", flush=True)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if "error" not in v)
    print(f"done: {ok} ok, {len(s)-ok} errors")


def report():
    s = json.load(open(STATE))
    tail = [v for v in s.values() if "error" not in v and not v.get("truncated")]
    ng = json.load(open("/tmp/mcpres/nested_gap.json"))

    def split(x):
        n, _, v = x.rpartition("@@")
        return n, v

    A = [measure({split(x) for x in g["installed"]})
         for g in ng.values() if "skip" not in g and not g["truncated"]]

    comp = set(json.load(open(os.path.join(HERE, "npm_frame_complete.json"))))
    NBC = len(comp) - NA
    ND = POP - len(comp)
    print(f"strata: A={NA} B+C={NBC} unreached={ND} of {POP}")
    print(f"stratum A n={len(A)}   tail n={len(tail)}\n")
    print(f"{'metric':24s} {'A':>9s} {'tail':>9s} {'corrected':>10s} {'bounds':>14s} {'published':>10s}")
    print("-" * 82)
    PUB = {"deprecated in tree": (18.1, [17.3, 22.2]),
           "install hook in tree": (14.8, [14.1, 19.0])}
    out = {"strata": {"A": NA, "BC": NBC, "D": ND, "population": POP},
           "median_tree_A": sorted(r["nodes"] for r in A)[len(A) // 2],
           "median_tree_tail": sorted(r["nodes"] for r in tail)[len(tail) // 2]}
    for label, key in (("deprecated in tree", "deprecated"),
                       ("install hook in tree", "hooks")):
        a = sum(1 for r in A if r[key])
        b = sum(1 for r in tail if r[key])
        pA, pT = a / len(A), b / len(tail)
        obs = NA * pA + NBC * pT
        corr = obs / (NA + NBC)
        lo, hi = obs / POP, (obs + ND) / POP
        p, pb = PUB[label]
        print(f"{label:24s} {100*pA:8.1f}% {100*pT:8.1f}% {100*corr:9.1f}% "
              f"[{100*lo:4.1f},{100*hi:5.1f}] {p:9.1f}%")
        out[label] = {"A": [a, len(A)], "tail": [b, len(tail)],
                      "corrected": round(100 * corr, 1),
                      "bounds": [round(100 * lo, 1), round(100 * hi, 1)],
                      "published_corrected": p, "published_bounds": pb}
    print(f"\nmedian tree: A {out['median_tree_A']}, tail {out['median_tree_tail']} "
          f"(published: A 97, tail 96)")
    json.dump(out, open(os.path.join(HERE, "rows_3_6_corrected_v2.json"), "w"), indent=1)
    print("wrote rows_3_6_corrected_v2.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 540) if m == "fetch" else report()
