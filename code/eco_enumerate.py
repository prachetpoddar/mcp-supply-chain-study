#!/usr/bin/env python3
"""
Enumerate npm keyword populations from ecosyste.ms.

WHAT WENT WRONG IN v1, AND WHY IT MATTERED
    v1 called /registries/npmjs.org/packages?keyword=<kw>. That endpoint has no
    keyword parameter -- confirmed against the published OpenAPI spec, whose
    only filters there are page, per_page, created/updated bounds, critical,
    sort and order. Unknown parameters are ignored silently, so every query
    returned the same unfiltered head of the registry.

    Two further v1 errors compounded it. The exact-match test read a `keywords`
    field; the actual field is `keywords_array`, so the test scored zero no
    matter what came back. And v1 printed "if exact-match is not n/n the filter
    is fuzzy", inviting exactly the wrong conclusion from a request bug. Had
    `fetch` been run, it would have paginated the whole npm registry and written
    it out labelled as one keyword's population.

    v1's eco_counts.json is meaningless and must be deleted, not reinterpreted.

WHAT v2 DOES
    Uses /keywords/<name>, the actual keyword resource. It reports
    packages_count directly and carries a paginated packages array, so no
    pagination-cap estimation is needed.

    That resource spans every registry ecosyste.ms indexes, not just npm, so
    the npm subset is taken client-side on each package's `ecosystem` field and
    both totals are reported. The cross-registry total is NOT an npm population
    and is never used as one.

GUARDS, because a silent wrong answer is worse than a loud failure
    1. Every fetched page is checked: each package must carry the keyword in
       keywords_array. If fewer than 95% of a page does, the run aborts.
    2. `fetch` refuses to start unless `count` has recorded a verified
       keyword-match rate for that keyword in this file's own state.
    3. A page whose contents match the previous page aborts the run, which is
       what an ignored pagination parameter looks like.

    python3 eco_enumerate.py count
    python3 eco_enumerate.py fetch [keyword ...]
"""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
BASE = "https://packages.ecosyste.ms/api/v1"
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}
PAUSE = 1.1
PER = 100
NPM = "npm"

KEYWORDS = ["mcp-server", "model-context-protocol", "mcp", "eslint-plugin",
            "langchain", "gatsby-plugin", "vite-plugin", "babel-plugin",
            "ai-tools", "rag", "embeddings", "fastify-plugin",
            "strapi-plugin", "serverless-plugin"]


def get(path, params=None):
    u = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for a in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45) as r:
                return json.load(r)
        except Exception:
            if a == 4:
                raise
            time.sleep(2 ** a)


def kwset(p):
    return {str(k).lower() for k in (p.get("keywords_array") or [])}


def count():
    os.makedirs(DATA, exist_ok=True)
    out = {}
    print(f"{'keyword':24s} {'all registries':>14s} {'npm in sample':>14s} "
          f"{'kw match':>10s}")
    print("-" * 66)
    for kw in KEYWORDS:
        try:
            d = get(f"/keywords/{urllib.parse.quote(kw)}")
        except Exception as e:
            print(f"{kw:24s} ERROR {repr(e)[:40]}")
            out[kw] = {"error": repr(e)[:200]}
            continue
        total = d.get("packages_count")
        sample = d.get("packages") or []
        match = sum(1 for p in sample if kw.lower() in kwset(p))
        npm_n = sum(1 for p in sample if p.get("ecosystem") == NPM)
        rate = (match / len(sample)) if sample else 0.0
        out[kw] = {"packages_count_all_registries": total,
                   "sample_n": len(sample), "sample_carrying_keyword": match,
                   "keyword_match_rate": round(rate, 3),
                   "sample_npm": npm_n,
                   "packages_url": d.get("packages_url"),
                   "verified": rate >= 0.95 and len(sample) > 0}
        print(f"{kw:24s} {str(total):>14s} {npm_n:>10d}/{len(sample):<3d} "
              f"{100*rate:>9.1f}%")
        time.sleep(PAUSE)
    json.dump(out, open(os.path.join(DATA, "eco_counts.json"), "w"), indent=1)
    print("\nwrote data/eco_counts.json")
    bad = [k for k, v in out.items() if not v.get("verified")]
    if bad:
        print(f"NOT VERIFIED, fetch will refuse these: {bad}")
    print("packages_count spans ALL registries. It is not an npm population. "
          "Run fetch to get the npm subset.")


def fetch(only=None):
    counts = json.load(open(os.path.join(DATA, "eco_counts.json")))
    for kw in (only or KEYWORDS):
        c = counts.get(kw) or {}
        if not c.get("verified"):
            print(f"{kw}: REFUSED, count did not verify the keyword match rate")
            continue
        path = os.path.join(DATA, f"eco_{kw}.json")
        seen = {r["name"]: r for r in json.load(open(path))} if os.path.exists(path) else {}
        page, prev = len(seen) // PER + 1, None
        print(f"{kw}: resuming at page {page} with {len(seen)} held "
              f"(of {c.get('packages_count_all_registries')} across all registries)")
        while True:
            rows = get(f"/keywords/{urllib.parse.quote(kw)}/packages",
                       {"page": page, "per_page": PER})
            if not rows:
                break
            names = [r.get("name") for r in rows]
            if names == prev:                       # pagination ignored
                print(f"  ABORT: page {page} identical to page {page-1}")
                break
            prev = names
            ok = sum(1 for r in rows if kw.lower() in kwset(r))
            if ok / len(rows) < 0.95:               # filter not applied
                print(f"  ABORT: only {ok}/{len(rows)} on page {page} carry `{kw}`")
                break
            for r in rows:
                if r.get("ecosystem") != NPM:
                    continue
                seen[r["name"]] = {"name": r.get("name"),
                                   "keywords": sorted(kwset(r)),
                                   "namespace": r.get("namespace"),
                                   "latest": r.get("latest_release_number"),
                                   "versions_count": r.get("versions_count")}
            json.dump(list(seen.values()), open(path, "w"))
            print(f"  page {page:4d}: +{len(rows)} rows, npm held {len(seen)}", flush=True)
            page += 1
            time.sleep(PAUSE)
        print(f"{kw}: {len(seen)} npm packages -> data/eco_{kw}.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "count"
    fetch(sys.argv[2:] or None) if m == "fetch" else count()
