#!/usr/bin/env python3
"""
A: download-weight the surviving PyPI finding.

Run this IN YOUR OWN TERMINAL (not through Claude). The research container's
egress policy blocks every download source: api.npmjs.org, pypistats.org,
pepy.tech, ecosyste.ms, libraries.io and ClickHouse's public endpoint.

    python3 RUN_A_pypi_weighting.py pypi_sample_for_weighting.json

Runtime ~5 minutes (pypistats is rate limited, so this paces itself).
No API key, no auth.

THE QUESTION
    Package-weighted, 32.8% of Python MCP servers ship with no license
    information at all, against a validated ~18% baseline for general PyPI.
    Is that concentrated in packages nobody installs?

WHAT TO LOOK FOR
    * gini and top-N share tell you how concentrated installs are.
    * "download_weighted_pct" is the number that matters. If it collapses
      toward zero, the finding is statistically true and commercially thin:
      the unlicensed packages are ones nobody runs.
    * If it stays near 30%, the finding is real for actual users and is the
      one thing worth publishing from four rounds of measurement.

PRIOR EVIDENCE (proxies, since downloads were unreachable)
    Release count and recency both say it survives: packages with >=4
    releases AND activity in the last year still show 31.1% +/- 11.6 missing,
    against 32.8% overall. So I expect the download-weighted figure to land
    somewhere in the 20-35% band. A result far below that would be new
    information and would change the recommendation.
"""
import json, sys, time, math, urllib.request, urllib.error

UA = {"User-Agent": "mcp-license-study/1.0 (academic research)"}

def downloads(name, tries=3):
    url = f"https://pypistats.org/api/packages/{urllib.parse.quote(name)}/recent"
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return (json.load(r).get("data") or {}).get("last_month", 0)
        except urllib.error.HTTPError as e:
            if e.code == 404: return 0
            time.sleep(2 ** a)
        except Exception:
            time.sleep(2 ** a)
    return None

def gini(vals):
    v = sorted(x for x in vals if x is not None)
    n, tot = len(v), sum(v)
    if not n or not tot: return None
    return round((2*sum((i+1)*x for i, x in enumerate(v)))/(n*tot) - (n+1)/n, 4)

def wilson(k, n):
    if not n: return (0, 0)
    p = k/n; z = 1.96
    d = 1 + z*z/n
    c = (p + z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return (round(100*(c-h), 1), round(100*(c+h), 1))

import urllib.parse
rows = json.load(open(sys.argv[1]))
print(f"fetching last-month downloads for {len(rows)} packages ...\n")
for i, r in enumerate(rows):
    r["downloads"] = downloads(r["name"])
    if (i+1) % 25 == 0: print(f"  {i+1}/{len(rows)}")
    time.sleep(0.45)

ok = [r for r in rows if r["downloads"] is not None]
dl = [r["downloads"] for r in ok]
tot = sum(dl) or 1
v = sorted(dl, reverse=True)
print("\n=== CONCENTRATION ===")
print(f"  packages: {len(ok)}   total last-month downloads: {tot:,}")
print(f"  gini: {gini(dl)}")
for k in (1, 5, 10, 25, 50):
    if k <= len(v): print(f"  top {k:3d} share: {100*sum(v[:k])/tot:5.1f}%")
print(f"  packages with 0 downloads: {sum(1 for x in dl if x == 0)}")

miss = [r for r in ok if not r["has_license"]]
pw_k, pw_n = len(miss), len(ok)
dw_k, dw_n = sum(r["downloads"] for r in miss), tot
lo, hi = wilson(pw_k, pw_n)
print("\n=== NO LICENSE INFORMATION AT ALL ===")
print(f"  package-weighted : {100*pw_k/pw_n:5.1f}%  (95% CI {lo}-{hi})   {pw_k}/{pw_n}")
print(f"  download-weighted: {100*dw_k/dw_n:5.1f}%   {dw_k:,}/{dw_n:,} installs")
ratio = (dw_k/dw_n)/(pw_k/pw_n) if pw_k else 0
print(f"  ratio dw/pw: {ratio:.2f}")
print("\n  " + ("FINDING SURVIVES: unlicensed packages are actually installed."
      if ratio > 0.6 else
      "FINDING IS THIN: the unlicensed packages are ones almost nobody installs."))

print("\n=== by download decile ===")
s = sorted(ok, key=lambda r: -r["downloads"])
d = max(1, len(s)//10)
for i in range(0, len(s), d):
    g = s[i:i+d]
    if not g: continue
    k = sum(1 for r in g if not r["has_license"])
    print(f"  decile {i//d+1:2d}  n={len(g):3d}  median dl {sorted(x['downloads'] for x in g)[len(g)//2]:>9,}  no license {100*k/len(g):5.1f}%")

json.dump(rows, open("pypi_weighted_result.json", "w"), indent=1)
print("\nwrote pypi_weighted_result.json")
