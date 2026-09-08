#!/usr/bin/env python3
"""
Re-fetch deps.dev graphs preserving (name, version) PAIRS.

WHY v1's STATE CANNOT BE REUSED
    depsdev_delta.py accumulated the response into a dict keyed on package
    name:

        nodes[vk["name"]] = vk.get("version")

    When deps.dev's graph carries the same package at two versions, the second
    silently overwrites the first. That is the identical flattening error that
    made the flat-map comparison unidentified, committed in the fetcher rather
    than the analysis, so it cannot be undone from the stored file. A re-fetch
    is required; data/depsdev_state.json is left untouched.

WHAT THIS STORES
    The full node list as pairs, plus the raw count, so the analysis side can
    see duplicates and compare set to set with no arbitrary choice.

    python3 depsdev_pairs.py

    Writes data/depsdev_pairs.json. Resumable: rerun after an interruption.
"""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
API = ("https://api.deps.dev/v3alpha/systems/npm/packages/{}"
       "/versions/{}:dependencies")
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}
STATE = os.path.join(DATA, "depsdev_pairs.json")
PAUSE = 0.35


def enc(n):
    return urllib.parse.quote(n, safe="")


def main():
    trees = json.load(open(os.path.join(DATA, "resolved_trees_for_depsdev.json")))
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [t for t in trees if t["server"] not in s]
    print(f"deps.dev pairs: {len(todo)} roots to query of {len(trees)}")
    for i, t in enumerate(todo):
        url = API.format(enc(t["root_name"]), urllib.parse.quote(t["root_version"], safe=""))
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=45) as r:
                d = json.load(r)
            pairs, dropped = [], 0
            for nd in d.get("nodes", []):
                vk = nd.get("versionKey") or {}
                if vk.get("name") and vk.get("version"):
                    pairs.append([vk["name"], vk["version"]])
                else:
                    dropped += 1
            names = {p[0] for p in pairs}
            s[t["server"]] = {"ok": True, "pairs": pairs,
                              "n_pairs": len(pairs), "n_names": len(names),
                              "duplicated_names": len(pairs) - len(names),
                              "dropped_nodes": dropped}
        except Exception as e:
            s[t["server"]] = {"ok": False, "error": type(e).__name__,
                              "code": getattr(e, "code", None)}
        if i % 25 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(PAUSE)
    json.dump(s, open(STATE, "w"))
    ok = [v for v in s.values() if v.get("ok")]
    dup = sum(v["duplicated_names"] for v in ok)
    withdup = sum(1 for v in ok if v["duplicated_names"])
    print(f"\ndone: {len(ok)} resolved, {len(s)-len(ok)} failed")
    print(f"  graphs carrying a duplicated package name: {withdup}/{len(ok)}")
    print(f"  duplicate pairs beyond one per name, total: {dup}")
    print("  (if that total is 0, deps.dev flattens too and v1's dict lost nothing)")
    print("\nwrote data/depsdev_pairs.json")


if __name__ == "__main__":
    main()
