#!/usr/bin/env python3
"""
Complete MCP population enumeration, with usage counts.

Run on your own machine. Every source below is blocked from the research
sandbox; all of them are open (or free-key) from a normal network.

    python3 enumerate_mcp.py registry     # complete server list, all ecosystems
    python3 enumerate_mcp.py smithery     # adds real connection counts
    python3 enumerate_mcp.py docker       # ~245 images with real pull counts
    #   optional: export DOCKERHUB_TOKEN=... to page past Docker's anonymous cap
    python3 enumerate_mcp.py npmdl        # npm download counts
    python3 enumerate_mcp.py pypisql      # prints the BigQuery SQL to run
    python3 enumerate_mcp.py npmtotal     # npm population denominator
    python3 enumerate_mcp.py compare      # cross-ecosystem concentration table

Run these as SEPARATE commands, one per line. Chaining them on a single
line passes the extra words to argv and only the first one executes.

Each step writes a JSON file and can be run independently.

WHY THIS EXISTS
    Our npm sampling frame came from the registry search API, which orders by
    score and stops paginating near 5,000. Free-text query partitioning lifts
    coverage from 63.8% to 79.5% and then plateaus (the last 20 of 100 search
    terms added 53 packages). The remaining fifth is not reachable that way.
    Everything below enumerates completely instead.
"""
import json, sys, time, urllib.request, urllib.parse, os, re

# Docker Hub and some CDNs reject unrecognised User-Agents with a bare 403.
# A browser-shaped UA plus an explicit Accept header avoids that.
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "en-US,en;q=0.9"}

def get(url, headers=None, tries=4):
    h = dict(UA); h.update(headers or {})
    last = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8", "replace")[:400]
            except Exception: pass
            last = f"HTTP {e.code} on {url}\n      response: {body}"
            if e.code in (429, 502, 503): time.sleep(2 ** a * 2); continue
            if e.code in (401, 403):
                raise RuntimeError(f"{last}\n      403/401 usually means the User-Agent or an auth "
                                   f"header was rejected, not that the endpoint is gone.")
            raise RuntimeError(last)
        except urllib.error.URLError as e:
            last = f"network error on {url}: {e.reason}"
            if a == tries - 1: raise RuntimeError(last)
            time.sleep(1.5 ** a)
        except Exception as e:
            last = f"{type(e).__name__} on {url}: {e}"
            if a == tries - 1: raise RuntimeError(last)
            time.sleep(1.5 ** a)


def gini(vals):
    v = sorted(x for x in vals if x is not None)
    n, tot = len(v), sum(v)
    if not n or not tot: return None
    return round((2*sum((i+1)*x for i, x in enumerate(v)))/(n*tot) - (n+1)/n, 4)

def concentration(vals, label):
    v = sorted((x for x in vals if x is not None), reverse=True)
    tot = sum(v) or 1
    print(f"\n  === {label} ===")
    print(f"  n = {len(v)}   total = {tot:,}   GINI = {gini(v)}")
    for k in (1, 5, 10, 25, 50, 100):
        if k <= len(v): print(f"    top {k:3d} share: {100*sum(v[:k])/tot:5.1f}%")
    print(f"    zero-usage entries: {sum(1 for x in v if x == 0)}")
    print(f"    median: {v[len(v)//2]:,}")
    return {"label": label, "n": len(v), "total": tot, "gini": gini(v),
            "top1": round(100*v[0]/tot,1) if v else 0,
            "top5": round(100*sum(v[:5])/tot,1), "top10": round(100*sum(v[:10])/tot,1),
            "median": v[len(v)//2] if v else 0}

# ---------------------------------------------------------------- registry
def registry():
    """Official MCP registry. The only source with clean npm/PyPI/OCI join keys.

    GOTCHAS
      * limit is capped at 100; 200 returns HTTP 422.
      * There is NO total count and NO bulk export. Pagination is mandatory.
      * version=latest is REQUIRED. Without it you get every historical
        version of every server and overcount badly.
      * The registry asks aggregators to poll no more than once per hour.
    """
    out, cursor, page = [], None, 0
    while True:
        u = "https://registry.modelcontextprotocol.io/v0.1/servers?limit=100&version=latest"
        if cursor: u += "&cursor=" + urllib.parse.quote(cursor)
        d = get(u)
        servers = d.get("servers", [])
        if not servers: break
        out.extend(servers)
        page += 1
        cursor = (d.get("metadata") or {}).get("nextCursor")
        if page % 10 == 0: print(f"  {len(out)} servers ...", flush=True)
        if not cursor: break
        time.sleep(0.35)
    # flatten the join keys
    rows = []
    for s in out:
        srv = s.get("server", s)
        pkgs = srv.get("packages") or []
        if not pkgs:
            rows.append({"name": srv.get("name"), "version": srv.get("version"),
                         "ecosystem": "remote-only", "identifier": None,
                         "repository": (srv.get("repository") or {}).get("url")})
        for p in pkgs:
            rows.append({"name": srv.get("name"), "version": srv.get("version"),
                         "ecosystem": p.get("registryType"),
                         "identifier": p.get("identifier"),
                         "pkg_version": p.get("version"),
                         "sha256": p.get("fileSha256"),
                         "repository": (srv.get("repository") or {}).get("url")})
    json.dump(rows, open("mcp_registry.json", "w"), indent=1)
    eco = {}
    for r in rows: eco[r["ecosystem"]] = eco.get(r["ecosystem"], 0) + 1
    print(f"\n  {len(out)} servers -> {len(rows)} package rows")
    print(f"  by ecosystem: {eco}")
    print("  wrote mcp_registry.json")

# ---------------------------------------------------------------- smithery
def smithery():
    """Smithery exposes useCount: actual connection counts, not a download proxy.
    This is the most direct usage metric available anywhere.

    Free key: https://smithery.ai/account/api-keys  -> export SMITHERY_API_KEY=...
    Pass seed= for deterministic paging, or concurrent pages duplicate rows.
    """
    key = os.environ.get("SMITHERY_API_KEY")
    if not key:
        print("  set SMITHERY_API_KEY first (free at smithery.ai/account/api-keys)"); return
    out, page = [], 1
    while True:
        u = f"https://api.smithery.ai/servers?page={page}&pageSize=100&seed=42"
        d = get(u, {"Authorization": f"Bearer {key}"})
        rows = d.get("servers", [])
        out.extend(rows)
        pg = d.get("pagination", {})
        if page == 1: print(f"  totalCount reported: {pg.get('totalCount')}")
        if page >= pg.get("totalPages", 0) or not rows: break
        page += 1
        if page % 10 == 0: print(f"  {len(out)} ...", flush=True)
        time.sleep(0.3)
    json.dump(out, open("mcp_smithery.json", "w"), indent=1)
    used = sorted(out, key=lambda s: -(s.get("useCount") or 0))
    st = concentration([s.get("useCount") or 0 for s in out], "Smithery (actual connection counts)")
    json.dump(st, open("conc_smithery.json", "w"))
    print("\n  top 5:", [(s.get("qualifiedName") or s.get("displayName"), s.get("useCount")) for s in used[:5]])
    print("  wrote mcp_smithery.json, conc_smithery.json")

# ---------------------------------------------------------------- docker
def docker():
    """Docker Hub mcp/ namespace with real pull counts.

    ANONYMOUS PAGINATION IS CAPPED AT PAGE 1:
        {"message":"pagination offset too large for anonymous requests"}
    So we ask for the TOP 100 BY PULL COUNT instead of the first 100
    alphabetically. Concentration lives in the head, so the top 100 of ~245
    carries essentially all the mass, and we can bound the rest exactly:
    every unseen repo has pull_count <= the 100th value.

    Set DOCKERHUB_TOKEN (a free Personal Access Token) to page the full
    namespace and remove the bounds entirely.
    """
    tok = os.environ.get("DOCKERHUB_TOKEN")
    hdr = {"Authorization": f"Bearer {tok}"} if tok else None
    base = "https://hub.docker.com/v2/repositories/mcp/"
    out, total_reported, truncated = [], None, False

    # sorted descending by pulls so page 1 is the head of the distribution
    for params in ("?page_size=100&ordering=-pull_count", "?page_size=100"):
        try:
            d = get(base + params, hdr)
            out = d.get("results", [])
            total_reported = d.get("count")
            nxt = d.get("next")
            break
        except Exception as e:
            print(f"  {params} -> {e}")
    if not out:
        print("\n  Could not reach Docker Hub at all. Sanity check:")
        print("    curl -s 'https://hub.docker.com/v2/repositories/mcp/?page_size=2' | head -c 300")
        return

    # try to page further; anonymous will 403, that is expected and fine
    while nxt:
        try:
            d = get(nxt, hdr)
            out.extend(d.get("results", []))
            nxt = d.get("next")
            time.sleep(0.3)
        except Exception as e:
            truncated = True
            print(f"  pagination stopped after {len(out)} of {total_reported} repos")
            print(f"    ({str(e).splitlines()[1].strip() if len(str(e).splitlines())>1 else e})")
            print("    set DOCKERHUB_TOKEN to page the rest; bounding the tail instead.\n")
            break

    out.sort(key=lambda r: -(r.get("pull_count") or 0))
    json.dump(out, open("mcp_docker.json", "w"), indent=1)
    v = [r.get("pull_count") or 0 for r in out]
    seen, floor_val = sum(v), (v[-1] if v else 0)

    if truncated and total_reported:
        missing = total_reported - len(out)
        lo, hi = seen, seen + missing * floor_val      # every unseen repo <= floor_val
        print(f"  === Docker Hub mcp/ (pull counts, top {len(out)} of {total_reported}) ===")
        print(f"  observed pulls: {seen:,}   unseen repos: {missing} (each <= {floor_val:,})")
        print(f"  true total is between {lo:,} and {hi:,}\n")
        for k in (1, 5, 10, 25, 50):
            if k <= len(v):
                sk = sum(v[:k])
                print(f"    top {k:3d} share: {100*sk/hi:5.1f}% to {100*sk/lo:5.1f}%")
        g_obs = gini(v)
        print(f"\n  Gini over the observed head only: {g_obs}")
        print("  (the true Gini is HIGHER, since the unseen tail is all at or below the floor)")
        st = {"label": f"Docker Hub mcp/ (top {len(out)} of {total_reported}, bounded)",
              "n": total_reported, "total": hi, "gini": g_obs,
              "top1": round(100*v[0]/hi,1), "top5": round(100*sum(v[:5])/hi,1),
              "top10": round(100*sum(v[:10])/hi,1), "median": v[len(v)//2]}
    else:
        st = concentration(v, "Docker Hub mcp/ namespace (pull counts)")

    json.dump(st, open("conc_docker.json", "w"))
    print("\n  top 5:", [(r["name"], r["pull_count"]) for r in out[:5]])
    print("  wrote mcp_docker.json, conc_docker.json")

# ---------------------------------------------------------------- npm counts
def npmdl(names=None):
    """npm download counts.

    THE TRAP: scoped packages hard-fail with HTTP 400 in a bulk query.
    npm's own docs say bulk does not support them. A large share of MCP
    packages are scoped, so a naive bulk loop silently loses most of them.
    Split the list.
    """
    if names is None:
        rows = json.load(open("mcp_registry.json"))
        names = sorted({r["identifier"] for r in rows if r.get("ecosystem") == "npm" and r.get("identifier")})
    unscoped = [n for n in names if not n.startswith("@")]
    scoped   = [n for n in names if n.startswith("@")]
    print(f"  {len(names)} npm packages: {len(unscoped)} unscoped (batched 128), {len(scoped)} scoped (one each)")
    out = {}
    for i in range(0, len(unscoped), 128):
        chunk = unscoped[i:i+128]
        try:
            d = get("https://api.npmjs.org/downloads/point/last-month/" + ",".join(chunk))
            for k, v in d.items():
                if isinstance(v, dict): out[k] = v.get("downloads", 0)
        except Exception as e:
            print(f"    batch {i} failed: {type(e).__name__}")
        time.sleep(0.25)
    for j, n in enumerate(scoped):
        try:
            d = get("https://api.npmjs.org/downloads/point/last-month/" + urllib.parse.quote(n, safe="@/"))
            out[n] = d.get("downloads", 0)
        except Exception:
            out[n] = 0
        if j % 100 == 99: print(f"    scoped {j+1}/{len(scoped)}", flush=True)
        time.sleep(0.15)
    json.dump(out, open("mcp_npm_downloads.json", "w"), indent=1)
    st = concentration(list(out.values()), "npm MCP servers (monthly downloads)")
    json.dump(st, open("conc_npm.json", "w"))
    print("  wrote mcp_npm_downloads.json, conc_npm.json")

# ---------------------------------------------------------------- pypi sql
def pypisql():
    """Cost is driven by DAYS SPANNED and COLUMNS TOUCHED, not by how many
    projects you ask for. One query covers the whole population for the same
    price as one project. Roughly 40-50 GB scanned for 30 days, well inside
    the 1 TiB/month free tier. Dry-run first."""
    try:
        rows = json.load(open("mcp_registry.json"))
        projects = sorted({re.sub(r"[-_.]+", "-", r["identifier"].lower())
                           for r in rows if r.get("ecosystem") == "pypi" and r.get("identifier")})
    except FileNotFoundError:
        projects = []
    print(f"""
-- Run: bq query --use_legacy_sql=false --dry_run < q.sql   (check bytes first)
-- Then drop --dry_run.
-- installer.name='pip' excludes bandersnatch and other mirror traffic.
-- file.project is PEP-503 normalised, so normalise your names to match
-- (lowercase; runs of - _ . collapsed to a single -). {len(projects)} projects found.

SELECT file.project AS project, COUNT(*) AS downloads
FROM `bigquery-public-data.pypi.file_downloads`
WHERE DATE(timestamp) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
                          AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND details.installer.name = 'pip'
GROUP BY project
ORDER BY downloads DESC;

-- Grouping over ALL projects costs the same as filtering to yours, and hands
-- you the denominator for free. Filter locally against this list:
""")
    if projects: print("-- " + json.dumps(projects[:40]) + (" ... " if len(projects) > 40 else ""))

# ---------------------------------------------------------------- npm total
def npmtotal():
    """Population denominator. No auth. Note _all_docs lost include_docs and
    skip in the 2025 migration: paginate with startkey, not offset."""
    d = get("https://replicate.npmjs.com/registry/_all_docs?limit=1")
    print(f"  npm total packages: {d.get('total_rows'):,}")


# ---------------------------------------------------------------- compare
def compare():
    """Cross-ecosystem concentration table. Run after docker / smithery / npmdl.
    PyPI baseline from our own measurement is included for reference."""
    import glob
    rows = [{"label": "PyPI MCP servers (measured 2026-09-07)", "n": 221,
             "total": 203446, "gini": 0.9611, "top1": 63.6, "top5": 88.7,
             "top10": 93.0, "median": 24}]
    for f in sorted(glob.glob("conc_*.json")):
        try: rows.append(json.load(open(f)))
        except Exception: pass
    print(f"\n  {'source':46s} {'n':>6s} {'gini':>7s} {'top1':>7s} {'top5':>7s} {'top10':>7s} {'median':>9s}")
    print("  " + "-"*94)
    for r in rows:
        print(f"  {r['label'][:46]:46s} {r['n']:6d} {r['gini']:7.4f} {r['top1']:6.1f}% {r['top5']:6.1f}% {r['top10']:6.1f}% {r['median']:9,}")
    g = [r["gini"] for r in rows if r.get("gini")]
    if len(g) > 1:
        print(f"\n  Gini range across {len(g)} independent ecosystems and usage metrics: {min(g):.4f} to {max(g):.4f}")
        print("  If all are above ~0.9, the concentration result generalises and")
        print("  package-weighted sampling is the wrong unit of analysis everywhere.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "registry"
    {"registry": registry, "smithery": smithery, "docker": docker,
     "npmdl": npmdl, "pypisql": pypisql, "npmtotal": npmtotal,
     "compare": compare}[cmd]()
