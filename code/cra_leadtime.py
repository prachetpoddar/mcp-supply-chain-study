#!/usr/bin/env python3
"""
Is abandonment visible before it happens? See PREREGISTRATION-3.md.

VERSION 2. The version 1 collector produced a series that did not survive the
project's adversarial gate, and the third amendment in PREREGISTRATION-3.md
records why. The three faults that forced this rewrite:

    1. It counted pull requests as issues. The issues endpoint returns both, the
       collector detected PRs, stored the count, and never subtracted it. 55% of
       cohort A's "opened" and 56% of cohort B's were pull requests.
    2. It fetched with `since`, which filters on updated_at and has no upper
       bound, then sorted ascending by creation date and stopped at 1000 items.
       For a live repository the result set held years of post-anchor activity,
       so the cap deleted the LATEST bins first. 32.6% of controls truncated
       against 1.4% of cases, which manufactured most of the control arm's
       apparent decline (-23.0% overall, -7.0% among untruncated controls).
    3. It never excluded bots, despite writing a bots_excluded field, which was
       zero in every record and read by nothing.

    And bin t-1 is the release month by construction, because the anchor IS the
    last release. It is dropped here permanently rather than corrected.

RUNS ON YOUR MACHINE, NOT IN THE STUDY SANDBOX

        read -s GITHUB_TOKEN && export GITHUB_TOKEN
        python3 cra_leadtime.py cohorts        # pick cohorts, resolve repositories
        python3 cra_leadtime.py fetch 3000     # resumable, honours rate limits
        python3 cra_leadtime.py report

    The token is read from the environment and is never written to any output
    file, any log line, or the state cache.

COLLECTION AND ANALYSIS STAY APART
    `fetch` gathers monthly bins and knows nothing about the hypothesis.
    `report` applies the rules fixed in the pre-registration. A collector that
    also decided the answer could be tuned against the answer.

EVERY DROP IS COUNTED
    Repositories that 404, that cannot be completed within the page cap, that
    fail the eligibility floor, or that carry no issues at all are each counted
    by arm and written into the output file, not merely printed.
"""
import collections, datetime as dt, json, math, os, random, re, statistics, sys, time
import urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
COMP = os.path.join(DATA, "cra_components.json")
STALENESS = os.path.join(DATA, "cra_staleness.json")
COHORTS = os.path.join(DATA, "leadtime_cohorts.json")
STATE = os.path.join(DATA, "leadtime_state.json")
REPOAGE = os.path.join(DATA, "leadtime_repo_ages.json")
OUT = os.path.join(DATA, "cra_leadtime.json")

STALE_DAYS, FRESH_DAYS, BINS = 730, 180, 24
GH = "https://api.github.com"

# Records written by the v1 collector used different fetch semantics and counted
# pull requests. They are not comparable and are purged rather than reused.
SCHEMA = 2

# A repository needing more than this many pages of history to reach its window
# start is EXCLUDED rather than reported partially. The v1 cap silently returned
# a partial series instead, and the partial series was the result.
PAGE_CAP = 60

# Eligibility floor, fixed in the third amendment: mean issues opened per month
# across the BASELINE half of the window only (t-24..t-13), so the threshold
# cannot be met or missed by the behaviour the study is looking for.
ELIGIBLE_RATE = 0.5
BASELINE_BINS = list(range(24, 12, -1))     # t-24 .. t-13
COMPARE_BINS = list(range(6, 1, -1))        # t-6 .. t-2, t-1 excluded
ANALYSIS_BINS = list(range(24, 1, -1))      # t-24 .. t-2, t-1 excluded everywhere
ADEQUACY_FLOOR = 150
BOOTSTRAP = 4000
BOOT_SEED = 20260909


def token():
    t = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not t:
        print("GITHUB_TOKEN is not set. Run:  read -s GITHUB_TOKEN && export GITHUB_TOKEN")
        sys.exit(1)
    return t


def preflight():
    """Prove the credential works before spending the run on it."""
    d, e = gh("/rate_limit")
    if e:
        print(f"\nGitHub rejected the token ({e}). Nothing has been collected.\n"
              "  401 means the value is wrong, expired, or was pasted with extra\n"
              "  characters. Check it without revealing it:\n"
              "    curl -sS -o /dev/null -w '%{http_code}\\n' \\\n"
              "      -H \"Authorization: Bearer $GITHUB_TOKEN\" https://api.github.com/rate_limit\n"
              "  200 means good, 401 means the token itself is the problem.")
        sys.exit(1)
    core = ((d or {}).get("resources") or {}).get("core") or {}
    print(f"token accepted: {core.get('remaining', '?')} of {core.get('limit', '?')} "
          f"requests remaining this hour")
    return int(core.get("remaining", 0) or 0)


def gh(path, params=None):
    url = GH + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token(),
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcp-supply-chain-study/0.8 (academic research)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                # Read the body BEFORE any sleep. Sleeping inside the `with` and
                # then reading meant a long rate-limit wait could drop the socket,
                # fail the read, land in the generic retry, and re-issue the very
                # request the sleep had just paid for.
                remaining = int(r.headers.get("X-RateLimit-Remaining", "9999"))
                reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                body = json.load(r)
            if remaining < 20:
                wait = max(0, reset - int(time.time())) + 5
                print(f"  rate limit low, sleeping {wait}s", flush=True)
                time.sleep(wait)
            return body, None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                reset = int(e.headers.get("X-RateLimit-Reset", "0"))
                wait = max(30, reset - int(time.time()) + 5)
                print(f"  throttled, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            return None, f"HTTP{e.code}"
        except Exception as e:
            if attempt == 3:
                return None, type(e).__name__
            time.sleep(2 ** attempt)
    return None, "retries"


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


EXCLUDE_REPOS = {"definitelytyped/definitelytyped"}
REPO_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/#?]+?)(?:\.git)?/?$", re.I)


def repo_of(name):
    url = "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "mcp-supply-chain-study/0.8"}), timeout=30) as r:
            d = json.load(r)
    except Exception:
        return None
    vs = list((d.get("versions") or {}).values())
    sources = [d.get("repository")]
    if vs:
        sources.append(vs[-1].get("repository"))
    for src in sources:
        u = src.get("url") if isinstance(src, dict) else src
        if isinstance(u, str):
            m = REPO_RE.search(u.strip())
            if m:
                return f"{m.group(1)}/{m.group(2)}"
    return None


def repo_ages(repos):
    """created_at per repository, cached. A repository must predate its window."""
    cache = json.load(open(REPOAGE)) if os.path.exists(REPOAGE) else {}
    todo = [r for r in repos if r not in cache]
    if todo:
        print(f"fetching creation dates for {len(todo)} repositories")
    for i, r in enumerate(todo):
        d, e = gh(f"/repos/{r}")
        cache[r] = {"created_at": (d or {}).get("created_at"), "error": e}
        if i % 50 == 0:
            json.dump(cache, open(REPOAGE, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
    json.dump(cache, open(REPOAGE, "w"))
    return cache


def cohorts():
    comp = json.load(open(COMP))
    nodes = comp["nodes"]
    age = {r["name"]: r["age"] for r in nodes if r["age"] is not None}
    ing = collections.Counter(r["name"] for r in nodes)
    as_of = ts(json.load(open(STALENESS))["as_of"])
    latest = {n: (as_of - dt.timedelta(days=a)).strftime("%Y-%m-%dT%H:%M:%SZ")
              for n, a in age.items()}
    print(f"anchors derived from as_of {as_of.strftime('%Y-%m-%d')} in cra_staleness.json")

    A = sorted(n for n, a in age.items() if a > STALE_DAYS)
    B = sorted(n for n, a in age.items() if a <= FRESH_DAYS)
    print(f"stale pool {len(A)}, fresh pool {len(B)}")

    def decile(n):
        c = ing[n]
        return 0 if c <= 1 else 1 if c <= 2 else 2 if c <= 4 else 3 if c <= 9 else 4 if c <= 49 else 5

    pool = collections.defaultdict(list)
    for n in B:
        pool[decile(n)].append(n)
    for k in pool:
        pool[k].sort(key=lambda x: ing[x])

    out = {"stale": {}, "fresh": {}, "unresolved": [], "schema": SCHEMA,
           "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    print("phase 1: resolving repositories from the registry")
    case_repo, fresh_repo = {}, {}
    for i, n in enumerate(A):
        r = repo_of(n)
        if r:
            case_repo[n] = r
        else:
            out["unresolved"].append(n)
        if i % 50 == 0:
            print(f"  cases {i}/{len(A)}", flush=True)
        time.sleep(0.05)
    for i, n in enumerate(B):
        r = repo_of(n)
        if r:
            fresh_repo[n] = r
        if i % 100 == 0:
            print(f"  controls {i}/{len(B)}", flush=True)
        time.sleep(0.05)
    print(f"  cases with a repository {len(case_repo)}, controls {len(fresh_repo)}")

    print("phase 2: repository creation dates")
    ages = repo_ages(sorted(set(case_repo.values()) | set(fresh_repo.values())))

    def born(repo):
        """None means UNKNOWN, which is treated as failing the constraint.

        v1 wrote `if b and b > need` for cases and `if cb is None or cb > need`
        for controls, so an unknown creation date KEPT a case and REJECTED a
        control. Lookups fail most often for deleted or renamed repositories,
        which sit disproportionately in the case arm, so the age constraint was
        being enforced on one arm only.
        """
        c = (ages.get(repo) or {}).get("created_at")
        return ts(c) if c else None

    print("phase 3: matching, both arms required to predate their own window")
    used = set()
    dropped_case_young, dropped_case_unknown, dropped_no_control = [], [], []
    for n, repo in case_repo.items():
        anchor = latest.get(n)
        need = ts(anchor) - dt.timedelta(days=30 * BINS)
        b = born(repo)
        if b is None:
            dropped_case_unknown.append(n)
            continue
        if b > need:
            dropped_case_young.append(n)
            continue
        cand = sorted((c for c in pool[decile(n)] if c not in used and c in fresh_repo),
                      key=lambda c: abs(ing[c] - ing[n]))
        matched = None
        for c in cand:
            cb = born(fresh_repo[c])
            if cb is None or cb > need:
                continue
            matched = c
            break
        if matched is None:
            dropped_no_control.append(n)
            continue
        used.add(matched)
        out["stale"][n] = {"repo": repo, "anchor": anchor, "ingestion": ing[n]}
        out["fresh"][matched] = {"repo": fresh_repo[matched], "anchor": anchor,
                                 "ingestion": ing[matched], "matched_to": n}

    out["dropped_case_repo_younger_than_window"] = sorted(dropped_case_young)
    out["dropped_case_repo_age_unknown"] = sorted(dropped_case_unknown)
    out["dropped_no_eligible_control"] = sorted(dropped_no_control)
    print(f"  cases kept {len(out['stale'])}, dropped for own repo age "
          f"{len(dropped_case_young)}, dropped for unknown repo age "
          f"{len(dropped_case_unknown)}, dropped for no eligible control "
          f"{len(dropped_no_control)}")

    def collapse(arm):
        by = collections.defaultdict(list)
        for n, v in arm.items():
            if v["repo"].lower() in EXCLUDE_REPOS:
                continue
            by[v["repo"]].append((n, v))
        out2 = {}
        for repo, members in by.items():
            anchor = max(v["anchor"] for _, v in members)
            out2[repo] = {"repo": repo, "anchor": anchor,
                          "ingestion": sum(v["ingestion"] for _, v in members),
                          "ingestion_max": max(v["ingestion"] for _, v in members),
                          "packages": sorted(n for n, _ in members)}
        return out2

    out["stale_by_repo"] = collapse(out["stale"])
    out["fresh_by_repo"] = collapse(out["fresh"])
    out["excluded_repos"] = sorted(EXCLUDE_REPOS)

    # POST-COLLAPSE BALANCE, written to the file rather than printed and lost.
    # Matching is package-to-package; summing ingestion across a repository's
    # packages does not inherit that balance, and v1 never checked whether it
    # had. It had not: cases median 5 / p90 70, controls median 8 / p90 168.
    bal = {}
    for arm in ("stale_by_repo", "fresh_by_repo"):
        xs = sorted(v["ingestion"] for v in out[arm].values())
        ps = sorted(len(v["packages"]) for v in out[arm].values())
        bal[arm] = {"n": len(xs), "median": xs[len(xs) // 2] if xs else None,
                    "mean": round(statistics.mean(xs), 2) if xs else None,
                    "p90": xs[int(.9 * len(xs))] if xs else None,
                    "max": max(xs) if xs else None,
                    "packages_per_repo_mean": round(statistics.mean(ps), 2) if ps else None,
                    "multi_package_share": round(sum(1 for p in ps if p > 1) / len(ps), 3) if ps else None}
    out["post_collapse_balance"] = bal
    json.dump(out, open(COHORTS, "w"), indent=1)

    print("\nREPOSITORY level, which is the unit used from here:")
    for arm in ("stale_by_repo", "fresh_by_repo"):
        b = bal[arm]
        print(f"  {arm:15s} n={b['n']:4d}  ingestion median {b['median']} "
              f"mean {b['mean']} p90 {b['p90']} max {b['max']}  "
              f"multi-package share {b['multi_package_share']}")
    print("  cross-arm LEVEL comparisons are not interpretable unless these agree")


def month_bins(anchor):
    a = ts(anchor)
    edges = []
    for k in range(BINS, 0, -1):
        start = a - dt.timedelta(days=30 * k)
        edges.append((f"t-{k}", start, start + dt.timedelta(days=30)))
    return edges, a


def is_bot(row):
    u = row.get("user") or {}
    return u.get("type") == "Bot" or str(u.get("login", "")).endswith("[bot]")


def fetch(budget):
    preflight()
    co = json.load(open(COHORTS))
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}

    # Purge v1 records outright. Their bins counted pull requests, included no
    # bot exclusion, and were collected over a window with no upper bound.
    old = [k for k, v in st.items() if v.get("schema") != SCHEMA]
    for k in old:
        del st[k]
    if old:
        print(f"purging {len(old)} records collected by the v1 collector "
              f"(different fetch semantics, not comparable)")

    poisoned = [k for k, v in st.items()
                if v.get("error") in ("HTTP401", "HTTP403", "retries")]
    for k in poisoned:
        del st[k]
    if poisoned:
        print(f"clearing {len(poisoned)} entries that failed on credentials or retries")

    stale_anchor = [f"{arm}|{repo}" for arm in ("stale_by_repo", "fresh_by_repo")
                    for repo, v in co.get(arm, {}).items()
                    if f"{arm}|{repo}" in st and st[f"{arm}|{repo}"].get("anchor") != v["anchor"]]
    for k in stale_anchor:
        del st[k]
    if stale_anchor:
        print(f"clearing {len(stale_anchor)} entries whose anchor changed since collection")

    todo = [(arm, n, v) for arm in ("stale_by_repo", "fresh_by_repo")
            for n, v in co[arm].items() if f"{arm}|{n}" not in st]
    print(f"{len(todo)} repositories to collect")
    t0 = time.time()
    for i, (arm, n, v) in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        edges, anchor = month_bins(v["anchor"])
        w_start = anchor - dt.timedelta(days=30 * BINS)

        # Walk by updated_at DESCENDING and stop once the page's oldest item was
        # last touched before the window opens. Every issue created in the window
        # and every issue closed in the window has updated_at >= w_start, so this
        # is a complete superset for both measures with a definite stopping rule.
        # v1 used `since`, which is bounded below and NOT above, so a live
        # repository's post-anchor years entered the result set and the item cap
        # deleted the newest bins.
        rows, page, err, incomplete = [], 1, None, False
        while True:
            d, e = gh(f"/repos/{v['repo']}/issues",
                      {"state": "all", "sort": "updated", "direction": "desc",
                       "per_page": 100, "page": page})
            if e:
                err = e
                break
            if not d:
                break
            rows.extend(d)
            if ts(d[-1]["updated_at"]) < w_start:
                break
            if len(d) < 100:
                break
            page += 1
            if page > PAGE_CAP:
                incomplete = True
                break

        rec = {"schema": SCHEMA, "repo": v["repo"], "anchor": v["anchor"],
               "error": err, "pages": page, "incomplete": bool(err is None and incomplete),
               "n_rows": len(rows), "n_pr": 0, "n_bot": 0, "bins": {}}
        if not err:
            keep = []
            for r in rows:
                if r.get("pull_request"):
                    rec["n_pr"] += 1
                    continue
                if is_bot(r):
                    rec["n_bot"] += 1
                    continue
                keep.append(r)
            for label, s, e2 in edges:
                op = [r for r in keep if s <= ts(r["created_at"]) < e2]
                cl = [r for r in keep if r.get("closed_at") and s <= ts(r["closed_at"]) < e2]
                rec["bins"][label] = {"opened": len(op), "closed": len(cl),
                                      "issue_numbers": [r["number"] for r in op]}
        st[f"{arm}|{n}"] = rec
        if i % 10 == 0:
            json.dump(st, open(STATE, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
    json.dump(st, open(STATE, "w"))
    ok = sum(1 for v in st.values() if not v.get("error") and not v.get("incomplete"))
    inc = sum(1 for v in st.values() if v.get("incomplete"))
    print(f"\ncomplete {ok} of {len(st)}; incomplete (page cap, excluded) {inc}; "
          f"errors: {collections.Counter(v['error'] for v in st.values() if v.get('error'))}")
    prs = sum(v.get("n_pr", 0) for v in st.values())
    bots = sum(v.get("n_bot", 0) for v in st.values())
    print(f"excluded during counting: {prs} pull requests, {bots} bot-authored items")


def boot_ci(xs, f, seed, B=BOOTSTRAP):
    if len(xs) < 8:
        return (None, None)
    rnd = random.Random(seed)
    s = sorted(f(rnd.choices(xs, k=len(xs))) for _ in range(B))
    return (round(s[int(.025 * B)], 3), round(s[int(.975 * B)], 3))



RETRACTION_NOTE = [
    "",
    "RETRACTED, see the fifth amendment to PREREGISTRATION-3. The within-repository",
    "ratio below is an artifact of the eligibility rule, not a result. Eligibility is",
    "imposed on the ratio's own denominator, and cohort A is selected from far deeper",
    "in its tail (population median 0.083 issues/month) than cohort B (2.08), so",
    "regression to the mean produces this difference with no decay present at all.",
    "A stationary null with the observed population medians returns A 0.867, B 0.997,",
    "difference -0.130, interval excluding zero. Printed only to keep the retracted",
    "value on the record.",
]

def report():
    st = json.load(open(STATE))
    co = json.load(open(COHORTS))
    drops = {a: collections.Counter() for a in ("stale_by_repo", "fresh_by_repo")}
    arms = collections.defaultdict(list)
    for arm in ("stale_by_repo", "fresh_by_repo"):
        for repo in co.get(arm, {}):
            v = st.get(f"{arm}|{repo}")
            if v is None:
                drops[arm]["not_collected"] += 1
            elif v.get("schema") != SCHEMA:
                drops[arm]["superseded_schema"] += 1
            elif v.get("anchor") != co[arm][repo]["anchor"]:
                drops[arm]["superseded_anchor"] += 1
            elif v.get("error"):
                drops[arm][v["error"]] += 1          # v1 dropped these with no counter
            elif v.get("incomplete"):
                drops[arm]["page_cap_incomplete"] += 1
            else:
                arms[arm].append(v)

    def rate(v, bins):
        xs = [v["bins"][f"t-{k}"]["opened"] for k in bins if f"t-{k}" in v["bins"]]
        return statistics.mean(xs) if xs else 0.0

    elig = {}
    for arm in ("stale_by_repo", "fresh_by_repo"):
        keep = []
        for v in arms[arm]:
            if rate(v, BASELINE_BINS) >= ELIGIBLE_RATE:
                keep.append(v)
            else:
                drops[arm]["below_eligibility_floor"] += 1
        elig[arm] = keep

    print("collection and eligibility, by arm")
    for arm in ("stale_by_repo", "fresh_by_repo"):
        print(f"  {arm:15s} in cohort {len(co.get(arm, {})):4d} -> collected clean "
              f"{len(arms[arm]):4d} -> eligible {len(elig[arm]):4d}   drops {dict(drops[arm])}")

    yrs = {a: sorted({v["anchor"][:4] for v in elig[a]}) for a in elig}
    print(f"  surviving anchor years  A {yrs['stale_by_repo'][:1]}..{yrs['stale_by_repo'][-1:]}  "
          f"B {yrs['fresh_by_repo'][:1]}..{yrs['fresh_by_repo'][-1:]}")

    nA, nB = len(elig["stale_by_repo"]), len(elig["fresh_by_repo"])
    adequate = nA >= ADEQUACY_FLOOR and nB >= ADEQUACY_FLOOR
    if not adequate:
        print(f"\nPOWER-LIMITED NEGATIVE. The pre-registered floor is "
              f"{ADEQUACY_FLOOR} eligible repositories per arm; cohort A has {nA} "
              f"and cohort B has {nB}.\n"
              "  No k is reported. Nothing below establishes a finding. The series is\n"
              "  printed as description of an instrument that lacks the resolution to\n"
              "  answer the question on this population, which is itself the result.")

    print(f"\nissues only, pull requests and bots excluded, bin t-1 dropped "
          f"(the release month, by construction)")
    print(f"{'bin':>6} {'A opened':>9} {'B opened':>9} {'A closed':>9} {'B closed':>9}")
    series = {}
    for k in ANALYSIS_BINS:
        lab = f"t-{k}"
        row = {}
        for arm in ("stale_by_repo", "fresh_by_repo"):
            op = [v["bins"][lab]["opened"] for v in elig[arm] if lab in v["bins"]]
            cl = [v["bins"][lab]["closed"] for v in elig[arm] if lab in v["bins"]]
            row[arm] = {"n": len(op),
                        "opened_mean": round(statistics.mean(op), 3) if op else None,
                        "opened_median": statistics.median(op) if op else None,
                        "closed_mean": round(statistics.mean(cl), 3) if cl else None,
                        "opened_ci": boot_ci(op, statistics.mean, BOOT_SEED + k)}
        series[lab] = row
        a, b = row["stale_by_repo"], row["fresh_by_repo"]
        print(f"{lab:>6} {a['opened_mean'] or 0:>9.2f} {b['opened_mean'] or 0:>9.2f} "
              f"{a['closed_mean'] or 0:>9.2f} {b['closed_mean'] or 0:>9.2f}")

    # Within-repository change, each repository against its own baseline. Level
    # differences between the arms cancel, which matters because the matching
    # does not survive the collapse to repositories. Recorded as EXPLORATORY:
    # it was devised after the v1 series was seen. See the third amendment.
    def ratio(v):
        e, l = rate(v, BASELINE_BINS), rate(v, COMPARE_BINS)
        return None if e < ELIGIBLE_RATE else (l + 0.5) / (e + 0.5)

    expl = {}
    for line in RETRACTION_NOTE:
        print(line)
    for arm in ("stale_by_repo", "fresh_by_repo"):
        xs = [x for x in (ratio(v) for v in elig[arm]) if x is not None]
        lo, hi = boot_ci(xs, statistics.median, BOOT_SEED + 991)
        expl[arm] = {"n": len(xs),
                     "median": round(statistics.median(xs), 3) if xs else None,
                     "ci": [lo, hi],
                     "share_below_1": round(sum(1 for x in xs if x < 1) / len(xs), 3) if xs else None}
        print(f"  {arm:15s} n={len(xs):4d} median {expl[arm]['median']} "
              f"95% CI [{lo}, {hi}] share below 1 {expl[arm]['share_below_1']}")
    a = [x for x in (ratio(v) for v in elig["stale_by_repo"]) if x is not None]
    b = [x for x in (ratio(v) for v in elig["fresh_by_repo"]) if x is not None]
    diff_ci = (None, None)
    if len(a) >= 8 and len(b) >= 8:
        rnd = random.Random(BOOT_SEED + 7)
        s = sorted(statistics.median(rnd.choices(a, k=len(a))) -
                   statistics.median(rnd.choices(b, k=len(b))) for _ in range(BOOTSTRAP))
        diff_ci = (round(s[int(.025 * BOOTSTRAP)], 3), round(s[int(.975 * BOOTSTRAP)], 3))
        d = statistics.median(a) - statistics.median(b)
        crosses = diff_ci[0] < 0 < diff_ci[1]
        print(f"  difference A - B {d:+.3f}  95% CI [{diff_ci[0]:+.3f}, {diff_ci[1]:+.3f}]  "
              f"{'CROSSES ZERO' if crosses else 'excludes zero'}")
        # leave-one-repository-out on the arm carrying the result
        infl = []
        for i in range(len(a)):
            infl.append(statistics.median(a[:i] + a[i + 1:]) - statistics.median(b))
        print(f"  leave-one-repository-out range of the difference: "
              f"[{min(infl):+.3f}, {max(infl):+.3f}]")
        expl["loo_range"] = [round(min(infl), 3), round(max(infl), 3)]
    expl["difference_ci"] = list(diff_ci)

    json.dump({"schema": SCHEMA, "unit": "repository", "series": series,
               "bins_analysed": [f"t-{k}" for k in ANALYSIS_BINS],
               "t_minus_1": "dropped: the anchor is the last release, so t-1 is the "
                            "release month in cohort A only",
               "measures_reported": ["issues opened", "issues closed"],
               "measures_excluded": "pull requests and bot-authored items",
               "n_eligible": {"stale_by_repo": nA, "fresh_by_repo": nB},
               "eligibility": {"rule": "mean issues opened per month over t-24..t-13",
                               "threshold": ELIGIBLE_RATE},
               "adequacy_floor": ADEQUACY_FLOOR, "adequate": adequate,
               "drops_by_arm": {a: dict(drops[a]) for a in drops},
               "anchor_years": yrs,
               "post_collapse_balance": co.get("post_collapse_balance"),
               "retracted_within_repo_ratio": expl,
               "retraction": " ".join(RETRACTION_NOTE[1:]),
               "primary_statistic": ("measure 4, median hours to first non-author "
                                     "non-bot response, is NOT collected by this script. "
                                     "It is gated behind the adequacy floor by design: "
                                     "collecting comment timelines for a study already "
                                     "known to be power-limited spends requests on a "
                                     "question it cannot answer. No statement about the "
                                     "primary statistic is made in either direction.")},
              open(OUT, "w"), indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    os.makedirs(DATA, exist_ok=True)
    if m == "cohorts":
        preflight()
        cohorts()
    elif m == "fetch":
        fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 1800)
    else:
        report()
