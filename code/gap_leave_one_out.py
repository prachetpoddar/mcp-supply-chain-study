"""Leave-one-out check on the frozen-versus-live verdict rate.

The count of individual phantom findings is dominated by `hono` (2,017 of
4,442). The rate -- trees where the frozen tree flags and the installed tree is
clean -- is a different quantity, and this script measures how much of it `hono`
carries. It rebuilds the crosstab of code/nested_gap.py's report() with a set of
package names suppressed from the advisory join on both arms.

Run: python3 code/gap_leave_one_out.py      (from the repository root)
"""
import collections
import json
import os

import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
STATE = os.environ.get("GAP_STATE", os.path.join(DATA, "nested_gap_state.json"))
ADVISORIES = os.environ.get("ADVISORIES", os.path.join(DATA, "advisories_npm.json"))

TOP5 = ("hono", "fast-uri", "qs", "axios", "ip-address")


def split(x):
    n, _, v = x.rpartition("@@")
    return n, v


def main():
    raw = json.load(open(STATE))
    s = {k: v for k, v in raw.items() if "skip" not in v and not v["truncated"]}
    adv = json.load(open(ADVISORIES))

    def vids(name, ver, drop):
        if name in drop:
            return []
        o = []
        for a in adv.get(name) or []:
            r = a.get("vulnerable_versions")
            if not r:
                continue
            try:
                if sv.satisfies(ver, r, loose=True, include_prerelease=True):
                    o.append(a.get("id"))
            except Exception:
                pass
        return o

    def crosstab(drop):
        cross = collections.Counter()
        for v in s.values():
            fz, lv = set(), set()
            for x in v["published"]:
                n, ver = split(x)
                for i in vids(n, ver, drop):
                    fz.add((n, i))
            for x in v["installed"]:
                n, ver = split(x)
                for i in vids(n, ver, drop):
                    lv.add((n, i))
            cross[(bool(fz), bool(lv))] += 1
        return cross

    out = {}
    for label, drop in [("none", set()),
                        ("hono", {"hono"}),
                        ("hono_and_node_server", {"hono", "@hono/node-server"}),
                        ("top5", set(TOP5))]:
        c = crosstab(drop)
        n = sum(c.values())
        ph, ms = c[(True, False)], c[(False, True)]
        out[label] = {"trees": n, "frozen_flags_live_clean": ph,
                      "rate_pct": round(100.0 * ph / n, 1),
                      "live_flags_frozen_clean": ms,
                      "both_flag": c[(True, True)],
                      "neither_flags": c[(False, False)]}
        print(f"drop={label:22s} n={n} frozen_only={ph} ({100.0*ph/n:.1f}%) "
              f"live_only={ms} both={c[(True, True)]} neither={c[(False, False)]}")

    dst = os.path.join(DATA, "gap_leave_one_out.json")
    json.dump({"source_state": os.path.basename(STATE),
               "advisory_basis": os.path.basename(ADVISORIES),
               "results": out}, open(dst, "w"), indent=1)
    print("wrote", dst)


if __name__ == "__main__":
    main()
