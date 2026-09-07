#!/usr/bin/env python3
"""Usage-weighted re-analysis of the MCP study.

Run this on your own machine. It needs two hosts this research container
cannot reach (both are blocked by the sandbox egress policy):
    api.npmjs.org      npm download counts
    pypistats.org      PyPI download counts

What it answers: every statistic in the study so far is PACKAGE-weighted
(each package counts once). This re-weights by installs, so the numbers
describe what people actually run rather than what exists.

Usage:  python3 usage_weighting.py mcp-study-v2-data.json
"""
import json, sys, time, urllib.request, urllib.parse, collections, math

UA = {"User-Agent": "mcp-usage-study/0.1 (research)"}

def npm_downloads(names, period="last-month"):
    """npm bulk endpoint: 128 unscoped names per call; scoped must be singular."""
    out, bulk, scoped = {}, [n for n in names if not n.startswith("@")], [n for n in names if n.startswith("@")]
    for i in range(0, len(bulk), 128):
        chunk = bulk[i:i+128]
        u = f"https://api.npmjs.org/downloads/point/{period}/" + ",".join(chunk)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
            for k, v in d.items():
                if isinstance(v, dict): out[k] = v.get("downloads", 0)
        except Exception as e:
            print(f"  bulk chunk failed: {type(e).__name__}", file=sys.stderr)
        time.sleep(0.3)
    for n in scoped:
        u = f"https://api.npmjs.org/downloads/point/{period}/{urllib.parse.quote(n, safe='@/')}"
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
            out[n] = d.get("downloads", 0)
        except Exception:
            out[n] = 0
        time.sleep(0.15)
    return out

def pypi_downloads(names):
    out = {}
    for n in names:
        try:
            u = f"https://pypistats.org/api/packages/{urllib.parse.quote(n)}/recent"
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
            out[n] = (d.get("data") or {}).get("last_month", 0)
        except Exception:
            out[n] = 0
        time.sleep(0.4)          # pypistats is rate limited; be polite
    return out

def concentration(dl):
    """Gini plus top-N share. This is the number that decides the question."""
    v = sorted(x for x in dl.values() if x is not None)
    n, tot = len(v), sum(v)
    if not n or not tot: return {}
    gini = (2*sum((i+1)*x for i, x in enumerate(v)))/(n*tot) - (n+1)/n
    cum = {}
    for k in (1, 5, 10, 20, 50, 100):
        if k <= n: cum[f"top{k}_share"] = round(100*sum(v[-k:])/tot, 2)
    return {"gini": round(gini, 4), "n": n, "total_downloads": tot, **cum}

def weighted_rate(rows, key_name, predicate, dl):
    """Compare package-weighted with download-weighted rates for one predicate."""
    pk = [r for r in rows if r[key_name] in dl]
    if not pk: return None
    pw_k = sum(1 for r in pk if predicate(r)); pw_n = len(pk)
    dw_k = sum(dl[r[key_name]] for r in pk if predicate(r))
    dw_n = sum(dl[r[key_name]] for r in pk) or 1
    return {"package_weighted_pct": round(100*pw_k/pw_n, 1),
            "download_weighted_pct": round(100*dw_k/dw_n, 1),
            "n_packages": pw_n, "n_downloads": dw_n}

if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    npm_rows = data["npm_stage1_metadata"]
    names = [r["name"] for r in npm_rows]
    print(f"fetching npm downloads for {len(names)} packages ...")
    dl = npm_downloads(names)
    print("\nCONCENTRATION:", json.dumps(concentration(dl), indent=1))
    def unev(r):
        l = r.get("license")
        return not l or not str(l).strip()
    print("\nno license field:", json.dumps(weighted_rate(npm_rows, "name", unev, dl), indent=1))
    print("\nsingle version: ", json.dumps(
        weighted_rate(npm_rows, "name", lambda r: r["n_versions"] == 1, dl), indent=1))
    json.dump(dl, open("npm_downloads.json", "w"))
    print("\nwrote npm_downloads.json")
