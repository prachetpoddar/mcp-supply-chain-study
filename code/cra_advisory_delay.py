#!/usr/bin/env python3
"""
What predicts a late advisory? See PREREGISTRATION-5.md.

RUNS ON YOUR MACHINE. Neither sandbox can reach api.osv.dev or the OSV bulk
export; both reach registry.npmjs.org only.

    python3 cra_advisory_delay.py dump      # OSV npm bulk export -> compact records
    python3 cra_advisory_delay.py resolve   # registry publish times + downloads
    python3 cra_advisory_delay.py report    # the pre-registered analysis

No credential is needed by any phase. Nothing here writes a token anywhere.

WHY THE ESTIMATOR LOOKS THE WAY IT DOES
    Every contrast is stratified by FIX YEAR and pooled with Mantel-Haenszel.
    An earlier reading of this same data found a twentyfold effect that was
    entirely fix-year composition: the attribute was near-absent before 2021 and
    near-universal after, and the years differ in lag by two orders of magnitude.
    Intervals are bootstrapped over PACKAGES, not advisories, because one package
    contributes many advisories and treating them as independent is the
    pseudo-replication that has already cost this project one result.
"""
import collections, datetime as dt, io, json, math, os, random, statistics, sys
import urllib.error, urllib.parse, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
ZIP = os.path.join(DATA, "osv_npm_all.zip")
ADV = os.path.join(DATA, "adv_npm.json")
PKG = os.path.join(DATA, "adv_npm_packages.json")
OUT = os.path.join(DATA, "cra_advisory_delay.json")
BULK = "https://osv-vulnerabilities.storage.googleapis.com/npm/all.zip"
UA = {"User-Agent": "mcp-supply-chain-study/0.9 (academic research)"}

# --- transcribed from PREREGISTRATION-5.md, fixed before this file existed ---
PROMPT_DAYS = 30
MIN_FOLLOWUP_DAYS = 90
MIN_DELAYED, MIN_PROMPT, MIN_PER_STRATUM = 300, 300, 30
RESOURCE_CWE = {"CWE-400", "CWE-770", "CWE-1333"}
BOOTSTRAP = int(os.environ.get("BOOTSTRAP", 100000))
PERMUTATIONS = int(os.environ.get("PERMUTATIONS", 2000))
SEED = 20260909
CHUNK = 2000            # bootstrap draws per matrix multiply, to bound memory
BOOT_FLOOR = 1000       # refuse an interval built on fewer estimable resamples
HORIZON_DAYS = 365      # the secondary family this protocol requires
# The analysis date is fixed, not the wall clock: the follow-up cutoff decides
# which pairs enter, so a clock-driven cutoff moved the analysed set between two
# runs of the same code. See PREREGISTRATION-5 amendment one, item 6.
ASOF = os.environ.get("ASOF", "2026-10-07")
CONTRASTS = [  # (key, label, direction expected: +1 more delay, -1 less, 0 none)
    ("sev_high",      "severity HIGH or CRITICAL",            -1),
    ("cwe_resource",  "resource-consumption CWE",             +1),
    ("multi_package", "advisory covers >1 package",           +1),
    ("multi_fix",     "more than one candidate fix version",  +1),
    ("low_downloads", "weekly downloads below the median",    +1),
    ("scoped",        "scoped @org/name package",             -1),
    ("no_cve",        "no CVE alias",                         +1),
    ("not_reviewed",  "not github_reviewed",                  +1),
    ("first_advisory","no prior advisory for this package",   +1),
    ("old_package",   "package older than five years at fix",  0),
]


def _jsonable(o):
    """numpy scalars are not JSON serialisable and numpy 2 calls its boolean
    'bool', so a leaked one reads like a plain Python value in the traceback.
    Convert rather than guess at every call site."""
    item = getattr(o, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def atomic(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, default=_jsonable)
    os.replace(tmp, path)


def ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def dump():
    if not os.path.exists(ZIP):
        print(f"downloading {BULK}")
        req = urllib.request.Request(BULK, headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r, open(ZIP + ".tmp", "wb") as fh:
            n = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                fh.write(b); n += len(b)
                print(f"  {n/1e6:.1f} MB", end="\r", flush=True)
        os.replace(ZIP + ".tmp", ZIP)
        print()
    print(f"reading {ZIP} ({os.path.getsize(ZIP)/1e6:.1f} MB)")
    out, drop = [], collections.Counter()
    with zipfile.ZipFile(ZIP) as z:
        names = [n for n in z.namelist() if n.endswith(".json")]
        print(f"  {len(names)} advisory files")
        for i, name in enumerate(names):
            if i % 20000 == 0:
                print(f"  {i}/{len(names)}", flush=True)
            try:
                a = json.loads(z.read(name))
            except Exception:
                drop["unparseable"] += 1
                continue
            aid = a.get("id", "")
            if a.get("withdrawn"):
                drop["withdrawn"] += 1; continue
            if aid.startswith("MAL-"):
                drop["malicious_package_feed"] += 1; continue
            ds = a.get("database_specific") or {}
            cwes = ds.get("cwe_ids") or []
            if not cwes and "malicious" in (a.get("summary", "") or "").lower():
                drop["malware_by_summary"] += 1; continue
            pub = a.get("published")
            if not pub:
                drop["no_published"] += 1; continue
            fixes = collections.defaultdict(set)
            for af in a.get("affected", []):
                pkg = ((af.get("package") or {}).get("name") or "")
                if (af.get("package") or {}).get("ecosystem") != "npm" or not pkg:
                    continue
                for rg in af.get("ranges", []):
                    for e in rg.get("events", []):
                        if e.get("fixed"):
                            fixes[pkg].add(e["fixed"])
            if not fixes:
                drop["no_fixed_event"] += 1; continue
            out.append({
                "id": aid, "published": pub,
                "aliases": [x for x in (a.get("aliases") or []) if str(x).startswith("CVE-")],
                "severity": ds.get("severity"), "cwes": cwes,
                "github_reviewed": bool(ds.get("github_reviewed")),
                "nvd_published_at": ds.get("nvd_published_at"),
                "n_affected": len(a.get("affected", [])),
                "ref_types": sorted({x.get("type") for x in (a.get("references") or []) if x.get("type")}),
                "fixes": {k: sorted(v) for k, v in fixes.items()},
            })
    print(f"\nkept {len(out)} advisories; dropped {dict(drop)}")
    pkgs = sorted({p for a in out for p in a["fixes"]})
    print(f"distinct npm packages named: {len(pkgs)}")
    atomic({"advisories": out, "dropped": dict(drop),
            "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, ADV)
    print(f"wrote {ADV}")


def get(url, timeout=45):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def resolve(budget=3000):
    d = json.load(open(ADV))
    pkgs = sorted({p for a in d["advisories"] for p in a["fixes"]})
    st = json.load(open(PKG)) if os.path.exists(PKG) else {}
    todo = [p for p in pkgs if p not in st]
    print(f"{len(pkgs)} packages, {len(todo)} still to resolve")
    import time as _t
    t0 = _t.time()
    for i, p in enumerate(todo):
        if _t.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}"); break
        rec = {"time": {}, "created": None, "downloads": None, "error": None}
        try:
            doc = get("https://registry.npmjs.org/" + urllib.parse.quote(p, safe="@"))
            tm = doc.get("time") or {}
            rec["created"] = tm.get("created")
            rec["time"] = {k: v for k, v in tm.items() if k not in ("created", "modified")}
        except urllib.error.HTTPError as e:
            rec["error"] = f"HTTP{e.code}"
        except Exception as e:
            rec["error"] = type(e).__name__
        try:
            dl = get("https://api.npmjs.org/downloads/point/last-week/" + urllib.parse.quote(p, safe="@"))
            rec["downloads"] = dl.get("downloads")
        except Exception:
            pass
        st[p] = rec
        if i % 100 == 0:
            atomic(st, PKG); print(f"  {i}/{len(todo)}", flush=True)
    atomic(st, PKG)
    ok = sum(1 for v in st.values() if v.get("time"))
    print(f"\nresolved {ok} of {len(st)} with a release-time map; "
          f"errors {collections.Counter(v['error'] for v in st.values() if v.get('error'))}")
    print(f"remaining to collect: {len([p for p in pkgs if p not in st])}")


def classify(lag):
    """Three-way outcome, fixed in PREREGISTRATION-5. Factored out so the
    boundaries can be tested; an inline conditional inside report() could not be."""
    if lag < 0:
        return "advisory_first"
    return "prompt" if lag <= PROMPT_DAYS else "delayed"


def holm(ps):
    """Holm step-down adjusted p-values, in the input order."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    m = len(ps); out = [None]*m; run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, ps[i]*(m-rank)))
        out[i] = run
    return out


def mh_odds(tab):
    """Mantel-Haenszel odds ratio across strata. tab: list of (a,b,c,d) per stratum,
    a=exposed&delayed b=exposed&prompt c=unexposed&delayed d=unexposed&prompt."""
    num = den = 0.0
    for a, b, c, d in tab:
        n = a + b + c + d
        if n == 0:
            continue
        num += a * d / n
        den += b * c / n
    return (num / den) if den > 0 else None


def _asof():
    t = ts(ASOF + "T00:00:00Z")
    if t is None:
        raise SystemExit(f"ASOF={ASOF!r} is not a date this code can parse")
    return t


def _rows(d, st, asof):
    """One row per (advisory, fix version), which is the unit this protocol fixes.

    Amendment one, items 1 to 4: the earlier version built one row per
    (advisory, package) and collapsed candidate versions with min(), which takes
    the earliest publish time and so maximises the lag; exposure for multi_fix
    came from the same collapsed list as the outcome; and unknown exposure was
    coded as unexposed. Here each version carries its own lag, multi_fix is a
    property of the group, and unknown exposure is None and excluded per
    contrast rather than counted as the reference level.
    """
    rows, drop = [], collections.Counter()
    seen_before = collections.Counter()
    # Date order, not file order. The zip namelist is GHSA identifiers, so the
    # earlier version's "no prior advisory for this package" was decided by
    # filename. Amendment two, item 3.
    for a in sorted(d["advisories"], key=lambda r: r.get("published") or ""):
        apub = ts(a["published"])
        if not apub:
            drop["advisory_has_no_publish_time"] += 1
            continue
        n_pkg = len(a["fixes"])
        for p in sorted(a["fixes"]):
            rec = st.get(p) or {}
            tm = rec.get("time") or {}
            names = a["fixes"][p]
            cand = [(v, ts(tm.get(v))) for v in names]
            cand = [(v, t) for v, t in cand if t]
            prior = seen_before[p]
            seen_before[p] += 1
            if not cand:
                drop["fix_version_has_no_publish_time"] += 1
                continue
            if len(cand) < len(names):
                # A group losing SOME versions is not a dropped group, and the
                # earlier version counted it nowhere while letting it change the
                # exposure. Amendment two, item 2.
                drop["groups_partially_resolved"] += 1
                drop["versions_lost_in_partial_groups"] += len(names) - len(cand)
                if len(names) > 1 and len(cand) == 1:
                    drop["groups_demoted_multi_to_single"] += 1
            created = ts(rec.get("created"))
            for v, fix in cand:
                followup = (asof - fix).days
                if followup < MIN_FOLLOWUP_DAYS:
                    drop["insufficient_followup"] += 1
                    continue
                lag = (apub - fix).total_seconds() / 86400
                rows.append({
                    "id": a["id"], "package": p, "fix_version": v,
                    "fix_year": fix.year, "lag": lag, "followup_days": followup,
                    "cls": classify(lag),
                    "sev_high": (a.get("severity") or "") in ("HIGH", "CRITICAL"),
                    "cwe_resource": bool(set(a.get("cwes") or []) & RESOURCE_CWE),
                    "multi_package": n_pkg > 1,
                    "multi_fix": len(cand) > 1,
                    "multi_fix_names": len(names) > 1,   # sensitivity, not a contrast
                    "scoped": p.startswith("@"),
                    "no_cve": not a["aliases"],
                    "not_reviewed": not a["github_reviewed"],
                    "first_advisory": prior == 0,
                    "old_package": None if created is None
                                   else (fix - created).days > 5 * 365,
                    "downloads": rec.get("downloads"),
                    "n_affected_osv": a["n_affected"],
                })
    return rows, drop


def cells_by_package(rows, keys, years):
    """M[i, k, s] = (a, b, c, d) for package i, contrast k, fix-year stratum s,
    with a=exposed&delayed, b=exposed&prompt, c=unexposed&delayed,
    d=unexposed&prompt, matching mh_odds's docstring. Rows whose exposure is
    unknown are skipped for that contrast only."""
    import numpy as np
    yi = {y: s for s, y in enumerate(years)}
    pk = sorted({r["package"] for r in rows})
    pi = {p: i for i, p in enumerate(pk)}
    M = np.zeros((len(pk), len(keys), len(years), 4))
    for r in rows:
        s, i = yi[r["fix_year"]], pi[r["package"]]
        dl = r["cls"] == "delayed"
        for k, key in enumerate(keys):
            e = r[key]
            if e is None:
                continue
            M[i, k, s, (0 if dl else 1) if e else (2 if dl else 3)] += 1
    return pk, M


def mh_from_cells(cells):
    """Vectorised Mantel-Haenszel over the last two axes of `cells`. Must agree
    with mh_odds() on the same table; report() asserts that it does."""
    import numpy as np
    a, b, c, d = cells[..., 0], cells[..., 1], cells[..., 2], cells[..., 3]
    n = a + b + c + d
    safe = np.where(n > 0, n, 1.0)
    num = np.where(n > 0, a * d / safe, 0.0).sum(-1)
    den = np.where(n > 0, b * c / safe, 0.0).sum(-1)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def mh_parts(cells):
    """The Mantel-Haenszel numerator and denominator, kept separate so the three
    ways a pooled estimate can fail stay distinguishable: an empty table, a zero
    numerator, and perfect separation (a zero denominator with a positive
    numerator, which is an unbounded odds ratio and not an absence of evidence)."""
    num = den = 0.0
    for a, b, c, d in cells:
        n = a + b + c + d
        if n == 0:
            continue
        num += a * d / n
        den += b * c / n
    return num, den


def stratum_or(cells, half=0.5):
    """Per-stratum odds ratios with a continuity correction, for the homogeneity
    table only. No pooled estimate uses these."""
    return [((a + half) * (d + half)) / ((b + half) * (c + half)) for a, b, c, d in cells]


def breslow_day(cells, mh):
    """Breslow-Day statistic for the hypothesis of a common odds ratio, with the
    degrees of freedom counted from the strata that carry information. A stratum
    with an empty margin tells you nothing about homogeneity and is skipped.

    Mantel-Haenszel is a summary only under a common odds ratio. PREREGISTRATION-5
    made it the sole estimator and never asked for this check; amendment two adds
    it, after a pooled 0.48 turned out to average stratum values from 0.12 to 1.55.
    """
    X, used = 0.0, 0
    for a, b, c, d in cells:
        n1, n0 = a + b, c + d
        m1, n = a + c, a + b + c + d
        if min(n1, n0, m1, n - m1) == 0:
            continue
        A = mh - 1.0
        B = -(mh * (n1 + m1) + (n0 - m1))
        C = mh * n1 * m1
        lo, hi = max(0.0, m1 - n0), min(n1, m1)
        if abs(A) < 1e-12:
            ea = n1 * m1 / n
        else:
            disc = B * B - 4 * A * C
            if disc < 0:
                continue
            roots = [(-B + math.sqrt(disc)) / (2 * A), (-B - math.sqrt(disc)) / (2 * A)]
            ok = [r for r in roots if lo - 1e-9 <= r <= hi + 1e-9]
            if not ok:
                continue
            ea = min(ok, key=lambda r: abs(r - n1 * m1 / n))
        eb, ec, ed = n1 - ea, m1 - ea, n0 - m1 + ea
        if min(ea, eb, ec, ed) <= 0:
            continue
        v = 1.0 / (1 / ea + 1 / eb + 1 / ec + 1 / ed)
        X += (a - ea) ** 2 / v
        used += 1
    return X, max(used - 1, 0)


def chi_sf(x, k):
    """Upper tail of a chi-square with k degrees of freedom, no SciPy here."""
    if k <= 0:
        return 1.0
    if k % 2 == 0:
        t = math.exp(-x / 2)
        s = t
        for i in range(1, k // 2):
            t *= (x / 2) / i
            s += t
        return min(1.0, s)
    z = math.sqrt(x)
    s = math.erfc(z / math.sqrt(2))
    t = math.exp(-x / 2) * math.sqrt(2 * x / math.pi)
    for i in range(1, (k - 1) // 2 + 1):
        s += t
        t *= x / (2 * i + 1)
    return min(1.0, s)


def bootstrap_logs(M, n_pkg, n_keys, n_strata, seed=None):
    """Cluster bootstrap over packages: BOOTSTRAP by n_keys log odds ratios, NaN
    where a resample is not estimable.

    Its own function so a test can pin it. A multinomial draw over package
    indices IS sampling n packages with replacement, and the multiplicity is the
    weight: replacing `mult` with `mult > 0` would silently turn this into an
    unweighted 63% subsample, widening every interval by about a quarter while
    the printed draw count stayed the same.
    """
    import numpy as np
    rng = np.random.default_rng(SEED if seed is None else seed)
    flat = M.reshape(n_pkg, -1)
    logs = np.full((BOOTSTRAP, n_keys), np.nan)
    at = 0
    while at < BOOTSTRAP:
        ch = min(CHUNK, BOOTSTRAP - at)
        mult = rng.multinomial(n_pkg, np.full(n_pkg, 1.0 / n_pkg), size=ch)
        cnt = (mult @ flat).reshape(ch, n_keys, n_strata, 4)
        orr = mh_from_cells(cnt)
        good = (orr > 0) & np.isfinite(orr)
        blk = np.full(orr.shape, np.nan)
        blk[good] = np.log(orr[good])
        logs[at:at + ch] = blk
        at += ch
    return logs


def _verdict(order, unestimable):
    """The verdict has to answer to the disposition, not to `supported` alone:
    this protocol's downgrade rule can retire a significant contrast, a rejected
    common odds ratio means the pooled value is not one effect, and a perfectly
    separated contrast is an unbounded association rather than a null."""
    sep = [u["label"] for u in unestimable if u.get("perfect_separation")]
    strong = [f["label"] for f in order if f["disposition"] == "supported"]
    het = [f["label"] for f in order
           if f["supported"] and not f["pooled_interpretable"]]
    if strong:
        return "supported contrasts present, see findings"
    if het:
        return ("heterogeneous: " + ", ".join(het) + " clears Holm with an interval "
                "excluding 1, but a common odds ratio is rejected, so it is reported "
                "stratum by stratum and not as a single effect")
    if sep:
        return ("not pooled: " + ", ".join(sep) + " is perfectly separated, which is "
                "an unbounded association and not an absence of evidence")
    return "negative: no contrast survives Holm with an interval excluding 1"


def family(rows, keys_all, label, out):
    """Run the whole pre-registered family on `rows` and write into dict `out`."""
    import numpy as np
    test = [r for r in rows if r["cls"] in ("prompt", "delayed")]
    nd = sum(1 for r in test if r["cls"] == "delayed")
    np_ = len(test) - nd
    years_all = sorted({r["fix_year"] for r in test})
    usable = [y for y in years_all
              if sum(1 for r in test if r["fix_year"] == y and r["cls"] == "delayed")
              >= MIN_PER_STRATUM]
    dropped_years = sorted(set(years_all) - set(usable))
    T = [r for r in test if r["fix_year"] in usable]
    res = {
        "label": label, "n_classified": len(rows), "n_prompt_or_delayed": len(test),
        "n_delayed": nd, "n_prompt": np_, "n_analysed": len(T),
        "strata_used": usable, "strata_dropped": dropped_years,
        "pairs_dropped_short_strata": len(test) - len(T),
        "excluded_advisory_first": sum(1 for r in rows if r["cls"] == "advisory_first"),
    }
    out[label] = res
    print(f"\n[{label}] delayed {nd}, prompt {np_}, analysed {len(T)}; "
          f"strata {usable} (dropped {dropped_years}, taking {len(test)-len(T)} pairs)")
    if nd < MIN_DELAYED or np_ < MIN_PROMPT or not usable:
        res["verdict"] = "descriptive only: below the adequacy floor"
        print(f"  DESCRIPTIVE ONLY: the floor is {MIN_DELAYED} delayed and "
              f"{MIN_PROMPT} prompt with {MIN_PER_STRATUM} delayed per stratum")
        return res

    # exposure counts per contrast, and which contrasts can be estimated at all
    counts, keys = {}, []
    for key, lbl, direction in keys_all:
        ex = sum(1 for r in T if r[key] is True)
        un = sum(1 for r in T if r[key] is False)
        mi = sum(1 for r in T if r[key] is None)
        exd = sum(1 for r in T if r[key] is True and r["cls"] == "delayed")
        counts[key] = {"label": lbl, "expected": direction, "n_exposed": ex,
                       "n_unexposed": un, "n_exposure_unknown": mi,
                       "n_exposed_and_delayed": exd}
        keys.append(key)
    res["exposure"] = counts

    pk, M = cells_by_package(T, keys, usable)
    obs_cells = M.sum(0)
    obs = mh_from_cells(obs_cells)

    # primitive check: the vectorised estimator against the scalar one it replaces
    for k, key in enumerate(keys):
        scal = mh_odds([tuple(obs_cells[k, s]) for s in range(len(usable))])
        vec = None if np.isnan(obs[k]) else float(obs[k])
        if (scal is None) != (vec is None) or (
                scal is not None and abs(scal - vec) > 1e-9 * max(1.0, abs(scal))):
            raise SystemExit(f"vectorised and scalar Mantel-Haenszel disagree on "
                             f"{key}: {scal!r} vs {vec!r}")
    res["per_stratum_tables"] = {
        key: {str(y): [int(x) for x in obs_cells[k, s]]
              for s, y in enumerate(usable)} for k, key in enumerate(keys)}

    logs = bootstrap_logs(M, len(pk), len(keys), len(usable))
    print(f"  bootstrap: {BOOTSTRAP} draws over {len(pk)} packages, "
          f"one shared set of draws for every contrast")

    findings, unestimable = [], []
    for k, key in enumerate(keys):
        lbl, direction = counts[key]["label"], counts[key]["expected"]
        col = logs[:, k]
        bs = col[np.isfinite(col)]
        if np.isnan(obs[k]) or bs.size < BOOT_FLOOR:
            cell = [tuple(obs_cells[k, s_]) for s_ in range(len(usable))]
            num, den = mh_parts(cell)
            separated = den == 0 and num > 0
            if separated:
                why = ("perfect separation: the denominator is zero while the "
                       "numerator is positive, so the pooled odds ratio is "
                       "unbounded. This is the strongest possible association "
                       "and must not be read as an absence of evidence")
            elif num == 0 and counts[key]["n_exposed"] > 0:
                why = (f"the numerator is identically zero: {counts[key]['n_exposed']} "
                       f"exposed pairs and none of them delayed")
            elif den == 0:
                why = ("no stratum holds both an exposed and an unexposed pair, so "
                       "the Mantel-Haenszel denominator is zero")
            else:
                why = f"only {int(bs.size)} of {BOOTSTRAP} resamples were estimable"
            unestimable.append(dict(counts[key], key=key, observed_or=None
                                    if np.isnan(obs[k]) else float(obs[k]),
                                    bootstrap_resamples_estimable=int(bs.size),
                                    mh_numerator=num, mh_denominator=den,
                                    perfect_separation=separated, reason=why))
            print(f"  {lbl:<36} not estimable: {why}")
            continue
        bs = np.sort(bs)
        lo, hi = float(np.exp(np.quantile(bs, 0.025))), float(np.exp(np.quantile(bs, 0.975)))
        neg, pos, zer = int((bs < 0).sum()), int((bs > 0).sum()), int((bs == 0).sum())
        k_side = min(neg + zer, pos + zer)
        p = min(1.0, (2 * k_side + 1) / (bs.size + 1))
        cell = [tuple(obs_cells[k, s_]) for s_ in range(len(usable))]
        X, df = breslow_day(cell, float(obs[k]))
        hp = chi_sf(X, df)
        sors = stratum_or(cell)
        inform = [s_ for s_ in range(len(usable))
                  if obs_cells[k, s_, 1] * obs_cells[k, s_, 2] > 0]
        findings.append({
            "key": key, "label": lbl, "or": float(obs[k]),
            "ci": [lo, hi], "p": p, "expected": direction,
            "bootstrap_resamples_estimable": int(bs.size),
            "homogeneity": {
                "breslow_day_x2": X, "df": df, "p": hp,
                "common_odds_ratio_rejected": hp < 0.05,
                "stratum_or": {str(usable[s_]): sors[s_] for s_ in range(len(usable))},
                "strata_informing_denominator": [usable[s_] for s_ in inform],
                "n_informative": int(sum(obs_cells[k, s_].sum() for s_ in inform)),
                "strata_opposing_pooled": [
                    usable[s_] for s_ in inform
                    if (sors[s_] > 1) != (float(obs[k]) > 1)],
            }})

    adj = holm([f["p"] for f in findings])
    pad = holm([f["p"] for f in findings] + [1.0] * (len(keys_all) - len(findings)))
    for f, h, h10 in zip(findings, adj, pad):
        f["holm"] = h
        f["holm_at_preregistered_ten"] = h10
        f["supported"] = h < 0.05 and not (f["ci"][0] <= 1 <= f["ci"][1])
        f["direction_as_expected"] = (f["expected"] == 0 or
                                      (f["or"] > 1) == (f["expected"] > 0))

    # permutation null, row level, as pre-registered. It ignores clustering.
    yi = {y: s for s, y in enumerate(usable)}
    yr = np.array([yi[r["fix_year"]] for r in T])
    dl = np.array([1 if r["cls"] == "delayed" else 0 for r in T])
    E = np.array([[-1 if r[key] is None else (1 if r[key] else 0) for key in keys]
                  for r in T])
    blocks = [np.where(yr == s)[0] for s in range(len(usable))]
    rng2 = np.random.default_rng(SEED + 1)
    est = [keys.index(f["key"]) for f in findings]
    maxlog = np.empty(PERMUTATIONS)
    for t in range(PERMUTATIONS):
        dp = dl.copy()
        for idx in blocks:
            dp[idx] = rng2.permutation(dl[idx])
        cells = np.zeros((len(est), len(usable), 4))
        for j, k in enumerate(est):
            ek = E[:, k]
            m = ek >= 0
            dd = dp[m]
            jj = np.where(ek[m] == 1, np.where(dd == 1, 0, 1), np.where(dd == 1, 2, 3))
            cells[j] = np.bincount(yr[m] * 4 + jj,
                                   minlength=len(usable) * 4).reshape(len(usable), 4)
        orr = mh_from_cells(cells)
        v = orr[(orr > 0) & np.isfinite(orr)]
        maxlog[t] = float(np.abs(np.log(v)).max()) if v.size else np.nan
    skipped = int(np.isnan(maxlog).sum())
    kept = maxlog[np.isfinite(maxlog)]
    if kept.size < PERMUTATIONS // 2:
        raise SystemExit(f"permutation null unusable: only {kept.size} of "
                         f"{PERMUTATIONS} draws produced an estimable contrast")
    thr = float(np.exp(np.quantile(np.sort(kept), 0.95)))
    if not thr > 1.0:
        raise SystemExit(f"permutation threshold came out at {thr}, which cannot be "
                         "right: the 95th percentile of |log OR| under no "
                         "association must exceed zero")
    res["permutation_draws_skipped"] = skipped
    print(f"  permutation null ({PERMUTATIONS} draws, labels shuffled within fix "
          f"year at the ROW level): family threshold OR {thr:.3f} or 1/{thr:.3f}")
    print("    that threshold ignores package clustering, so it is narrower than "
          "the intervals above; decisions stay on Holm over the bootstrap")

    for f in findings:
        exceeds = f["or"] > thr or f["or"] < 1 / thr
        f["exceeds_permutation_spread"] = exceeds
        het = f["homogeneity"]["common_odds_ratio_rejected"]
        f["pooled_interpretable"] = not het
        if f["supported"] and het:
            f["disposition"] = (
                "significant under pooling, but the common odds ratio is rejected "
                f"(Breslow-Day p={f['homogeneity']['p']:.2g}); the pooled value is "
                "not one effect and the result is reported stratum by stratum")
        elif f["supported"]:
            f["disposition"] = ("supported" if exceeds else
                                "downgraded: smaller than the permutation spread, "
                                "reported as consistent with no association")
        elif exceeds:
            f["disposition"] = ("not supported after Holm, but larger than the "
                                "row-level permutation spread, which ignores "
                                "clustering; treated as unresolved, not as a null")
        else:
            f["disposition"] = "not supported, and within the permutation spread"

    if T and "multi_fix_names" in T[0]:
        _, Mn = cells_by_package(T, ["multi_fix_names"], usable)
        alt = mh_from_cells(Mn.sum(0))[0]
        res["sensitivity_multi_fix_exposure_on_names"] = (
            None if np.isnan(alt) else float(alt))
        print(f"  sensitivity: exposure defined on named fix versions rather than "
              f"on resolvable ones gives MH {alt:.3f}")

    order = sorted(findings, key=lambda f: f["p"])
    res.update({
        "contrasts_preregistered": len(keys_all),
        "contrasts_estimated": len(findings),
        "holm_divisor": len(findings),
        "unestimable": unestimable,
        "findings": order,
        "permutation_family_threshold_or": thr,
        "exceeding_permutation_spread": [f["label"] for f in order
                                         if f["exceeds_permutation_spread"]],
        "verdict": _verdict(order, unestimable),
        "heterogeneous_contrasts": [f["label"] for f in order
                                    if f["supported"] and not f["pooled_interpretable"]],
        "unresolved": [f["label"] for f in order
                       if f["disposition"].startswith("not supported after Holm, but")],
    })
    print(f"\n  after Holm across {len(findings)} contrasts "
          f"(at the pre-registered ten in brackets)")
    for f in order:
        d = "as expected" if f["direction_as_expected"] else "DIRECTION OPPOSITE TO EXPECTED"
        hh = f["homogeneity"]
        flag = "" if not hh["common_odds_ratio_rejected"] else \
               f"  HETEROGENEOUS (Breslow-Day p={hh['p']:.1e}, strata against: {hh['strata_opposing_pooled']})"
        print(f"    {f['label']:<36} OR {f['or']:>5.2f} [{f['ci'][0]:.2f},{f['ci'][1]:.2f}] "
              f"holm {f['holm']:.4f} [{f['holm_at_preregistered_ten']:.4f}]  "
              f"{'SUPPORTED' if f['supported'] else 'not supported'}  {d}{flag}")
    print(f"  verdict: {res['verdict']}")
    if res["unresolved"]:
        print(f"  unresolved rather than null: {res['unresolved']}")
    return res


def report():
    import hashlib
    import numpy as np
    d = json.load(open(ADV))
    st = json.load(open(PKG)) if os.path.exists(PKG) else {}
    missing = sum(1 for a in d["advisories"] for p in a["fixes"] if p not in st)
    if missing:
        print(f"COLLECTION INCOMPLETE: {missing} advisory-package pairs have no registry\n"
              "  record. Nothing is reported. Run `resolve` until it reports 0 remaining.")
        return
    asof = _asof()
    rows, drop = _rows(d, st, asof)
    if not rows:
        print("no rows survived the drops; nothing to report")
        return
    cls = collections.Counter(r["cls"] for r in rows)

    # popularity: the median is over analysed rows that carry a figure, and rows
    # without one are excluded from that contrast rather than called above median.
    # The split is the median over PACKAGES that carry a figure, which is what
    # the protocol says. Taking it over rows let a package with many advisory
    # rows pull the split up. Amendment two, item 4.
    per_pkg = {r["package"]: r["downloads"] for r in rows if r["downloads"] is not None}
    dls = sorted(per_pkg.values())
    med_dl = statistics.median(dls) if dls else None
    for r in rows:
        r["low_downloads"] = (None if r["downloads"] is None or med_dl is None
                              else r["downloads"] < med_dl)
    cover = sum(1 for r in rows if r["downloads"] is not None) / len(rows)

    af = sorted(-r["lag"] for r in rows if r["cls"] == "advisory_first")
    af_window = {"n": len(af),
                 "median_days": (statistics.median(af) if af else None),
                 "p90_days": (af[int(.9 * (len(af) - 1))] if af else None)}

    out = {
        "schema": 2,
        "asof": ASOF,
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED, "bootstrap": BOOTSTRAP, "permutations": PERMUTATIONS,
        "bootstrap_floor": BOOT_FLOOR,
        "code_sha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(),
        "unit": "one row per (advisory, fix version); see PREREGISTRATION-5 amendment one",
        "n_rows": len(rows), "classes": dict(cls),
        "drops": dict(drop),
        "median_downloads_split": med_dl,
        "downloads_split_basis": f"median over {len(dls)} packages carrying a figure",
        "downloads_coverage": round(cover, 4),
        "downloads_note": ("api.npmjs.org is unreachable from both sandboxes, so the "
                           "popularity contrast is estimated on the rows that carry a "
                           "figure and the rest are excluded, not called above median"),
        "advisory_first_exposure_window": af_window,
        "families": {},
    }
    print(f"asof {ASOF}; {len(rows)} rows "
          f"(delayed {cls['delayed']}, prompt {cls['prompt']}, "
          f"advisory-first {cls['advisory_first']})")
    print(f"drops {dict(drop)}")
    print(f"downloads coverage {cover:.1%}; popularity split at {med_dl}")
    print(f"advisory-first exposure window: n {af_window['n']}, "
          f"median {af_window['median_days']}d, p90 {af_window['p90_days']}d")

    family(rows, CONTRASTS, "main", out["families"])
    horizon = [r for r in rows if r["followup_days"] >= HORIZON_DAYS]
    print(f"\n365-day horizon: {len(horizon)} of {len(rows)} rows carry a full year "
          f"of follow-up at {ASOF}")
    family(horizon, CONTRASTS, "horizon_365", out["families"])

    out["verdict"] = out["families"]["main"].get("verdict")
    atomic(out, OUT)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    if m == "dump":
        dump()
    elif m == "resolve":
        resolve(float(sys.argv[2]) if len(sys.argv) > 2 else 3000)
    else:
        report()
