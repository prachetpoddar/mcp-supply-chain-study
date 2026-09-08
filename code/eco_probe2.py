#!/usr/bin/env python3
"""
Second diagnostic: why does the keyword-match rate vary from 5% to 99%?

THE QUESTION
    eco_enumerate v2 queries /keywords/<name> and checks each returned package
    for the keyword in its keywords_array. Rates came back at 99% for
    gatsby-plugin and 5% for mcp-server. A filter that was simply ignored would
    fail uniformly, so it is not being ignored. Three explanations remain, and
    they have opposite consequences:

      A  keywords_array is sparse. Many packages carry no keyword metadata at
         all in ecosyste.ms, so the test scores them as misses even though the
         index placed them correctly. Then the filter is fine and MY TEST is
         wrong, again.
      B  keywords_array is populated at sync time and goes stale. Newer
         keywords would then be systematically underrepresented, which fits
         mcp-server being the newest keyword and gatsby-plugin an old one.
      C  the keyword index genuinely includes packages that do not carry the
         keyword, in which case the endpoint is unusable for enumeration.

    A and B are both survivable; C is fatal. They are distinguished by looking
    at whether the non-matching packages have an EMPTY keywords_array or a
    populated one that lacks the keyword, and by checking a sample against the
    npm registry directly, which is the ground truth for what a package is
    actually tagged with.

WHAT THIS WRITES
    data/eco_probe2.json, holding the raw response keys, and for each sampled
    package its name, its ecosyste.ms keywords_array, and its last_synced_at.
    The npm cross-check runs separately, in the container, against packuments.

    python3 eco_probe2.py
"""
import json, os, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
BASE = "https://packages.ecosyste.ms/api/v1"
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}
PROBE = ["mcp-server", "model-context-protocol", "gatsby-plugin", "fastify-plugin"]


def get(path, params=None):
    u = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45) as r:
        return json.load(r)


def main():
    os.makedirs(DATA, exist_ok=True)
    out = {}
    for kw in PROBE:
        d = get(f"/keywords/{urllib.parse.quote(kw)}")
        pkgs = d.get("packages") or []
        rows = []
        for p in pkgs:
            ka = p.get("keywords_array")
            rows.append({"name": p.get("name"),
                         "ecosystem": p.get("ecosystem"),
                         "keywords_array": ka,
                         "keywords_empty": not ka,
                         "carries": bool(ka) and kw.lower() in [str(k).lower() for k in ka],
                         "last_synced_at": p.get("last_synced_at"),
                         "latest": p.get("latest_release_number")})
        npm = [r for r in rows if r["ecosystem"] == "npm"]
        empty = sum(1 for r in npm if r["keywords_empty"])
        pop = [r for r in npm if not r["keywords_empty"]]
        carry = sum(1 for r in pop if r["carries"])
        print(f"{kw}")
        print(f"  top-level response keys: {sorted(d.keys())}")
        print(f"  npm packages in sample        : {len(npm)}")
        print(f"  with EMPTY keywords_array     : {empty}")
        print(f"  with populated keywords_array : {len(pop)}, of which carry `{kw}`: {carry}")
        if pop:
            print(f"  match rate among populated    : {100*carry/len(pop):.1f}%")
        miss = [r for r in pop if not r["carries"]][:3]
        for r in miss:
            print(f"    MISS {r['name']}  kw={r['keywords_array'][:6]}  synced={r['last_synced_at']}")
        out[kw] = {"response_keys": sorted(d.keys()),
                   "packages_count_field": d.get("packages_count"),
                   "rows": rows}
        print()
    json.dump(out, open(os.path.join(DATA, "eco_probe2.json"), "w"), indent=1)
    print("wrote data/eco_probe2.json  (stage this back for the npm cross-check)")


if __name__ == "__main__":
    main()
