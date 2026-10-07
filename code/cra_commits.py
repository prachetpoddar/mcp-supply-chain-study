#!/usr/bin/env python3
"""
Can a commit-rate detector warn before a package stops? See PREREGISTRATION-4.md.

WHY THIS EXISTS
    The issue-based study (PREREGISTRATION-3) closed as a power-limited negative:
    180 of 456 cohort A repositories had no issue created in the whole baseline
    year and only 95 met the eligibility floor of 150. A probe of 12 cohort A
    repositories, 7 of them with zero issue traffic, found commits in every one.
    So this asks a narrower question over a signal that has coverage.

RUNS ON YOUR MACHINE, NOT IN THE STUDY SANDBOX

        read -s GITHUB_TOKEN && export GITHUB_TOKEN
        python3 cra_commits.py fetch 3000   # resumable, honours rate limits
        python3 cra_commits.py report

    Cohorts are READ from leadtime_cohorts.json and are not re-derived here.
    The token is never written to any output file, log line, or cache.

WHAT THIS DOES NOT DO
    `fetch` bins commits and knows nothing about the detector. `report` applies
    the rule fixed in PREREGISTRATION-4 before this file was written. The
    thresholds below are transcribed from that document and are not tunable
    without amending it.

THE BOUNDED-WINDOW LESSON, CARRIED OVER
    The v1 issue collector used `since`, which filters on updated_at and has no
    upper bound, so a live repository's post-anchor years entered the result set
    and the page cap deleted the newest bins. The commits endpoint takes BOTH
    `since` and `until`, so the window is closed at both ends by the API itself.
"""
import collections, datetime as dt, json, os, random, statistics, sys, time
import urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
COHORTS = os.path.join(DATA, "leadtime_cohorts.json")
STATE = os.path.join(DATA, "leadtime_commits_state.json")
OUT = os.path.join(DATA, "cra_commits.json")
GH = "https://api.github.com"

SCHEMA = 2
BINS = 24
PAGE_CAP = 60

# --- transcribed from PREREGISTRATION-4.md AND ITS FIRST AMENDMENT ---
BASELINE_BINS = list(range(24, 12, -1))   # t-24 .. t-13
ELIGIBLE_RATE = 1.0                       # commits per month over the baseline
MIN_BASELINE_NONZERO = 4                  # of the 12 baseline bins
# Detection stops at t-10 so that no detection window (m, m+1, m+2) can read a
# bin used by the baseline. The original t-12..t-2 range read t-13 and t-14 at
# its two largest m, which let a lull INSIDE the baseline be scored as a
# maximum-lead detection on a repository that was healthy throughout detection.
DETECT_M = list(range(10, 1, -1))         # t-10 .. t-2
DETECTOR_WINDOW = 3
# Bin t-m spans [anchor-30m, anchor-30(m-1)), so its count is not known until
# anchor-30(m-1). A firing at m is actionable m-1 months out, not m.
MIN_ACTIONABLE_LEAD = 3                   # therefore requires a firing at m >= 4
FRAC_GRID = [round(0.05 * i, 2) for i in range(1, 20)]   # 0.05 .. 0.95
STRATA = [(1.0, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, 16.0), (16.0, float("inf"))]
MIN_PER_STRATUM = 20                      # per arm, for common support
TARGET_FPR = 0.10                         # calibrated, not assumed
SENS_TARGET = 0.50
ADEQUACY_FLOOR = 150
LEGACY_FRAC = 0.5                         # reported only as the artifact diagnostic
BOOTSTRAP, BOOT_SEED = 4000, 20260909

# Release automation that GitHub reports as ordinary User accounts. Fixed here by
# name so it is not tunable after seeing results. semantic-release emits one
# commit per release, and in cohort A that series terminates at the anchor by
# construction, so leaving these in lets the outcome generate the predictor.
BOT_LOGINS = {"semantic-release-bot", "renovate-bot", "greenkeeper", "greenkeeperio-bot",
              "travis-ci", "circleci", "netlify", "snyk-bot", "depfu", "pyup-bot",
              "allcontributors", "imgbot", "restyled-io", "codecov"}

PILOT = {"jonschlinkert/extend-shallow", "stephenplusplus/stream-events",
         "gtanner/qrcode-terminal", "knownasilya/cli-width",
         "inspect-js/is-weakmap", "es-shims/String.prototype.trimStart",
         "ljharb/object-keys", "nodejs/string_decoder",
         "bendrucker/postgres-date", "evanshortiss/env-var",
         "graphology/graphology", "joyent/node-verror"}


def atomic_dump(obj, path):
    """Write via a temporary file and rename. json.dump straight onto the target
    truncates it first, so an interrupt mid-write destroyed a resumable run."""
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def token():
    t = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not t:
        print("GITHUB_TOKEN is not set. Run:  read -s GITHUB_TOKEN && export GITHUB_TOKEN")
        sys.exit(1)
    return t


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
                wait = max(30, int(e.headers.get("X-RateLimit-Reset", "0")) - int(time.time()) + 5)
                print(f"  throttled, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            return None, f"HTTP{e.code}"
        except Exception as e:
            if attempt == 3:
                return None, type(e).__name__
            time.sleep(2 ** attempt)
    return None, "retries"


def preflight():
    d, e = gh("/rate_limit")
    if e:
        print(f"\nGitHub rejected the token ({e}). Nothing has been collected.\n"
              "  Check it without revealing it:\n"
              "    curl -sS -o /dev/null -w '%{http_code}\\n' \\\n"
              "      -H \"Authorization: Bearer $GITHUB_TOKEN\" https://api.github.com/rate_limit")
        sys.exit(1)
    core = ((d or {}).get("resources") or {}).get("core") or {}
    print(f"token accepted: {core.get('remaining','?')} of {core.get('limit','?')} "
          f"requests remaining this hour")


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def month_bins(anchor):
    a = ts(anchor)
    return [(f"t-{k}", a - dt.timedelta(days=30 * k),
             a - dt.timedelta(days=30 * k) + dt.timedelta(days=30))
            for k in range(BINS, 0, -1)], a


def author_login(c):
    """GitHub account login, or None when the commit author is not a GitHub user.

    A null author is a human whose email GitHub could not match to an account.
    It is NOT treated as a bot: bot detection needs positive evidence, and
    guessing from a commit email would silently drop real contributors.
    """
    a = c.get("author")
    return (a or {}).get("login")


def is_bot_commit(c):
    a = c.get("author") or {}
    login = str(a.get("login", "") or "")
    return (a.get("type") == "Bot" or login.endswith("[bot]")
            or login.lower() in BOT_LOGINS)


def is_webflow(c):
    """GitHub's own committer account, used for merges made through the web UI.
    Its share is a proxy for squash and rebase merge policy, which changes how
    many commits a given amount of work produces."""
    return ((c.get("committer") or {}).get("login") or "").lower() == "web-flow"


def fetch(budget):
    preflight()
    co = json.load(open(COHORTS))
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}

    old = [k for k, v in st.items() if v.get("schema") != SCHEMA]
    for k in old:
        del st[k]
    if old:
        print(f"purging {len(old)} records from an earlier schema")
    poisoned = [k for k, v in st.items()
                if v.get("error") in ("HTTP401", "HTTP403", "retries")]
    for k in poisoned:
        del st[k]
    if poisoned:
        print(f"clearing {len(poisoned)} entries that failed on credentials or retries")
    stale = [f"{arm}|{r}" for arm in ("stale_by_repo", "fresh_by_repo")
             for r, v in co.get(arm, {}).items()
             if f"{arm}|{r}" in st and st[f"{arm}|{r}"].get("anchor") != v["anchor"]]
    for k in stale:
        del st[k]
    if stale:
        print(f"clearing {len(stale)} entries whose anchor changed since collection")

    todo = [(arm, r, v) for arm in ("stale_by_repo", "fresh_by_repo")
            for r, v in co[arm].items() if f"{arm}|{r}" not in st]
    print(f"{len(todo)} repositories to collect")
    t0 = time.time()
    for i, (arm, r, v) in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        edges, anchor = month_bins(v["anchor"])
        w0 = anchor - dt.timedelta(days=30 * BINS)
        rows, page, err, incomplete, seen = [], 1, None, False, set()
        while True:
            d, e = gh(f"/repos/{v['repo']}/commits",
                      {"since": w0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "until": anchor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "per_page": 100, "page": page})
            if e:
                err = e
                break
            if not isinstance(d, list):
                err = "non_list_response"
                break
            if not d:
                break
            for c in d:
                if c.get("sha") in seen:
                    continue           # defensive: pagination overlap
                seen.add(c.get("sha"))
                rows.append(c)
            if len(d) < 100:
                break
            page += 1
            if page > PAGE_CAP:
                incomplete = True
                break

        rec = {"schema": SCHEMA, "repo": v["repo"], "anchor": v["anchor"],
               "error": err, "pages": page,
               "incomplete": bool(err is None and incomplete),
               "n_rows": len(rows), "n_merge": 0, "n_bot": 0, "n_null_author": 0,
               "n_webflow": 0,
               "bins": {}}
        if not err:
            keep = []
            for c in rows:
                if len(c.get("parents") or []) > 1:
                    rec["n_merge"] += 1
                    continue
                if is_bot_commit(c):
                    rec["n_bot"] += 1
                    continue
                if author_login(c) is None:
                    rec["n_null_author"] += 1
                if is_webflow(c):
                    rec["n_webflow"] += 1
                keep.append(c)
            for label, s, e2 in edges:
                inb = [c for c in keep
                       if s <= ts(c["commit"]["committer"]["date"]) < e2]
                rec["bins"][label] = {
                    "commits": len(inb),
                    "authors": len({author_login(c) for c in inb if author_login(c)})}
        st[f"{arm}|{r}"] = rec
        if i % 10 == 0:
            atomic_dump(st, STATE)
            print(f"  {i}/{len(todo)}", flush=True)
    atomic_dump(st, STATE)
    ok = sum(1 for v in st.values() if not v.get("error") and not v.get("incomplete"))
    print(f"\ncomplete {ok} of {len(st)}; incomplete (page cap, excluded) "
          f"{sum(1 for v in st.values() if v.get('incomplete'))}; errors: "
          f"{collections.Counter(v['error'] for v in st.values() if v.get('error'))}")
    print(f"excluded during counting: {sum(v.get('n_merge',0) for v in st.values())} merge "
          f"commits, {sum(v.get('n_bot',0) for v in st.values())} bot-authored; "
          f"{sum(v.get('n_null_author',0) for v in st.values())} commits kept with no "
          f"GitHub account attached")


def baseline(v):
    xs = [v["bins"][f"t-{k}"]["commits"] for k in BASELINE_BINS if f"t-{k}" in v["bins"]]
    return statistics.mean(xs) if xs else 0.0


def baseline_nonzero(v):
    return sum(1 for k in BASELINE_BINS
               if f"t-{k}" in v["bins"] and v["bins"][f"t-{k}"]["commits"] > 0)


def lead_time(v, frac):
    """Largest m in DETECT_M where the trailing three-bin mean is <= frac x baseline.

    Bins m, m+1, m+2 are the three months ending at t-m. Returns 0 if it never
    fires. Non-decreasing in frac, which the calibration below relies on.
    """
    b = baseline(v)
    if b <= 0:
        return 0
    for m in DETECT_M:                                   # descending: largest m first
        ks = [m + j for j in range(DETECTOR_WINDOW)]
        xs = [v["bins"][f"t-{k}"]["commits"] for k in ks if f"t-{k}" in v["bins"]]
        if len(xs) < DETECTOR_WINDOW:
            continue
        if statistics.mean(xs) <= frac * b:
            return m
    return 0


def actionable_lead(v, frac):
    """Months of warning a firing actually gives. See the first amendment."""
    m = lead_time(v, frac)
    return 0 if m == 0 else m - 1


def fire_threshold(v):
    """Smallest grid fraction at which this repository counts as detected.

    Firing is monotone in frac, so one scalar per repository fully describes it.
    Calibration and the bootstrap then reduce to quantiles of these scalars.
    Returns None for a repository that never fires anywhere on the grid.
    """
    for f in FRAC_GRID:                                  # ascending
        if actionable_lead(v, f) >= MIN_ACTIONABLE_LEAD:
            return f
    return None


def stratum_of(b):
    for i, (lo, hi) in enumerate(STRATA):
        if lo <= b < hi:
            return i
    return None


def fire_rate(thresholds, frac):
    """Share of repositories that fire at `frac`, from precomputed thresholds."""
    if not thresholds:
        return 0.0
    return sum(1 for t in thresholds if t is not None and t <= frac) / len(thresholds)


def calibrate(control_thresholds):
    """Largest grid fraction at which the control firing rate is at most TARGET_FPR.

    Returns None when no grid value achieves it, which drops the stratum. The
    original fixed 0.5 had a null firing rate that fell from 0.94 to 0.002 across
    the baseline range, so it measured volume; calibrating per stratum pins the
    false-positive rate instead of assuming it.
    """
    best = None
    for f in FRAC_GRID:                                  # ascending, rate is monotone
        if fire_rate(control_thresholds, f) <= TARGET_FPR:
            best = f
        else:
            break
    return best


def report():
    st = json.load(open(STATE))
    co = json.load(open(COHORTS))
    drops = {a: collections.Counter() for a in ("stale_by_repo", "fresh_by_repo")}
    elig = {}
    counters = {a: collections.Counter() for a in ("stale_by_repo", "fresh_by_repo")}
    for arm in ("stale_by_repo", "fresh_by_repo"):
        keep = []
        for repo in co.get(arm, {}):
            v = st.get(f"{arm}|{repo}")
            # The pilot test comes FIRST so the exclusion count is deterministic
            # and equals the list in PREREGISTRATION-4 regardless of fetch outcome.
            if repo in PILOT:
                drops[arm]["pilot_excluded_by_name"] += 1
            elif v is None:
                drops[arm]["not_collected"] += 1
            elif v.get("schema") != SCHEMA:
                drops[arm]["superseded_schema"] += 1
            elif v.get("anchor") != co[arm][repo]["anchor"]:
                drops[arm]["superseded_anchor"] += 1
            elif v.get("error"):
                drops[arm][v["error"]] += 1
            elif v.get("incomplete"):
                drops[arm]["page_cap_incomplete"] += 1
            elif baseline(v) < ELIGIBLE_RATE:
                drops[arm]["below_rate_floor"] += 1
            elif baseline_nonzero(v) < MIN_BASELINE_NONZERO:
                drops[arm]["baseline_too_concentrated"] += 1
            else:
                keep.append(v)
                for f in ("n_merge", "n_bot", "n_null_author", "n_webflow", "n_rows"):
                    counters[arm][f] += v.get(f, 0)
        elig[arm] = keep
        tot = sum(drops[arm].values()) + len(keep)
        assert tot == len(co.get(arm, {})), \
            f"drop taxonomy does not partition {arm}: {tot} != {len(co.get(arm, {}))}"

    print("collection and eligibility, by arm")
    for arm in ("stale_by_repo", "fresh_by_repo"):
        c = counters[arm]
        print(f"  {arm:15s} cohort {len(co.get(arm,{})):4d} -> eligible {len(elig[arm]):4d}"
              f"   drops {dict(drops[arm])}")
        if c["n_rows"]:
            print(f"      excluded while counting: {c['n_merge']} merge, {c['n_bot']} bot; "
                  f"kept {c['n_null_author']} with no GitHub account; "
                  f"web-flow committer share {c['n_webflow']/c['n_rows']:.3f} "
                  f"(squash/rebase merge-policy proxy)")

    # HARD STOP ON AN INCOMPLETE COLLECTION.
    # Without this, running `report` before `fetch` printed a full strata table
    # and the sentence "the arms do not overlap in baseline commit volume, so the
    # two populations are not comparable" -- the most interesting conclusion the
    # study can reach -- from a state file holding one repository. Code that
    # produces a plausible answer where it should produce a complaint is the
    # exact failure this project exists to catch, so an absent collection is now
    # an error and not a finding.
    missing = sum(drops[a]["not_collected"] for a in drops)
    total = sum(len(co.get(a, {})) for a in ("stale_by_repo", "fresh_by_repo"))
    if missing:
        print(f"\nCOLLECTION INCOMPLETE. {missing} of {total} cohort repositories have "
              f"no commit record.\n"
              "  Nothing is reported. This is not a result of any kind, and in particular\n"
              "  it is NOT a finding about common support. Run:\n"
              "      read -s GITHUB_TOKEN && export GITHUB_TOKEN\n"
              "      python3 code/cra_commits.py fetch 3000\n"
              "  repeatedly until it reports 0 repositories to collect, then report again.")
        atomic_dump({"schema": SCHEMA, "verdict": "collection incomplete, nothing reported",
                     "missing": missing, "total": total,
                     "drops_by_arm": {a: dict(drops[a]) for a in drops}}, OUT)
        print(f"\nwrote {OUT}")
        return

    # one scalar per repository, from the tested primitive
    thr = {a: [fire_threshold(v) for v in elig[a]] for a in elig}
    bas = {a: [baseline(v) for v in elig[a]] for a in elig}
    strat = {a: [stratum_of(b) for b in bas[a]] for a in bas}

    rows, supported, unsupported_A, uncalibratable = [], [], 0, []
    for i, (lo, hi) in enumerate(STRATA):
        tA = [t for t, s_ in zip(thr["stale_by_repo"], strat["stale_by_repo"]) if s_ == i]
        tB = [t for t, s_ in zip(thr["fresh_by_repo"], strat["fresh_by_repo"]) if s_ == i]
        enough = len(tA) >= MIN_PER_STRATUM and len(tB) >= MIN_PER_STRATUM
        f = calibrate(tB) if enough else None
        # WHY a stratum was dropped is not one thing. "Too few repositories in an
        # arm" and "the control arm fires too often at every threshold" are
        # different findings, and reporting both as absence of common support
        # stated something that was not true of this data.
        reason = ("used" if f is not None else
                  ("insufficient_n" if not enough else "calibration_failed"))
        row = {"stratum": f"[{lo},{hi})", "n_A": len(tA), "n_B": len(tB),
               "drop_reason": reason,
               "min_control_rate": round(fire_rate(tB, FRAC_GRID[0]), 4) if tB else None,
               "calibrated_frac": f,
               "B_fire_at_calibrated": round(fire_rate(tB, f), 4) if f else None,
               "B_fire_at_legacy_0.5": round(fire_rate(tB, LEGACY_FRAC), 4),
               "A_fire_at_legacy_0.5": round(fire_rate(tA, LEGACY_FRAC), 4),
               "sensitivity": round(fire_rate(tA, f), 4) if f else None}
        rows.append(row)
        if f is not None:
            supported.append((i, tA, tB, f))
        else:
            unsupported_A += len(tA)
            if reason == "calibration_failed":
                uncalibratable.append(row)

    print(f"\nstrata, common support requires {MIN_PER_STRATUM} repositories per arm")
    print(f"{'stratum':>12} {'nA':>5} {'nB':>5} {'outcome':>19} {'minB':>6} {'frac':>6} "
          f"{'B@0.5':>7} {'A@0.5':>7} {'sens':>7}")
    for r in rows:
        print(f"{r['stratum']:>12} {r['n_A']:>5} {r['n_B']:>5} {r['drop_reason']:>19} "
              f"{(r['min_control_rate'] if r['min_control_rate'] is not None else 0):>6.3f} "
              f"{str(r['calibrated_frac']):>6} "
              f"{r['B_fire_at_legacy_0.5']:>7.3f} {r['A_fire_at_legacy_0.5']:>7.3f} "
              f"{str(r['sensitivity']):>7}")
    print(f"  minB is the LOWEST control firing rate reachable anywhere on the grid.")
    print(f"  Where it exceeds the {TARGET_FPR:.0%} target, no threshold makes the")
    print(f"  detector usable in that stratum at any sensitivity.")
    print("  B@0.5 and A@0.5 are the ARTIFACT diagnostic: the uncalibrated rule's")
    print("  firing rate should fall steeply with baseline volume in both arms.")

    nA = sum(len(tA) for _, tA, _, _ in supported)
    nB = sum(len(tB) for _, _, tB, _ in supported)
    res = {"schema": SCHEMA, "design": "volume-stratified, threshold calibrated per stratum",
           "n_eligible": {"cohort_A": len(elig["stale_by_repo"]),
                          "cohort_B": len(elig["fresh_by_repo"])},
           "n_in_supported_strata": {"cohort_A": nA, "cohort_B": nB},
           "cohort_A_excluded_no_common_support": unsupported_A,
           "strata": rows, "drops_by_arm": {a: dict(drops[a]) for a in drops},
           "counters_by_arm": {a: dict(counters[a]) for a in counters},
           "baseline_distribution": {
               a: {"n": len(bas[a]),
                   "p10": round(sorted(bas[a])[int(.10 * len(bas[a]))], 3) if bas[a] else None,
                   "median": round(statistics.median(bas[a]), 3) if bas[a] else None,
                   "p90": round(sorted(bas[a])[int(.90 * len(bas[a]))], 3) if bas[a] else None,
                   "max": round(max(bas[a]), 3) if bas[a] else None}
               for a in bas},
           "target_false_positive_rate": TARGET_FPR,
           "adequacy_floor": ADEQUACY_FLOOR,
           "pilot_excluded": sorted(PILOT)}

    if nA < ADEQUACY_FLOOR:
        print(f"\nWITHHELD. {nA} cohort A repositories sit inside supported strata, "
              f"against a floor of {ADEQUACY_FLOOR}.")
        if uncalibratable:
            worst = min(r["min_control_rate"] for r in uncalibratable)
            print(f"\n  AND THE DETECTOR IS NEGATIVE ON ITS OWN TERMS, separately from power.")
            print(f"  {len(uncalibratable)} stratum/strata had enough repositories in both arms")
            print(f"  but no threshold on the grid brings the control firing rate to "
                  f"{TARGET_FPR:.0%}:")
            for r in uncalibratable:
                print(f"    {r['stratum']}  nA {r['n_A']}  nB {r['n_B']}  lowest reachable "
                      f"control rate {r['min_control_rate']:.3f}")
            print(f"  Maintained repositories halve their own commit rate for three months")
            print(f"  often enough that the rule cannot be made specific at any sensitivity.")
            res["verdict"] = ("negative: the pre-registered false-positive rate is "
                              "unreachable in strata that had adequate n; separately "
                              "underpowered in cohort A")
        elif not supported:
            print("  Every stratum was dropped for insufficient repositories in one arm.")
            print("  No statement about common support or about the detector is made.")
            res["verdict"] = "withheld: no stratum reached the per-arm minimum"
        else:
            res["verdict"] = "withheld: below the adequacy floor inside supported strata"
        res["adequate"] = False
        res["uncalibratable_strata"] = uncalibratable
        atomic_dump(res, OUT)
        print(f"\nwrote {OUT}")
        return

    def pooled(sA, sB):
        """Sensitivity and realised control rate, weighted by cohort A stratum size,
        with the calibration RE-RUN on the given sample."""
        num = den = 0.0
        fnum = fden = 0.0
        for tA, tB in zip(sA, sB):
            f = calibrate(tB)
            if f is None or not tA:
                continue
            num += fire_rate(tA, f) * len(tA); den += len(tA)
            fnum += fire_rate(tB, f) * len(tA); fden += len(tA)
        return (num / den if den else 0.0), (fnum / fden if fden else 0.0)

    sens, fpr = pooled([tA for _, tA, _, _ in supported], [tB for _, _, tB, _ in supported])
    rnd = random.Random(BOOT_SEED)
    diffs, senss = [], []
    for _ in range(BOOTSTRAP):
        bA = [[rnd.choice(tA) for _ in tA] for _, tA, _, _ in supported]
        bB = [[rnd.choice(tB) for _ in tB] for _, _, tB, _ in supported]
        s_, f_ = pooled(bA, bB)
        senss.append(s_); diffs.append(s_ - f_)
    diffs.sort(); senss.sort()
    q = lambda a, p: a[min(len(a) - 1, max(0, int(round(p * (len(a) - 1)))))]
    ci_d = (round(q(diffs, .025), 4), round(q(diffs, .975), 4))
    ci_s = (round(q(senss, .025), 4), round(q(senss, .975), 4))
    usable = sens >= SENS_TARGET and not (ci_d[0] <= 0 <= ci_d[1])

    print(f"\nPRIMARY, fixed in PREREGISTRATION-4 and its first amendment")
    print(f"  pooled sensitivity at a calibrated {TARGET_FPR:.0%} false-positive rate: "
          f"{sens:.3f}  95% CI [{ci_s[0]}, {ci_s[1]}]   (n={nA})")
    print(f"  realised control firing rate                                : {fpr:.3f}   (n={nB})")
    print(f"  difference                                                  : {sens-fpr:+.3f}  "
          f"95% CI [{ci_d[0]:+.4f}, {ci_d[1]:+.4f}]")
    print(f"\n  criterion: sensitivity >= {SENS_TARGET} and the difference interval excluding zero")
    print(f"  VERDICT: the detector is {'USABLE' if usable else 'NOT usable'} by the "
          f"pre-registered criterion")

    res.update({"sensitivity": round(sens, 4), "sensitivity_ci": list(ci_s),
                "realised_control_rate": round(fpr, 4),
                "difference": round(sens - fpr, 4), "difference_ci": list(ci_d),
                "usable_by_criterion": bool(usable), "adequate": True,
                "criterion": {"sensitivity_at_least": SENS_TARGET,
                              "false_positive_calibrated_to": TARGET_FPR}})
    atomic_dump(res, OUT)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    os.makedirs(DATA, exist_ok=True)
    if m == "fetch":
        fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 1800)
    else:
        report()
