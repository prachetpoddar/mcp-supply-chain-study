#!/usr/bin/env python3
"""
Docker Hub pull counts for the complete mcp/ namespace, done correctly.

VERSION HISTORY
    v1  Asked Docker Hub for the namespace sorted by pull_count. Docker Hub
        SILENTLY IGNORED the ordering parameter and returned an arbitrary
        100 of 245 repositories. The giveaway was in the output: the top
        five differed by 1.7% from each other, and `fetch` (1,715,536 pulls,
        93x the largest value returned) was absent entirely. Every number
        that run produced was wrong, including the "bounds", which assumed
        a sort that never happened.
    v2  Stopped paginating. Took the complete name list from Docker's own
        open catalog (github.com/docker/mcp-registry, 328 entries) and
        fetched each repository individually. Correct in principle, but it
        SKIPPED on HTTP 429, and Docker Hub started rate-limiting partway
        through: 55 of 328 entries were lost, running alphabetically from
        `scorecard` to `zscaler`. That block is not random with respect to
        pull count (it contains slack, stripe, sentry, terraform, time,
        sequentialthinking, semgrep, sonarqube, tavily, wolfram-alpha), so
        the resulting Gini and top-k shares were unreportable. One further
        entry, `SQLite`, failed with HTTP 400 because the catalog name has
        a capital letter and the API path is case-sensitive.
    v3  This version. Retries 429 with exponential backoff instead of
        skipping, normalises names to lowercase, saves after every response,
        and resumes.

RESUMING
    State lives in docker_state.json next to the output. Re-running picks up
    only the names not yet resolved, so an interrupted or rate-limited run
    costs nothing to finish.

    python3 docker_pulls.py docker_mcp_names.json

~330 requests on a cold start, about three minutes. A resume of the missing
55 takes well under a minute.
"""
import json, os, sys, time, urllib.request, urllib.error

UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept": "application/json, text/plain, */*"}

STATE = "docker_state.json"
BACKOFF = [4, 8, 16, 32, 60]     # seconds, per 429


def gini(vals):
    v = sorted(x for x in vals if x is not None)
    n, tot = len(v), sum(v)
    if not n or not tot:
        return None
    return round((2 * sum((i + 1) * x for i, x in enumerate(v))) / (n * tot) - (n + 1) / n, 4)


def fetch(name):
    """Return a dict, the string 'missing', or None if it could not be resolved."""
    u = f"https://hub.docker.com/v2/repositories/mcp/{name}/"
    for attempt in range(len(BACKOFF) + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                d = json.load(r)
            return {"name": name, "pull_count": d.get("pull_count", 0),
                    "star_count": d.get("star_count", 0),
                    "last_updated": d.get("last_updated")}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "missing"                      # catalogued, no image published
            if e.code in (429, 503) and attempt < len(BACKOFF):
                w = BACKOFF[attempt]
                print(f"  {name}: HTTP {e.code}, waiting {w}s", flush=True)
                time.sleep(w)
                continue
            print(f"  {name}: HTTP {e.code} (giving up)", flush=True)
            return None
        except Exception as e:
            if attempt < len(BACKOFF):
                time.sleep(BACKOFF[attempt])
                continue
            print(f"  {name}: {type(e).__name__} (giving up)", flush=True)
            return None
    return None


src = sys.argv[1] if len(sys.argv) > 1 else "docker_mcp_names.json"
raw = json.load(open(src))

# Docker Hub repository paths are lowercase. The catalog is not: `SQLite`
# failed with HTTP 400 in v2 for exactly this reason. Deduplicate after
# normalising so a catalog listing both cases costs one request.
names, seen = [], set()
for n in raw:
    ln = n.strip().lower()
    if ln and ln not in seen:
        seen.add(ln)
        names.append(ln)

state = json.load(open(STATE)) if os.path.exists(STATE) else {}
todo = [n for n in names if n not in state]
print(f"catalog: {len(names)} unique names   already resolved: {len(state)}   to fetch: {len(todo)}\n")

for i, n in enumerate(todo):
    r = fetch(n)
    if r is None:
        continue                                       # leave unresolved, retry next run
    state[n] = r
    json.dump(state, open(STATE, "w"))                 # save after every response
    if (i + 1) % 25 == 0:
        print(f"  {i+1}/{len(todo)}", flush=True)
    time.sleep(0.25)

unresolved = [n for n in names if n not in state]
rows = [v for v in state.values() if v != "missing"]
missing = [k for k, v in state.items() if v == "missing"]
rows.sort(key=lambda r: -r["pull_count"])

if unresolved:
    print(f"\n  !! {len(unresolved)} names still unresolved: {unresolved[:12]}"
          f"{' ...' if len(unresolved) > 12 else ''}")
    print("  !! The run is INCOMPLETE. Re-run this script to fetch only these.")
    print("  !! Do not report the figures below until this line is gone.\n")

json.dump(rows, open("mcp_docker.json", "w"), indent=1)
v = [r["pull_count"] for r in rows]
tot = sum(v) or 1

print(f"\n  === Docker Hub mcp/ namespace (pull counts) ===")
print(f"  catalogued: {len(names)}   with a published image: {len(rows)}   "
      f"not found: {len(missing)}   unresolved: {len(unresolved)}")
print(f"  total pulls: {tot:,}   GINI = {gini(v)}")
for k in (1, 5, 10, 25, 50, 100):
    if k <= len(v):
        print(f"    top {k:3d} share: {100*sum(v[:k])/tot:5.1f}%")
print(f"    median: {v[len(v)//2]:,}    zero-pull images: {sum(1 for x in v if x == 0)}")
print(f"\n  top 10: {[(r['name'], r['pull_count']) for r in rows[:10]]}")

json.dump({"label": "Docker Hub mcp/ namespace (pull counts)",
           "complete": not unresolved,
           "n": len(rows), "catalogued": len(names),
           "no_image": len(missing), "unresolved": len(unresolved),
           "total": tot, "gini": gini(v),
           "top1": round(100 * v[0] / tot, 1),
           "top5": round(100 * sum(v[:5]) / tot, 1),
           "top10": round(100 * sum(v[:10]) / tot, 1),
           "median": v[len(v) // 2]},
          open("conc_docker.json", "w"))
print(f"\n  wrote mcp_docker.json, conc_docker.json, {STATE}")
if unresolved:
    print("  conc_docker.json is marked complete:false - do not cite it yet")
