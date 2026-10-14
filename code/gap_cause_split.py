#!/usr/bin/env python3
"""Why does a release-frozen dependency tree report advisories the install does not?

Pre-registered in PREREGISTRATION-6.md. Amendment two withdrew the first run's
headline, and this file implements the corrected protocol. Read that amendment
before reading these numbers.

THE CORRECTION THAT MATTERS
    The first run classified only the findings the frozen tree reports and the
    live tree does not. That population is not neutral: a finding lands in it
    only when a fixed version inside the root's declared range was published
    after the root shipped, because otherwise the live arm would still flag it.
    GHSA publishes at or after the fix in all but about 4% of cases, so
    "advisory published after the root shipped" is close to forced there. The
    99.8% that population produced is arithmetically right and says nothing
    about publisher behaviour.

    The headline here is therefore every finding the frozen tree reports,
    whether or not the live tree still reports it, which carries no fix-timing
    filter. The filtered cell is still reported, labelled as conditional.

THE CELL THE FIRST RUN THREW AWAY IS THE INTERESTING ONE
    A finding both arms flag, whose advisory was already published when the root
    shipped, is a root that shipped a dependency version already covered by a
    published advisory and still installs it today. That is the publisher-side
    question, and the frozen-only population excludes it by construction.
    Reported at the server level, because the finding level is concentrated.

CATEGORIES (unchanged from the original protocol)
    post_ship           advisory published after the root shipped
    pre_ship_stable     published at or before, and unchanged since
    pre_ship_modified   published at or before but changed after, so whether it
                        covered the frozen version at ship time is not settled
    undated             no publication timestamp; excluded from the split
                        denominator per the protocol, and zero in this export

WHAT THE DATES ARE NOT
    `published` is when the advisory entered OSV, which can lag the upstream
    GHSA publication, so post_ship is an UPPER BOUND on "no one could have known
    at ship time". This file makes no claim about when knowledge was available.
    199 rows carry `modified` earlier than `published` (amendment one item 2), so
    the change test uses max(published, modified).

WHY THE PARSER RAISES
    It used to return None on an unreadable timestamp, and the change test read
    None as "no modified date" and fell back to `published` alone. That moved
    rows OUT of the indeterminate band, the opposite of what amendment one
    guarantees, silently, with the verdict unchanged. 30% of `modified` values
    carry nine fractional digits and depend on that path, so a format change
    there is a live risk. It is NOT true of `published`, which decides the
    category and carries no fractional second anywhere in this snapshot. An
    unreadable timestamp is an error either way.

Run: python3 code/gap_cause_split.py
"""
import collections
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys

import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
STATE = os.environ.get("GAP_STATE", os.path.join(DATA, "nested_gap_state.json"))
ADVISORIES = os.environ.get("ADVISORIES", os.path.join(DATA, "advisories_npm.json"))
ADV_META = os.environ.get("ADVISORY_META",
                          os.path.join(DATA, "advisories_npm_meta.json"))
GAP = os.environ.get("GAP_RESULT", os.path.join(DATA, "nested_gap.json"))
OUT = os.environ.get("CAUSE_OUT", os.path.join(DATA, "gap_cause_split.json"))
BOOTSTRAP = int(os.environ.get("BOOTSTRAP", 10000))
SEED = 20261013
YOUNG_DAYS = 30
DENSEST = "hono"
PRE_SHIP = ("pre_ship_stable", "pre_ship_modified")

# The join must include prereleases, and nothing used to test that it did. This
# is the (package, version) the behaviour check fires on: a version that matches
# its advisory ONLY when prereleases are included. A constant so that a fixture
# can point it elsewhere, and a hard failure if it stops being prerelease-only.
PROBE = (("multer", "1.4.5-lts.2"),)

# The published measurement this analysis must reproduce before it may report
# anything. These are not defaults to be relaxed: PREREGISTRATION-6 makes
# reproducing them a precondition, and the gate used to live in prose only.
PUBLISHED = {
    "crosstab": {"frozen_flags_live_clean": 130, "live_flags_frozen_clean": 0,
                 "both_flag": 37, "both_flag_lists_differ": 34,
                 "both_flag_lists_identical": 3, "neither_flags": 82},
    "phantom_findings": 4442, "missed_findings": 15,
    "phantom_trees": 164, "phantom_pairs_tree_package": 906,
    # the populations this analysis actually reports, which the gate used to omit
    "all_frozen_side": 4638, "both_arms_flag": 196,
}

TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?"
                r"(Z|[+-]\d{2}:?\d{2})$")


class BadTimestamp(ValueError):
    """An unreadable timestamp. Never swallowed: see WHY THE PARSER RAISES."""


class GateFailed(RuntimeError):
    """A precondition did not hold. Raised, not asserted.

    `python3 -O` deletes every `assert`, which deleted this file's entire
    reproduction gate and left an output byte-indistinguishable from a gated
    run. A check that can be removed by an interpreter flag is prose with extra
    steps.
    """


CHECKS = []


def require(cond, msg):
    CHECKS.append(msg)
    if not cond:
        raise GateFailed(msg)


def parse(ts):
    """One OSV or registry timestamp to an aware datetime. Raises on anything else.

    Handles arbitrary fractional-second precision, because OSV emits nine digits
    where `datetime.fromisoformat` accepts six on some interpreters, and both
    `Z` and numeric offsets. A naive timestamp is an error rather than a silent
    timezone assumption, since comparing naive to aware raises later and
    comparing two naives is timezone-blind.
    """
    if ts is None or ts == "":
        raise BadTimestamp("empty timestamp")
    m = TS.match(ts.strip())
    if not m:
        raise BadTimestamp(f"unreadable timestamp: {ts!r}")
    day, clock, frac, off = m.groups()
    micro = (frac or ".0")[1:7].ljust(6, "0")
    off = "+00:00" if off == "Z" else (off if ":" in off else off[:3] + ":" + off[3:])
    try:
        return dt.datetime.fromisoformat(f"{day}T{clock}.{micro}{off}")
    except ValueError as e:
        # well-shaped but impossible, such as month 13. Raised as BadTimestamp so
        # that a caller catching BadTimestamp cannot let a bare ValueError past.
        raise BadTimestamp(f"impossible timestamp: {ts!r}") from e


def split(x):
    n, _, v = x.rpartition("@@")
    return n, v


def classify(pub, mod, ship):
    """The pre-registered decision rule.

    `pub` None means the advisory carries no publication date. `mod` None means
    no modification date, which is a different thing from an unreadable one:
    unreadable raises in parse() and never reaches here.
    """
    if pub is None:
        return "undated"
    if pub > ship:
        return "post_ship"
    last = max(pub, mod) if mod is not None else pub
    return "pre_ship_modified" if last > ship else "pre_ship_stable"


def in_cohort(asof, ship, days=None):
    """Is this root inside the young cohort?

    Extracted because the boundary is the thing that moves: a root at exactly
    `days` is in, and a root published AFTER the snapshot has a negative age and
    is out. Both were inline and untested, and a reviewer-designed mutation of
    the inclusive bound changed the cohort by two roots without turning anything
    red.
    """
    d = (asof - ship).days
    return 0 <= d <= (YOUNG_DAYS if days is None else days)


def cluster(name, unit):
    """The resampling unit. `scope` approximates publisher and is declared as such."""
    if unit == "package":
        return name
    if unit == "scope":
        return name.split("/")[0] if name.startswith("@") else name
    raise ValueError(unit)


def share(rows, cat="post_ship"):
    """Percentage in `cat`, with `undated` out of the denominator per the protocol."""
    d = collections.Counter(r["category"] for r in rows)
    n = sum(v for k, v in d.items() if k != "undated")
    return (100.0 * d[cat] / n) if n else None


def pctile(xs, q):
    return xs[min(int(q * len(xs)), len(xs) - 1)] if xs else None


def bootstrap_ci(rows, key, draws=BOOTSTRAP, seed=SEED):
    """Cluster bootstrap over whatever `key` returns. Two decimals, not one.

    This is a ratio estimator over a superpopulation of clusters like the ones
    observed. It has no finite-population coverage interpretation for the
    findings actually in hand, which is why the result is reported across
    several cluster units rather than behind this single interval.
    """
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    names = sorted(by)
    rnd = random.Random(seed)
    vals = []
    for _ in range(draws):
        draw = []
        for nm in rnd.choices(names, k=len(names)):
            draw.extend(by[nm])
        v = share(draw)
        if v is not None:
            vals.append(v)
    vals.sort()
    return {"clusters": len(names), "draws": len(vals),
            "ci95": [round(pctile(vals, 0.025), 2),
                     round(pctile(vals, 0.975), 2)] if vals else None,
            "draws_at_100_pct": round(100.0 * sum(1 for v in vals if v >= 100.0)
                                      / len(vals), 2) if vals else None}


ALIGNED = os.environ.get("GAP_STATE_ALIGNED",
                         os.path.join(DATA, "nested_gap_state_aligned.json"))


def collect(state=None):
    """Every frozen-side finding, labelled by cell, with its category and gap."""
    raw = json.load(open(state or STATE))
    s = {k: v for k, v in raw.items() if "skip" not in v and not v["truncated"]}
    adv = json.load(open(ADVISORIES))

    meta, sev_of = {}, {}
    for name, rows in adv.items():
        for r in rows:
            k = (name, r.get("id"))
            if k not in meta:
                pub = parse(r["published"]) if r.get("published") else None
                mod = parse(r["modified"]) if r.get("modified") else None
                meta[k] = (pub, mod)
                sev_of[k] = r.get("severity")

    def hits(name, ver):
        o = []
        for a in adv.get(name) or []:
            r = a.get("vulnerable_versions")
            if not r:
                continue
            try:
                if sv.satisfies(ver, r, loose=True, include_prerelease=True):
                    o.append(a.get("id"))
            except Exception:
                pass
        return o

    rows, live_only, no_date = [], [], []
    for root, v in s.items():
        if not v.get("root_published"):
            no_date.append(root)
            continue
        ship = parse(v["root_published"])
        fz, lv = {}, {}
        for x in v["published"]:
            n, ver = split(x)
            for i in hits(n, ver):
                fz.setdefault((n, i), ver)
        for x in v["installed"]:
            n, ver = split(x)
            for i in hits(n, ver):
                lv.setdefault((n, i), ver)
        for k, fver in fz.items():
            pub, mod = meta.get(k, (None, None))
            rows.append({"root": root, "package": k[0], "advisory": k[1],
                         "cell": "both" if k in lv else "frozen_only",
                         "category": classify(pub, mod, ship),
                         "gap_days": (pub - ship).days if pub else None,
                         # The day count truncates, so a 6-hour-late advisory
                         # reads as gap 0 while being post-ship. The category
                         # invariant needs the exact comparison, not the days.
                         "predates_ship": (pub <= ship) if pub else None,
                         "severity": sev_of.get(k),
                         "frozen_version": fver, "live_version": lv.get(k),
                         "root_published": v["root_published"]})
        for k, lver in lv.items():
            if k not in fz:
                pub, mod = meta.get(k, (None, None))
                live_only.append({"root": root, "package": k[0], "advisory": k[1],
                                  "cell": "live_only",
                                  "category": classify(pub, mod, ship)})
    return s, rows, live_only, no_date


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def gate(g, frozen_only, live_only, expected=None, rows=None, both=None):
    """Reproduce the published measurement, or refuse to go on.

    Three things are checked against each other, not two: the published numbers,
    the gap result file on disk, and what this run recomputed. Comparing the
    file to itself would pass while measuring nothing.
    """
    e = PUBLISHED if expected is None else expected
    checks = {
        "crosstab": (e["crosstab"], g["crosstab"]),
        "phantom_findings": (e["phantom_findings"], g["phantom_findings"]),
        "phantom_findings_recomputed": (e["phantom_findings"], len(frozen_only)),
        "missed_findings": (e["missed_findings"], g["missed_findings"]),
        "missed_findings_recomputed": (e["missed_findings"], len(live_only)),
        "phantom_trees": (e["phantom_trees"], g["phantom_trees"]),
        "phantom_trees_recomputed": (e["phantom_trees"],
                                     len({r["root"] for r in frozen_only})),
        "phantom_pairs": (e["phantom_pairs_tree_package"],
                          g["phantom_pairs_tree_package"]),
        "phantom_pairs_recomputed": (e["phantom_pairs_tree_package"],
                                     len({(r["root"], r["package"])
                                          for r in frozen_only})),
    }
    # The reported populations were outside the gate: a change that moved the
    # 4,638 and the both cell while leaving the frozen-only cell untouched went
    # through it unseen. Both are now pinned.
    if rows is not None:
        checks["all_frozen_side"] = (e["all_frozen_side"], len(rows))
    if both is not None:
        checks["both_arms_flag"] = (e["both_arms_flag"], len(both))
    for name, (want, got) in checks.items():
        require(want == got,
                f"reproduction gate failed on {name}: {want} != {got}")
    return len(checks)


def analyse():
    s, rows, live_only, no_date = collect()
    frozen_only = [r for r in rows if r["cell"] == "frozen_only"]
    both = [r for r in rows if r["cell"] == "both"]

    gate(json.load(open(GAP)), frozen_only, live_only, rows=rows, both=both)

    # The free invariant the review named, in its correct form: an advisory that
    # predates its root is exactly a pre-ship finding, so neither the sign of
    # the comparison nor the category assignment can drift unnoticed. Stated on
    # the exact timestamps, because the reported day count truncates: six
    # findings have a gap of 0 whole days while being post-ship by hours, and
    # the first form of this assertion fired on them.
    pre_exact = sum(1 for r in rows if r["predates_ship"])
    pre = sum(1 for r in rows if r["category"] in PRE_SHIP)
    require(pre_exact == pre,
            f"category invariant failed: {pre_exact} advisories predate their "
            f"root but {pre} are classed pre-ship")
    sub_day = sum(1 for r in rows if r["gap_days"] == 0 and not r["predates_ship"])

    # The pre-registered join includes prereleases, and nothing tested that it
    # was on. Dropping the flag left the frozen-only cell at exactly 4,442 while
    # moving the headline and every figure in the both cell, so the gate could
    # not see it. This checks the behaviour rather than a count.
    adv = json.load(open(ADVISORIES))
    probe = list(PROBE)
    require(all(adv.get(n) for n, _ in probe),
            "prerelease probe package is absent from the snapshot: re-point the "
            "probe at a package that still has a prerelease-only match rather "
            "than letting the check disappear")
    for n, v in probe:
        live = [a for a in adv[n]
                if sv.satisfies(v, a["vulnerable_versions"], loose=True,
                                include_prerelease=True)]
        plain = [a for a in adv[n]
                 if sv.satisfies(v, a["vulnerable_versions"], loose=True)]
        require(len(live) > len(plain),
                f"prerelease join probe is inert for {n}@{v}: the corpus no "
                "longer contains a prerelease-only match, so this check must be "
                "re-pointed at one that does")

    def table(rs, clustered=True):
        """A proportion never travels alone.

        The original protocol required a cluster interval and a leave-one-out
        beside every finding-level proportion, because five packages hold 82% of
        the findings. Two earlier runs reported the both-cell and young-cohort
        shares bare, and both turn out not to survive the interval. Attaching
        them here makes that impossible rather than remembered.
        """
        d = collections.Counter(r["category"] for r in rs)
        out = {"n": len(rs), "by_category": dict(sorted(d.items())),
               "post_ship_pct": round(share(rs), 1) if rs else None}
        if clustered and rs:
            boot = bootstrap_ci(rs, lambda r: r["package"])
            out["package_cluster_ci95"] = boot["ci95"]
            out["package_clusters"] = boot["clusters"]
            out["leave_out_densest"] = {
                "package": DENSEST,
                "n": sum(1 for r in rs if r["package"] != DENSEST),
                "post_ship_pct": (round(share([r for r in rs
                                               if r["package"] != DENSEST]), 1)
                                  if any(r["package"] != DENSEST for r in rs)
                                  else None)}
        return out

    # ---- the cell amendment two mistook for a publisher result ----
    # It is not one, and the reason is weaker than amendment two's wording.
    # Frequently the tree installs TWO versions of the flagged package, the
    # flagged one and a strictly newer one the advisory does not cover, so the
    # finding cannot be attributed to a single declared pin. Which copy the root
    # itself declared is NOT in the released data: the walk state keeps flat
    # (name, version) sets with no edges or depth, and nested_gap.py says it
    # does not model placement. So this counts duplicate copies and claims
    # nothing about parentage. No root is named in any reported quantity.
    still = [r for r in both if r["category"] == "pre_ship_stable"]
    still_roots = {r["root"] for r in still}
    still_pkgs = collections.Counter(r["package"] for r in still)
    still_sev = collections.Counter(r["severity"] or "none" for r in still)
    # "newer" and "not covered" were prose only; both are computed here, because
    # an OLDER second copy, or a second copy the same advisory covers, is not
    # this confound.
    dup_pairs, dup_findings, dup_newer_clean = set(), 0, 0
    adv_rows = json.load(open(ADVISORIES))
    for r in still:
        inst = {x.rpartition("@@")[2] for x in s[r["root"]]["installed"]
                if x.rpartition("@@")[0] == r["package"]}
        if len(inst) <= 1:
            continue
        dup_pairs.add((r["root"], r["package"]))
        dup_findings += 1
        rng = next((a["vulnerable_versions"] for a in adv_rows.get(r["package"], [])
                    if a.get("id") == r["advisory"]), None)
        for other in inst - {r["frozen_version"]}:
            try:
                newer = sv.gt(other, r["frozen_version"], loose=True)
                covered = sv.satisfies(other, rng, loose=True,
                                       include_prerelease=True) if rng else True
            except Exception:
                continue
            if newer and not covered:
                dup_newer_clean += 1
                break

    # ---- the cell free of BOTH fix-availability conditions ----
    # frozen_only conditions on a fix arriving after ship; both conditions on no
    # in-range fix existing even today. The behavioural question lives in
    # neither: a pre-ship advisory on a pin that later became fixable.
    unconditioned = [r for r in frozen_only if r["category"] in PRE_SHIP]

    # ---- tree-level, over both populations, because the protocol named one
    # and the findings come from the other ----
    def trees(rs):
        by = collections.defaultdict(set)
        for r in rs:
            by[r["root"]].add(r["category"])
        c = collections.Counter(next(iter(v)) if len(v) == 1 else "mixed"
                                for v in by.values())
        return {"trees": len(by), "by_category": dict(sorted(c.items()))}

    asof = parse(json.load(open(ADV_META))["source_mtime_utc"])
    young_roots = {r for r, v in s.items() if v.get("root_published")
                   and in_cohort(asof, parse(v["root_published"]))}
    young = [r for r in rows if r["root"] in young_roots]

    # ---- the age bands, which are the result ----
    # A finding exists only if its advisory is in the snapshot, so a root shipped
    # d days before it has a d-day window for a post-ship advisory and the whole
    # history of OSV for a pre-ship one. In expectation the share is therefore
    # non-decreasing in root age, which makes the pooled figure a property of the
    # corpus's age mix. OBSERVED it is not monotone: the 91-180 band sits below
    # the 31-90 band, the intervals overlap heavily, and the inversion is carried
    # by a handful of roots. Only the endpoints are a safe statement.
    age = {r: (asof - parse(v["root_published"])).days
           for r, v in s.items() if v.get("root_published")}
    BUCKETS = [(0, 30), (31, 90), (91, 180), (181, 365), (366, 10 ** 6)]
    gradient, bucketed = [], 0
    for lo, hi in BUCKETS:
        g = [r for r in rows if lo <= age.get(r["root"], -1) <= hi]
        bucketed += len(g)
        if g:
            gradient.append({"age_days_from": lo,
                             "age_days_to": None if hi > 10 ** 5 else hi,
                             **table(g)})
    # A root published after the snapshot has a negative age and falls in no
    # bucket. Silently dropping those rows would make the gradient's bands fail
    # to sum to the population they are drawn from, so the remainder is counted.
    outside = len(rows) - bucketed

    gaps = sorted(r["gap_days"] for r in rows if r["gap_days"] is not None)

    # the protocol's band is pre_ship_modified plus undated, not the first alone
    band = sum(1 for r in rows
               if r["category"] in ("pre_ship_modified", "undated"))
    band_pct = 100.0 * band / len(rows) if rows else 0.0

    # ---- the time-aligned arm, computed before the output is assembled ----
    aligned = {"state_file": os.path.basename(ALIGNED)}
    if os.path.exists(ALIGNED):
        a_s, a_rows, a_live, _ = collect(ALIGNED)
        a_fo = [r for r in a_rows if r["cell"] == "frozen_only"]
        a_both = [r for r in a_rows if r["cell"] == "both"]
        a_still = [r for r in a_both if r["category"] == "pre_ship_stable"]
        a_unc = [r for r in a_fo if r["category"] in PRE_SHIP]
        a_age = {r: (asof - parse(v["root_published"])).days
                 for r, v in a_s.items() if v.get("root_published")}
        a_grad = []
        for lo, hi in BUCKETS:
            g = [r for r in a_rows if lo <= a_age.get(r["root"], -1) <= hi]
            if g:
                a_grad.append({"age_days_from": lo, "n": len(g),
                               "post_ship_pct": round(share(g), 1)})
        aligned.update({
            "all_frozen_side_n": len(a_rows), "frozen_only_n": len(a_fo),
            "both_arms_flag_n": len(a_both), "live_only_n": len(a_live),
            "post_ship_pct": round(share(a_rows), 1) if a_rows else None,
            "age_bands": a_grad,
            "behavioural_findings": len(a_unc),
            "behavioural_servers": len({r["root"] for r in a_unc}),
            "behavioural_by_category": dict(sorted(collections.Counter(
                r["category"] for r in a_unc).items())),
            "pre_ship_and_never_moved_findings": len(a_still),
            "pre_ship_and_never_moved_servers": len({r["root"] for r in a_still}),
            "note": "the age bands are the figure that must not move; the two "
                    "cells' membership may, and if it does the cells are "
                    "walk-date dependent and are reported from both arms",
        })

    out = {
        "preregistration": "PREREGISTRATION-6.md (amendment four)",
        "headline": "the share is non-decreasing in root age IN EXPECTATION, "
                    "because a younger root has had less time to accrue "
                    "advisories; observed it is not monotone and the bands' "
                    "intervals overlap, so the bands are the result and the "
                    "pooled figure is a property of this corpus's age mix",
        "post_ship_share_by_root_age": gradient,
        "age_bands_are_monotone": all(
            a["post_ship_pct"] <= b["post_ship_pct"]
            for a, b in zip(gradient, gradient[1:])),
        "age_band_edges": [[lo, None if hi > 10 ** 5 else hi]
                           for lo, hi in BUCKETS],
        "findings_outside_every_age_bucket": outside,
        "all_frozen_side": dict(
            table(rows),
            caveat="age-exposure weighted; read the gradient, not this"),
        "by_cell": {
            "frozen_only": dict(table(frozen_only),
                                caveat="conditional on a fixed version inside the "
                                       "root's range published after the root "
                                       "shipped; post_ship is close to forced here"),
            "both_arms_flag": table(both),
            "live_only": table(live_only),
        },
        "pre_ship_and_never_moved": {
            "definition": "both arms flag, advisory published at or before the "
                          "root shipped and unchanged since. NOT a publisher "
                          "result: this cell requires that no in-range fix "
                          "exists even today, and the flagged copy is often a "
                          "nested older duplicate the root did not select.",
            "findings": len(still),
            "servers": len(still_roots),
            "servers_pct_of_corpus": round(100.0 * len(still_roots) / len(s), 1),
            "packages": len(still_pkgs),
            "frozen_version_equals_live_version": sum(
                1 for r in still if r["frozen_version"] == r["live_version"]),
            "findings_with_a_second_copy_installed": dup_findings,
            "root_package_pairs_total": len({(r["root"], r["package"])
                                             for r in still}),
            "root_package_pairs_with_a_second_copy": len(dup_pairs),
            "findings_whose_second_copy_is_newer_and_uncovered": dup_newer_clean,
            "what_this_does_not_establish": "which copy the root itself "
                                            "declared: the walk state carries "
                                            "no edges, so parentage is not in "
                                            "the released data",
            "by_severity": dict(sorted(still_sev.items())),
            "top_packages": sorted(still_pkgs.items(),
                                   key=lambda kv: (-kv[1], kv[0]))[:10],
        },
        "behavioural_answer": {
            "question": "do these servers ship pins already covered by a "
                        "published advisory, where a fix later became available?",
            "definition": "frozen-only cell (a fix arrived after ship) AND the "
                          "advisory predates the root; free of the "
                          "fix-availability condition carried by either cell",
            "findings": len(unconditioned),
            # 40% of the null is the indeterminate band, which the protocol says
            # is never merged into pre_ship_stable. Shown rather than pooled.
            "by_category": dict(sorted(collections.Counter(
                r["category"] for r in unconditioned).items())),
            "of_all_frozen_side": len(rows),
            "denominator": "all frozen-side findings",
            "pct": round(100.0 * len(unconditioned) / len(rows), 2) if rows else None,
            "servers": len({r["root"] for r in unconditioned}),
            "reading": "a null. A frozen tree over-reports because advisories "
                       "accrue against a fixed description, not because "
                       "publishers ship pins they could have avoided.",
        },
        "indeterminate_band_pct": round(band_pct, 1),
        "verdict": ("point_estimate" if band_pct <= 10 else
                    "bound_only" if band_pct <= 25 else "unestimable"),
        "trees_all_frozen_side": trees(rows),
        "trees_frozen_only": trees(frozen_only),
        "trees_note": ("trees_frozen_only is 164: the 130 frozen-flags-live-clean "
                       "trees plus the 34 both-flag trees whose advisory lists "
                       "differ. trees_all_frozen_side adds the 3 both-flag trees "
                       "whose lists are identical"),
        "young_cohort": {
            "days": YOUNG_DAYS, "asof": asof.isoformat(),
            "roots": len(young_roots),
            "roots_contributing_a_finding": len({r["root"] for r in young}),
            **table(young),
            "boundary": "advisory snapshot mtime minus root_published, the same "
                        "boundary code/nested_gap.py's age gradient uses",
            "not_comparable_with": "the published 56% for this cohort, which is "
                                   "the share of TREES carrying any frozen-only "
                                   "finding, not a finding-level share",
            "interpretation": "none drawn: the package-cluster interval does not "
                              "exclude a mostly pre-ship cohort, which is the "
                              "hinge the original protocol named",
        },
        "gap_days_advisory_published_minus_root_shipped": {
            "min": gaps[0] if gaps else None, "p10": pctile(gaps, 0.10),
            "median": pctile(gaps, 0.50), "p90": pctile(gaps, 0.90),
            "max": gaps[-1] if gaps else None,
            "advisories_predating_their_root": pre_exact,
            "published_within_24h_after_shipping": sub_day,
            "note": "the day count truncates, so a zero gap can be either side "
                    "of the ship time; the category uses the timestamps",
        },
        "pairs_by_category": {
            "unit": "(tree, package); a pair holding more than one category is "
                    "reported as mixed",
            **{k: v for k, v in sorted(collections.Counter(
                (lambda cs: next(iter(cs)) if len(cs) == 1 else "mixed")(
                    frozenset(x["category"] for x in rows
                              if (x["root"], x["package"]) == pr))
                for pr in {(r["root"], r["package"]) for r in rows}).items())},
        },
        "undated_sensitivity": {
            "undated_rows": sum(1 for r in rows if r["category"] == "undated"),
            "post_ship_pct_if_undated_called_post_ship": round(
                100.0 * sum(1 for r in rows if r["category"] in
                            ("post_ship", "undated")) / len(rows), 1) if rows else None,
            "post_ship_pct_if_undated_called_pre_ship": round(
                100.0 * sum(1 for r in rows if r["category"] == "post_ship")
                / len(rows), 1) if rows else None,
        },
        "cluster_robustness": {
            "note": "reported across units because no single one of them is the "
                    "binding dependence; scope approximates publisher and the "
                    "publisher map in this repository keys root packages, not "
                    "dependency packages, so it cannot be used here",
            "package": bootstrap_ci(rows, lambda r: r["package"]),
            "scope_as_publisher": dict(
                bootstrap_ci(rows, lambda r: cluster(r["package"], "scope")),
                caveat="degenerate on this corpus: it merges exactly one pair of "
                       "packages, so it is the package interval with two findings "
                       "moved, not a publisher-level check"),
            "root": bootstrap_ci(rows, lambda r: r["root"]),
            "package_advisory": dict(
                bootstrap_ci(rows, lambda r: (r["package"], r["advisory"])),
                caveat="FINER than package, so it splits the concentration the "
                       "protocol named as binding. Its tightness is not "
                       "robustness and must not be quoted as the uncertainty"),
        },
        # the leave-one-out now rides with every proportion, in table()
        # ---- the same cells against the time-aligned live arm ----
        # The published live arm was resolved a month after the advisory
        # snapshot, so membership of the two cells is partly a function of the
        # day the walk ran. This repository already carries an arm resolved at
        # the snapshot instant; both are reported rather than one chosen.
        "time_aligned_arm": aligned,
        "roots_excluded_no_publication_date": sorted(no_date),
        "provenance": {
            "python": sys.version.split()[0],
            "code_sha256": sha(os.path.abspath(__file__)),
            "advisories_sha256": sha(ADVISORIES),
            "state_sha256": sha(STATE),
            "gap_result_sha256": sha(GAP),
            "seed": SEED, "bootstrap_draws": BOOTSTRAP,
            # without these two a -O run is indistinguishable from a gated one
            "assertions_enabled": __debug__,
            "checks_run": len(CHECKS),
        },
    }
    return out


def main():
    out = analyse()
    json.dump(out, open(OUT, "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "provenance"}, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
