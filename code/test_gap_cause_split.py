#!/usr/bin/env python3
"""Tests for code/gap_cause_split.py, with mutations designed by two reviews.

WHY THE MUTATIONS ARE NOT MINE
    A self-authored mutation set measures the author's imagination. The 13 M-
    mutations were designed by an independent reviewer against the first version
    of this analysis and 10 of them left the headline within a rounding step. The
    10 N-mutations were designed by a second reviewer, which had not seen the
    first, against the version the first round produced: every one of them
    survived that suite, all aimed at output fields nothing pinned.

WHY A FIXTURE AND NOT THE CORPUS
    The corpus sits far from every boundary: no advisory is published at a ship
    instant, none has max(published, modified) equal to one, no root is exactly
    at the cohort edge, none is published after the snapshot, none is undated,
    and the indeterminate band never crosses the downgrade threshold. The fixture
    makes all six live.

ONE SOURCE OF TRUTH
    `EXPECT` is the hand-derived row table: one entry per finding the analysis
    should produce, with its cell, category and signed gap. Every scalar golden
    below is derived from it rather than copied from a run, so a wrong row
    cannot agree with a wrong total.

Run: python3 code/test_gap_cause_split.py
"""
import collections
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "gap_cause_split.py")

# ---------------------------------------------------------------- the fixture

ADVISORIES = {
    "alpha": [
        {"id": "A1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-01-01T00:00:00Z", "modified": "2026-01-01T00:00:00Z"},
        {"id": "A2", "severity": "low", "vulnerable_versions": ">=0.0.0 <3.0.0",
         "published": "2026-06-01T00:00:00Z", "modified": "2026-06-01T00:00:00Z"},
    ],
    # published long before R1 shipped, modified after: the only path into the
    # indeterminate band, and the one max(published, modified) exists for
    "beta": [
        {"id": "B1", "severity": "moderate", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2025-01-01T00:00:00Z", "modified": "2026-07-01T00:00:00Z"},
        # the same advisory a second time, as OSV does when one entry carries
        # several ranges. The first row must win.
        {"id": "B1", "severity": "moderate", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-07-15T00:00:00Z", "modified": "2026-07-15T00:00:00Z"},
    ],
    # modified EARLIER than published, the anomaly amendment one records
    "gamma": [
        {"id": "G1", "severity": "critical", "vulnerable_versions": ">=0.0.0 <9.0.0",
         "published": "2026-03-01T00:00:00Z", "modified": "2026-02-01T00:00:00Z"},
    ],
    # published at the exact instant R4 shipped: the `pub > ship` boundary
    "@scope/delta": [
        {"id": "D1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-05-01T00:00:00Z", "modified": "2026-05-01T00:00:00Z"},
    ],
    # max(published, modified) equals R5's ship instant: the `last > ship` boundary
    "epsilon": [
        {"id": "E1", "severity": "low", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-01-01T00:00:00Z", "modified": "2026-08-15T00:00:00Z"},
    ],
    "zeta": [
        {"id": "Z1", "severity": "high", "vulnerable_versions": ">=3.0.0 <4.0.0",
         "published": "2026-09-01T00:00:00Z", "modified": "2026-09-01T00:00:00Z"},
    ],
    "eta": [
        {"id": "H1", "severity": "moderate", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-09-08T00:00:00Z", "modified": "2026-09-08T00:00:00Z"},
    ],
    "theta": [
        {"id": "T1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2025-01-01T00:00:00Z", "modified": "2025-01-01T00:00:00Z"},
    ],
    "iota": [
        {"id": "I1", "severity": "low", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-09-01T00:00:00Z", "modified": "2026-09-01T00:00:00Z"},
    ],
    "kappa": [
        {"id": "K1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-01-01T00:00:00Z", "modified": "2026-01-01T00:00:00Z"},
    ],
    # matched only when the join includes prereleases
    "lambda": [
        {"id": "L1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-06-01T00:00:00Z", "modified": "2026-06-01T00:00:00Z"},
    ],
    # already published when R9 shipped, and R9's installed version MOVED but is
    # still covered: makes frozen_version == live_version falsifiable
    "nu": [
        {"id": "N1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-01-01T00:00:00Z", "modified": "2026-01-01T00:00:00Z"},
    ],
    # published before R1 shipped; R1 installs a second copy at 9.5.0, which is
    # newer AND outside the advisory. gamma's second copy is newer and still
    # covered, so the two rows separate the duplicate test from the clean test.
    "omicron": [
        {"id": "O1", "severity": "low", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2026-01-01T00:00:00Z", "modified": "2026-01-01T00:00:00Z"},
    ],
    # pre-ship but modified after R5 shipped, and the live arm has moved past
    # it: the only frozen-only row in the indeterminate band, which is what
    # makes the null's split falsifiable
    "pi": [
        {"id": "P1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": "2025-06-01T00:00:00Z", "modified": "2026-09-01T00:00:00Z"},
    ],
    # a second never-moved finding on a root that already has one, so the server
    # count and the pair count of that cell differ
    "rho": [
        {"id": "R1x", "severity": "moderate", "vulnerable_versions": ">=0.0.0 <9.0.0",
         "published": "2026-01-01T00:00:00Z", "modified": "2026-01-01T00:00:00Z"},
    ],
    # flagged identically by both arms, so R11's two sets are equal: a tree a
    # "skip trees whose arms agree" shortcut would silently drop
    "sigma": [
        {"id": "S1", "severity": "low", "vulnerable_versions": ">=0.0.0 <9.0.0",
         "published": "2026-09-01T00:00:00Z", "modified": "2026-09-01T00:00:00Z"},
    ],
    # no publication date at all: the undated category and its sensitivity
    "mu": [
        {"id": "U1", "severity": "moderate", "vulnerable_versions": ">=0.0.0 <2.0.0",
         "published": None, "modified": None},
    ],
}


def tree(ship, pub, inst):
    return {"root_version": "1.0.0", "root_published": ship, "truncated": False,
            "published": pub, "installed": inst}


ASOF = "2026-09-10T00:00:00Z"

STATE = {
    # frozen flags A1+A2+B1, live flags A2+B1: both_flag, lists differ
    "R1": tree("2026-04-01T00:00:00Z",
               ["alpha@@1.0.0", "beta@@1.0.0", "omicron@@1.0.0"],
               ["alpha@@2.5.0", "beta@@1.0.0", "omicron@@1.0.0",
                "omicron@@9.5.0"]),
    # both arms flag G1 on an unmoved version, and the tree carries a SECOND
    # copy of gamma, which is the confound that killed the publisher reading
    "R2": tree("2026-07-01T00:00:00Z",
               ["gamma@@1.0.0", "lambda@@1.0.0-rc.1", "rho@@1.0.0"],
               ["gamma@@1.0.0", "gamma@@2.0.0", "lambda@@2.0.0",
                "rho@@1.0.0"]),
    # carries the undated advisory alongside a dated one
    "R3": tree("2026-05-02T00:00:00Z",
               ["@scope/delta@@1.0.0", "mu@@1.0.0"],
               ["@scope/delta@@2.0.0", "mu@@2.0.0"]),
    "R4": tree("2026-05-01T00:00:00Z",
               ["@scope/delta@@1.0.0"], ["@scope/delta@@2.0.0"]),
    "R5": tree("2026-08-15T00:00:00Z", ["epsilon@@1.0.0", "pi@@1.0.0"],
               ["epsilon@@2.0.0", "pi@@2.0.0"]),
    # live flags what frozen does not: the missed side
    "R6": tree("2026-02-01T00:00:00Z", ["zeta@@1.0.0"], ["zeta@@3.0.0"]),
    "R7": tree("2026-09-05T00:00:00Z", ["eta@@1.0.0"], ["eta@@2.0.0"]),
    # 31 days old: one day outside the cohort
    "R8": tree("2026-08-10T00:00:00Z", ["theta@@1.0.0"], ["theta@@2.0.0"]),
    # exactly 30 days old: the inclusive edge of the cohort
    "R9": tree("2026-08-11T00:00:00Z", ["iota@@1.0.0", "nu@@1.0.0"],
               ["iota@@2.0.0", "nu@@1.5.0"]),
    # published AFTER the snapshot: negative age, excluded by the lower bound
    "R10": tree("2026-09-20T00:00:00Z", ["kappa@@1.0.0"], ["kappa@@2.0.0"]),
    # both arms flag the identical set: the tree a skip-if-equal bug would drop
    "R11": tree("2026-06-01T00:00:00Z", ["sigma@@1.0.0"], ["sigma@@1.0.0"]),
}

ADV_META = {"source_mtime_utc": ASOF}

# ---- the hand-derived row table: (root, package, advisory, cell, category, gap)
EXPECT = [
    ("R1", "alpha", "A1", "frozen_only", "pre_ship_stable", -90),
    ("R1", "alpha", "A2", "both", "post_ship", 61),
    ("R1", "beta", "B1", "both", "pre_ship_modified", -455),
    ("R1", "omicron", "O1", "both", "pre_ship_stable", -90),
    ("R2", "gamma", "G1", "both", "pre_ship_stable", -122),
    ("R2", "lambda", "L1", "frozen_only", "pre_ship_stable", -30),
    ("R2", "rho", "R1x", "both", "pre_ship_stable", -181),
    ("R3", "@scope/delta", "D1", "frozen_only", "pre_ship_stable", -1),
    ("R3", "mu", "U1", "frozen_only", "undated", None),
    ("R4", "@scope/delta", "D1", "frozen_only", "pre_ship_stable", 0),
    ("R5", "epsilon", "E1", "frozen_only", "pre_ship_stable", -226),
    ("R5", "pi", "P1", "frozen_only", "pre_ship_modified", -440),
    ("R7", "eta", "H1", "frozen_only", "post_ship", 3),
    ("R8", "theta", "T1", "frozen_only", "pre_ship_stable", -586),
    ("R9", "iota", "I1", "frozen_only", "post_ship", 21),
    ("R9", "nu", "N1", "both", "pre_ship_stable", -222),
    ("R10", "kappa", "K1", "frozen_only", "pre_ship_stable", -262),
    ("R11", "sigma", "S1", "both", "post_ship", 92),
]
EXPECT_LIVE_ONLY = [("R6", "zeta", "Z1", "post_ship")]

# cohort membership, hand-derived from ASOF: R5 26d, R7 5d, R9 exactly 30d in;
# R8 31d and R10 negative out
YOUNG = {"R5", "R7", "R9"}


def _cats(rows):
    return dict(sorted(collections.Counter(r[4] for r in rows).items()))


def _share(rows):
    n = sum(1 for r in rows if r[4] != "undated")
    return round(100.0 * sum(1 for r in rows if r[4] == "post_ship") / n, 1) if n else None


FROZEN_ONLY = [r for r in EXPECT if r[3] == "frozen_only"]
BOTH = [r for r in EXPECT if r[3] == "both"]
_gaps = sorted(r[5] for r in EXPECT if r[5] is not None)
_band = sum(1 for r in EXPECT if r[4] in ("pre_ship_modified", "undated"))

GAP = {"crosstab": {"frozen_flags_live_clean": 6, "live_flags_frozen_clean": 1,
                    "both_flag": 4, "both_flag_lists_differ": 3,
                    "both_flag_lists_identical": 1, "neither_flags": 0},
       "phantom_findings": len(FROZEN_ONLY),
       "missed_findings": len(EXPECT_LIVE_ONLY),
       "phantom_trees": len({r[0] for r in FROZEN_ONLY}),
       "phantom_pairs_tree_package": len({(r[0], r[1]) for r in FROZEN_ONLY})}
EXPECTED = dict(GAP, all_frozen_side=len(EXPECT), both_arms_flag=len(BOTH))

GOLD = {
    "all_n": len(EXPECT), "all_cats": _cats(EXPECT), "all_pct": _share(EXPECT),
    "fo_n": len(FROZEN_ONLY), "fo_pct": _share(FROZEN_ONLY),
    "both_n": len(BOTH), "both_pct": _share(BOTH),
    "live_only_n": len(EXPECT_LIVE_ONLY),
    "young_roots": len(YOUNG),
    "young_n": sum(1 for r in EXPECT if r[0] in YOUNG),
    "young_pct": _share([r for r in EXPECT if r[0] in YOUNG]),
    "predates": sum(1 for r in EXPECT if r[4] in
                    ("pre_ship_stable", "pre_ship_modified")),
    "gap_min": _gaps[0], "gap_max": _gaps[-1],
    "gap_median": _gaps[min(int(0.5 * len(_gaps)), len(_gaps) - 1)],
    "gap_p10": _gaps[min(int(0.10 * len(_gaps)), len(_gaps) - 1)],
    "gap_p90": _gaps[min(int(0.90 * len(_gaps)), len(_gaps) - 1)],
    "band_pct": round(100.0 * _band / len(EXPECT), 1),
    # 15.4% is above the protocol's 10% threshold and below 25%, so the fixture
    # exercises the downgrade rule, which the real corpus never does
    "verdict": "bound_only",
    "undated_rows": sum(1 for r in EXPECT if r[4] == "undated"),
    "leave_out_alpha_n": sum(1 for r in EXPECT if r[1] != "alpha"),
    "leave_out_alpha_pct": _share([r for r in EXPECT if r[1] != "alpha"]),
    "behavioural_n": sum(1 for r in FROZEN_ONLY if r[4] in
                         ("pre_ship_stable", "pre_ship_modified")),
    "behavioural_servers": len({r[0] for r in FROZEN_ONLY if r[4] in
                                ("pre_ship_stable", "pre_ship_modified")}),
    "still_n": sum(1 for r in BOTH if r[4] == "pre_ship_stable"),
    "still_servers": len({r[0] for r in BOTH if r[4] == "pre_ship_stable"}),
    # R2's G1 is on an unmoved version; R9's N1 is on one that moved and is
    # still covered. Equal to still_n would mean the check cannot fail.
    # G1, O1 and R1x are on unmoved versions, N1 is not
    "still_unmoved": 3,
    # R2's gamma and R1's omicron both have a second copy installed, but only
    # omicron's is outside the advisory, so the two counts must differ
    "still_dup_findings": 2,
    "still_dup_newer_clean": 1,
    "still_dup_pairs": 2,
    "cluster_counts": (len({r[1] for r in EXPECT}), len({r[0] for r in EXPECT}),
                       len({r[1].split("/")[0] if r[1].startswith("@") else r[1]
                            for r in EXPECT})),
    "pairs": None,               # derived in the test from EXPECT
    "package_ci95": (7.14, 44.44),
    "boot_ci95": (80.0, 97.5),
}

FAILS = []
RAN = collections.Counter()


def check(name, got, want):
    RAN[name] += 1
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")
    return got == want


def load(src=None):
    """Import the module (optionally a mutated source) against the fixture."""
    d = tempfile.mkdtemp()
    data = os.path.join(d, "data")
    os.makedirs(data, exist_ok=True)
    json.dump(ADVISORIES, open(os.path.join(data, "adv.json"), "w"))
    json.dump(STATE, open(os.path.join(data, "state.json"), "w"))
    json.dump(ADV_META, open(os.path.join(data, "meta.json"), "w"))
    json.dump(GAP, open(os.path.join(data, "gap.json"), "w"))
    os.environ.update({
        "GAP_STATE": os.path.join(data, "state.json"),
        "ADVISORIES": os.path.join(data, "adv.json"),
        "ADVISORY_META": os.path.join(data, "meta.json"),
        "GAP_RESULT": os.path.join(data, "gap.json"),
        "CAUSE_OUT": os.path.join(data, "out.json"),
        # the aligned arm reads a second state file; pointing it at the same
        # fixture makes the branch run and its figures equal the main ones
        "GAP_STATE_ALIGNED": os.path.join(data, "state.json"),
        "BOOTSTRAP": "200",
    })
    path = os.path.join(d, "mod_under_test.py")
    open(path, "w").write(src if src is not None else open(MODULE).read())
    spec = importlib.util.spec_from_file_location("mod_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.PUBLISHED = dict(EXPECTED)
    # lambda@1.0.0-rc.1 matches L1 only when prereleases are included
    m.PROBE = (("lambda", "1.0.0-rc.1"),)
    return m


# ------------------------------------------------------- unit level, the parser

def test_parse(m):
    ok = ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00.5Z",
          "2026-01-01T00:00:00.495290489Z", "2026-01-01T00:00:00+00:00",
          "2026-01-01T00:00:00.495290489-07:00", "2026-01-01T00:00:00+0530",
          "2026-01-01 00:00:00Z"]
    for s in ok:
        try:
            v = m.parse(s)
            check(f"parse accepts {s}", v.tzinfo is not None, True)
        except Exception as e:
            check(f"parse accepts {s}", f"raised {e}", "parsed")
    # nine fractional digits must not be truncated into a different instant
    check("parse keeps microseconds",
          m.parse("2026-01-01T00:00:00.495290489Z").microsecond, 495290)
    # the defect this parser exists for: an unreadable date must raise, never
    # return None, because the change test reads None as "absent"
    for s in [None, "", "2026-01-01T00:00:00", "not a date",
              "2026-13-01T00:00:00Z", "2026-01-01"]:
        try:
            m.parse(s)
            check(f"parse rejects {s!r}", "returned", "raised")
        except m.BadTimestamp:
            check(f"parse rejects {s!r}", "raised", "raised")
        except Exception as e:
            check(f"parse rejects {s!r}", f"wrong error {type(e).__name__}",
                  "raised")


def test_classify(m):
    p = m.parse
    ship = p("2026-05-01T00:00:00Z")
    check("classify post_ship",
          m.classify(p("2026-05-01T00:00:01Z"), p("2026-05-01T00:00:01Z"), ship),
          "post_ship")
    # the boundary the first version never exercised: published == shipped
    check("classify boundary pub == ship",
          m.classify(ship, ship, ship), "pre_ship_stable")
    check("classify boundary pub one second before",
          m.classify(p("2026-04-30T23:59:59Z"), p("2026-04-30T23:59:59Z"), ship),
          "pre_ship_stable")
    # the second boundary: max(published, modified) == shipped
    check("classify boundary last == ship",
          m.classify(p("2026-01-01T00:00:00Z"), ship, ship), "pre_ship_stable")
    check("classify boundary last one second after",
          m.classify(p("2026-01-01T00:00:00Z"), p("2026-05-01T00:00:01Z"), ship),
          "pre_ship_modified")
    # max, not min: amendment one item 2
    check("classify uses max(published, modified)",
          m.classify(p("2025-01-01T00:00:00Z"), p("2026-07-01T00:00:00Z"), ship),
          "pre_ship_modified")
    # modified earlier than published must not drag the row into the band
    check("classify tolerates modified < published",
          m.classify(p("2026-03-01T00:00:00Z"), p("2026-02-01T00:00:00Z"), ship),
          "pre_ship_stable")
    check("classify undated", m.classify(None, None, ship), "undated")
    check("classify missing modified",
          m.classify(p("2026-01-01T00:00:00Z"), None, ship), "pre_ship_stable")


def test_share(m):
    rows = [{"category": "post_ship"}, {"category": "pre_ship_stable"},
            {"category": "undated"}, {"category": "undated"}]
    # the protocol excludes undated from the denominator
    check("share excludes undated from the denominator", m.share(rows), 50.0)
    check("share of an empty set is None", m.share([]), None)


def test_cluster_and_pctile(m):
    check("cluster package", m.cluster("@scope/delta", "package"), "@scope/delta")
    check("cluster scope", m.cluster("@scope/delta", "scope"), "@scope")
    check("cluster scope of unscoped", m.cluster("alpha", "scope"), "alpha")
    check("pctile low", m.pctile([1, 2, 3, 4], 0.0), 1)
    check("pctile high", m.pctile([1, 2, 3, 4], 0.975), 4)


def test_bootstrap_percentiles(m):
    """The interval must be the 2.5th to 97.5th percentile, not some other pair."""
    rows = ([{"category": "post_ship", "k": i} for i in range(36)] +
            [{"category": "pre_ship_stable", "k": 100 + i} for i in range(4)])
    r = m.bootstrap_ci(rows, lambda x: x["k"], draws=4000, seed=7)
    check("bootstrap cluster count", r["clusters"], 40)
    check("bootstrap draw count", r["draws"], 4000)
    check("bootstrap interval is the pinned 95%", tuple(r["ci95"]),
          GOLD["boot_ci95"])
    # a one-cluster input cannot vary, so the interval must collapse
    one = m.bootstrap_ci([{"category": "post_ship", "k": 1}], lambda x: x["k"],
                         draws=50, seed=7)
    check("bootstrap on one cluster collapses", tuple(one["ci95"]), (100.0, 100.0))


def test_gate(m):
    fo = [{"root": r[0], "package": r[1]} for r in FROZEN_ONLY]
    lo = [{"root": r[0]} for r in EXPECT_LIVE_ONLY]
    allrows = [{"root": r[0]} for r in EXPECT]
    bothrows = [{"root": r[0]} for r in BOTH]
    try:
        m.gate(GAP, fo, lo, EXPECTED, rows=allrows, both=bothrows)
        check("gate passes on agreement", "passed", "passed")
    except (m.GateFailed, AssertionError) as e:
        check("gate passes on agreement", f"raised {e}", "passed")
    # the populations the gate used to omit
    try:
        m.gate(GAP, fo, lo, EXPECTED, rows=allrows[:-1], both=bothrows)
        check("gate fires on the headline population", "passed", "raised")
    except (m.GateFailed, AssertionError):
        check("gate fires on the headline population", "raised", "raised")
    try:
        m.gate(GAP, fo, lo, EXPECTED, rows=allrows, both=bothrows[:-1])
        check("gate fires on the both cell", "passed", "raised")
    except (m.GateFailed, AssertionError):
        check("gate fires on the both cell", "raised", "raised")
    bad = dict(GAP, phantom_findings=7)
    try:
        m.gate(bad, fo, lo, EXPECTED)
        check("gate fires when the file disagrees", "passed", "raised")
    except (m.GateFailed, AssertionError):
        check("gate fires when the file disagrees", "raised", "raised")
    try:
        m.gate(GAP, fo[:-1], lo, EXPECTED)
        check("gate fires when the recomputation disagrees", "passed", "raised")
    except (m.GateFailed, AssertionError):
        check("gate fires when the recomputation disagrees", "raised", "raised")


# -------------------------------------------------------- end to end, the split

def test_collect_rows(m):
    """Every finding, by row, against the hand-derived table."""
    s, rows, live_only, no_date = m.collect()
    got = sorted((r["root"], r["package"], r["advisory"], r["cell"],
                  r["category"], r["gap_days"]) for r in rows)
    check("collect returns exactly the expected rows", got, sorted(EXPECT))
    gl = sorted((r["root"], r["package"], r["advisory"], r["category"])
                for r in live_only)
    check("live-only rows", gl, sorted(EXPECT_LIVE_ONLY))
    check("no root is dropped for a missing date", no_date, [])
    # the prerelease join: lambda@1.0.0-rc.1 matches only with the flag on
    check("prerelease version is joined",
          ("R2", "lambda", "L1", "frozen_only", "pre_ship_stable", -30) in got,
          True)
    check("predates_ship agrees with the category",
          sum(1 for r in rows if r["predates_ship"]), GOLD["predates"])


def test_in_cohort(m):
    p = m.parse
    asof = p(ASOF)
    check("cohort includes the exact edge",
          m.in_cohort(asof, p("2026-08-11T00:00:00Z")), True)
    check("cohort excludes one day past the edge",
          m.in_cohort(asof, p("2026-08-10T00:00:00Z")), False)
    check("cohort includes the snapshot day itself",
          m.in_cohort(asof, p(ASOF)), True)
    check("cohort excludes a root published after the snapshot",
          m.in_cohort(asof, p("2026-09-20T00:00:00Z")), False)


def test_analyse(m):
    m.DENSEST = "alpha"
    out = m.analyse()
    a = out["all_frozen_side"]
    check("all frozen-side n", a["n"], GOLD["all_n"])
    check("all frozen-side categories", a["by_category"], GOLD["all_cats"])
    check("all frozen-side pct", a["post_ship_pct"], GOLD["all_pct"])
    check("all frozen-side carries an interval",
          isinstance(a.get("package_cluster_ci95"), list), True)
    check("all frozen-side carries a leave-one-out",
          a["leave_out_densest"]["n"], GOLD["leave_out_alpha_n"])
    check("leave-one-out percentage", a["leave_out_densest"]["post_ship_pct"],
          GOLD["leave_out_alpha_pct"])
    fo, bo = out["by_cell"]["frozen_only"], out["by_cell"]["both_arms_flag"]
    check("frozen-only n", fo["n"], GOLD["fo_n"])
    check("frozen-only pct", fo["post_ship_pct"], GOLD["fo_pct"])
    check("both-arms n", bo["n"], GOLD["both_n"])
    check("both-arms pct", bo["post_ship_pct"], GOLD["both_pct"])
    # the rule two earlier runs broke: no finding-level proportion travels bare
    for name, cell in (("frozen_only", fo), ("both_arms_flag", bo),
                       ("young_cohort", out["young_cohort"])):
        check(f"{name} carries an interval",
              isinstance(cell.get("package_cluster_ci95"), list), True)
        check(f"{name} carries a leave-one-out",
              "leave_out_densest" in cell, True)
    check("live-only n", out["by_cell"]["live_only"]["n"], GOLD["live_only_n"])
    check("cells partition the frozen side", fo["n"] + bo["n"], a["n"])

    b = out["behavioural_answer"]
    check("behavioural findings", b["findings"], GOLD["behavioural_n"])
    check("behavioural servers", b["servers"], GOLD["behavioural_servers"])
    check("behavioural denominator is the whole frozen side",
          b["of_all_frozen_side"], GOLD["all_n"])
    check("behavioural percentage over that denominator", b["pct"],
          round(100.0 * GOLD["behavioural_n"] / GOLD["all_n"], 2))
    check("the null is split, not pooled", b["by_category"],
          dict(sorted(collections.Counter(
              r[4] for r in FROZEN_ONLY
              if r[4] in ("pre_ship_stable", "pre_ship_modified")).items())))
    check("the null names its denominator", "denominator" in b, True)

    st = out["pre_ship_and_never_moved"]
    check("never-moved findings", st["findings"], GOLD["still_n"])
    check("never-moved servers", st["servers"], GOLD["still_servers"])
    check("unmoved-version count is not a tautology",
          st["frozen_version_equals_live_version"], GOLD["still_unmoved"])
    check("second-copy findings counted",
          st["findings_with_a_second_copy_installed"], GOLD["still_dup_findings"])
    check("second-copy pairs counted",
          st["root_package_pairs_with_a_second_copy"], GOLD["still_dup_pairs"])
    check("never-moved package count", st["packages"],
          len({r[1] for r in BOTH if r[4] == "pre_ship_stable"}))
    sev = collections.Counter()
    for r in BOTH:
        if r[4] == "pre_ship_stable":
            sev[next(x["severity"] for x in ADVISORIES[r[1]]
                     if x["id"] == r[2]) or "none"] += 1
    check("never-moved severities come from this cell only",
          st["by_severity"], dict(sorted(sev.items())))
    pk = collections.Counter(r[1] for r in BOTH if r[4] == "pre_ship_stable")
    check("top packages are package-keyed and ranked",
          [list(x) for x in st["top_packages"]],
          [list(x) for x in sorted(pk.items(), key=lambda kv: (-kv[1], kv[0]))])
    check("never-moved server percentage", st["servers_pct_of_corpus"],
          round(100.0 * GOLD["still_servers"] / len(STATE), 1))
    check("no root is named in the output", "roots" in st, False)
    check("pair total is the pair unit, not the server count",
          st["root_package_pairs_total"],
          len({(r[0], r[1]) for r in BOTH if r[4] == "pre_ship_stable"}))
    check("the newer-and-uncovered property is computed, not asserted in prose",
          st["findings_whose_second_copy_is_newer_and_uncovered"],
          GOLD["still_dup_newer_clean"])
    check("the cell says what it does not establish",
          "what_this_does_not_establish" in st, True)

    y = out["young_cohort"]
    check("young roots", y["roots"], GOLD["young_roots"])
    check("young contributing roots", y["roots_contributing_a_finding"],
          len({r[0] for r in EXPECT if r[0] in YOUNG}))
    check("young n", y["n"], GOLD["young_n"])
    check("young pct", y["post_ship_pct"], GOLD["young_pct"])

    def tree_table(rs):
        by = collections.defaultdict(set)
        for r in rs:
            by[r[0]].add(r[4])
        c = collections.Counter(next(iter(v)) if len(v) == 1 else "mixed"
                                for v in by.values())
        return {"trees": len(by), "by_category": dict(sorted(c.items()))}
    check("tree table over all frozen-side findings",
          out["trees_all_frozen_side"], tree_table(EXPECT))
    check("tree table over the frozen-only cell",
          out["trees_frozen_only"], tree_table(FROZEN_ONLY))

    check("band edges are pinned", out["age_band_edges"],
          [[0, 30], [31, 90], [91, 180], [181, 365], [366, None]])
    mono = all(a["post_ship_pct"] <= b["post_ship_pct"] for a, b in
               zip(out["post_ship_share_by_root_age"],
                   out["post_ship_share_by_root_age"][1:]))
    check("the monotonicity flag states what the bands do",
          out["age_bands_are_monotone"], mono)

    gr = out["post_ship_share_by_root_age"]
    check("gradient has more than one band", len(gr) >= 2, True)
    # R10 was published after the snapshot, so its finding falls in no bucket
    check("gradient bands plus the remainder account for every row",
          sum(x["n"] for x in gr) + out["findings_outside_every_age_bucket"],
          GOLD["all_n"])
    check("out-of-bucket rows are counted, not dropped",
          out["findings_outside_every_age_bucket"],
          sum(1 for r in EXPECT if r[0] == "R10"))
    check("every gradient band carries an interval",
          all(isinstance(x.get("package_cluster_ci95"), list) for x in gr), True)

    g = out["gap_days_advisory_published_minus_root_shipped"]
    for k, gk in (("min", "gap_min"), ("median", "gap_median"),
                  ("max", "gap_max"), ("p10", "gap_p10"), ("p90", "gap_p90")):
        check(f"gap {k}", g[k], GOLD[gk])
    check("advisories predating their root", g["advisories_predating_their_root"],
          GOLD["predates"])

    check("band percentage", out["indeterminate_band_pct"], GOLD["band_pct"])
    check("downgrade rule fires", out["verdict"], GOLD["verdict"])
    us = out["undated_sensitivity"]
    check("undated rows", us["undated_rows"], GOLD["undated_rows"])
    check("undated sensitivity moves the figure",
          us["post_ship_pct_if_undated_called_post_ship"] !=
          us["post_ship_pct_if_undated_called_pre_ship"], True)

    pairs = collections.Counter()
    for pr in {(r[0], r[1]) for r in EXPECT}:
        cs = {r[4] for r in EXPECT if (r[0], r[1]) == pr}
        pairs[next(iter(cs)) if len(cs) == 1 else "mixed"] += 1
    check("pair-level split", {k: v for k, v in out["pairs_by_category"].items()
                               if k != "unit"}, dict(sorted(pairs.items())))

    cr = out["cluster_robustness"]
    check("cluster counts are the unit's own",
          (cr["package"]["clusters"], cr["root"]["clusters"],
           cr["scope_as_publisher"]["clusters"]), GOLD["cluster_counts"])
    ivals = [tuple(cr[u]["ci95"]) for u in
             ("package", "scope_as_publisher", "root", "package_advisory")]
    check("cluster units give different intervals", len(set(ivals)) > 1, True)
    check("package interval is the pinned one", tuple(cr["package"]["ci95"]),
          GOLD["package_ci95"])
    for u in ("scope_as_publisher", "package_advisory"):
        check(f"{u} carries its caveat", "caveat" in cr[u], True)

    al = out["time_aligned_arm"]
    check("the aligned arm runs", al.get("all_frozen_side_n"), GOLD["all_n"])
    check("the aligned arm reports the bands",
          [x["n"] for x in al["age_bands"]], [x["n"] for x in gr])
    check("the aligned arm reports both cells separately",
          (al["behavioural_findings"], al["pre_ship_and_never_moved_findings"]),
          (GOLD["behavioural_n"], GOLD["still_n"]))
    # the hedges are the claim; nothing used to assert they were present
    check("the pooled figure carries its caveat",
          "age-exposure" in out["all_frozen_side"]["caveat"], True)
    check("the frozen-only cell carries its caveat",
          "close to forced" in out["by_cell"]["frozen_only"]["caveat"], True)
    check("the null is labelled a null", "a null" in b["reading"], True)
    check("the confound is labelled not a publisher result",
          "NOT a publisher result" in st["definition"], True)
    check("the interval names its cluster unit",
          out["all_frozen_side"]["package_clusters"],
          len({r[1] for r in EXPECT}))

    pv = out["provenance"]
    check("provenance records the interpreter",
          pv["python"] == sys.version.split()[0], True)
    check("provenance records whether checks ran", pv["assertions_enabled"], True)
    check("provenance records how many ran", pv["checks_run"] > 0, True)
    for k in ("code_sha256", "advisories_sha256", "state_sha256",
              "gap_result_sha256"):
        check(f"provenance records {k}", len(pv[k]), 64)
    return out
# ------------------------------------------------------- the mutation campaign

# (name, old, new, what the reviewer measured on the real corpus)
MUTATIONS = [
    ("M1 boundary pub >= ship", "    if pub > ship:", "    if pub >= ship:",
     "no change on the real corpus: no advisory is published at a ship instant"),
    ("M2 boundary last >= ship",
     'return "pre_ship_modified" if last > ship else "pre_ship_stable"',
     'return "pre_ship_modified" if last >= ship else "pre_ship_stable"',
     "no change on the real corpus, same reason"),
    ("M3 min for max in the change test",
     "last = max(pub, mod) if mod is not None else pub",
     "last = min(pub, mod) if mod is not None else pub",
     "band 4 -> 0, pre_ship_stable 6 -> 10, headline unmoved"),
    ("M4 swapped date operands", "    if pub > ship:", "    if ship > pub:",
     "post_ship 99.8% -> 0.2%, loud"),
    ("M5 swapped classify arguments",
     '"category": classify(pub, mod, ship),\n                         "gap_days"',
     '"category": classify(mod, pub, ship),\n                         "gap_days"',
     "99.8 -> 99.9, reads as a rounding wobble"),
    ("M6 inverted gap sign", '"gap_days": (pub - ship).days if pub else None,',
     '"gap_days": (ship - pub).days if pub else None,',
     "median +74 -> -75, every category untouched"),
    ("M7 cohort boundary on the wrong date",
     'asof = parse(json.load(open(ADV_META))["source_mtime_utc"])',
     'asof = max(parse(v["root_published"]) for v in s.values()'
     ' if v.get("root_published"))',
     "cohort 75 -> 76 roots, rounded percentage unmoved"),
    ("M8 bootstrap resamples findings, not clusters",
     "        for nm in rnd.choices(names, k=len(names)):\n"
     "            draw.extend(by[nm])",
     "        draw = rnd.choices(rows, k=len(rows))",
     "interval narrows and looks better: pseudo-replication"),
    ("M9 ninety percent interval labelled ninety-five",
     'vals, 0.025), 2),\n                     round(pctile(vals, 0.975)',
     'vals, 0.05), 2),\n                     round(pctile(vals, 0.95)',
     "bounds move inward, field name still says ci95"),
    ("M10 leave-one-out keyed on the root",
     '"n": sum(1 for r in rs if r["package"] != DENSEST),',
     '"n": sum(1 for r in rs if r["root"] != DENSEST),',
     "the hono sensitivity silently becomes a no-op"),
    ("M11 pair unit keyed on the advisory",
     '(r["root"], r["package"])\n                                          for r in frozen_only})',
     '(r["root"], r["advisory"])\n                                          for r in frozen_only})',
     "pairs 906 -> 4,439, caught only if 906 is checked"),
    ("M12 band dropped from the denominator",
     'n = sum(v for k, v in d.items() if k != "undated")',
     'n = d["post_ship"] + d["pre_ship_stable"]',
     "99.8 -> 99.9 while the output still states a band"),
    ("M13 last advisory row wins over the first", "            if k not in meta:",
     "            if True:",
     "no change today; live the moment OSV emits per-range timestamps"),
]

# Mutations of the checking machinery itself. A harness mutation alone leaves a
# suite green by construction, so each is paired with a defect only the disabled
# layer would have caught.
# The second review designed these against the version the first round
# produced. Every one of them survived that suite, all aimed at output fields
# nothing pinned.
MUTATIONS += [
    ("N1 server percentage over the wrong denominator",
     '"servers_pct_of_corpus": round(100.0 * len(still_roots) / len(s), 1),',
     '"servers_pct_of_corpus": round(100.0 * len(still_roots)'
     ' / len({r["root"] for r in rows}), 1),',
     "5.2% -> 7.8% on the real corpus"),
    ("N2 package counter keyed on the pair",
     'still_pkgs = collections.Counter(r["package"] for r in still)',
     'still_pkgs = collections.Counter((r["package"], r["root"]) for r in still)',
     "18 packages -> 24, and top_packages becomes pair-keyed"),
    ("N3 severities taken from the wrong cell",
     'still_sev = collections.Counter(r["severity"] or "none" for r in still)',
     'still_sev = collections.Counter(r["severity"] or "none" for r in both)',
     "38 high, 3 critical -> 109 high, 6 critical"),
    ("N4 mixed trees relabelled post_ship",
     'c = collections.Counter(next(iter(v)) if len(v) == 1 else "mixed"',
     'c = collections.Counter(next(iter(v)) if len(v) == 1 else'
     ' ("post_ship" if "post_ship" in v else "mixed")',
     "148 post / 18 mixed -> 166 post / 0 mixed"),
    ("N5 band counted over the wrong population",
     'band = sum(1 for r in rows\n               if r["category"] in'
     ' ("pre_ship_modified", "undated"))',
     'band = sum(1 for r in frozen_only\n               if r["category"] in'
     ' ("pre_ship_modified", "undated"))',
     "band 0.3% -> 0.1%, the input to the downgrade rule"),
    ("N6 cohort edge made exclusive",
     "return 0 <= d <= (YOUNG_DAYS if days is None else days)",
     "return 0 <= d < (YOUNG_DAYS if days is None else days)",
     "75 roots -> 73, breaking the claimed alignment with nested_gap.py"),
    ("N7 prerelease dropped from the advisory join",
     "if sv.satisfies(ver, r, loose=True, include_prerelease=True):",
     "if sv.satisfies(ver, r, loose=True):",
     "frozen_only stays 4,442 so the gate passed; 4,638 -> 4,616, "
     "58 -> 44, 13 servers -> 11"),
    ("N8 p10 computed at the p90 quantile",
     '"min": gaps[0] if gaps else None, "p10": pctile(gaps, 0.10),',
     '"min": gaps[0] if gaps else None, "p10": pctile(gaps, 0.90),',
     "p10 +14 -> +192, equal to p90"),
    ("N9 the reported share is the wrong category",
     '"post_ship_pct": round(share(rs), 1) if rs else None}',
     '"post_ship_pct": round(share(rs, "pre_ship_stable"), 1) if rs else None}',
     "every percentage becomes its complement under an unchanged key name"),
    ("N10 young cohort over the withdrawn population",
     'young = [r for r in rows if r["root"] in young_roots]',
     'young = [r for r in frozen_only if r["root"] in young_roots]',
     "318 / 90.6% -> 289 / 98.3%, the figure the population switch moves most"),
    ("N11 unmoved check compares a version with itself",
     '1 for r in still if r["frozen_version"] == r["live_version"]),',
     '1 for r in still if r["frozen_version"] == r["frozen_version"]),',
     "the check becomes a tautology and can never fail"),
    ("N12 duplicate copies looked for in the frozen tree",
     'inst = {x.rpartition("@@")[2] for x in s[r["root"]]["installed"]',
     'inst = {x.rpartition("@@")[2] for x in s[r["root"]]["published"]',
     "the confound count is taken from the wrong arm"),
]

# A third review, scoped to the restated claims, found these six. Each left the
# whole suite AND the reproduction gate green on the version it reviewed.
MUTATIONS += [
    ("MA bucket edges shifted by one day",
     "BUCKETS = [(0, 30), (31, 90), (91, 180), (181, 365), (366, 10 ** 6)]",
     "BUCKETS = [(0, 29), (30, 90), (91, 180), (181, 365), (366, 10 ** 6)]",
     "the first published band moves from n=318 at 90.6 to n=295 at 90.5, and "
     "its interval from [28.89, 96.64] to [23.68, 96.61]"),
    ("MB the null drops the indeterminate band",
     'unconditioned = [r for r in frozen_only if r["category"] in PRE_SHIP]',
     'unconditioned = [r for r in frozen_only'
     ' if r["category"] == "pre_ship_stable"]',
     "10 findings / 7 servers / 0.22% -> 6 / 5 / 0.13%"),
    ("MC the null's percentage over the wrong denominator",
     '"pct": round(100.0 * len(unconditioned) / len(rows), 2) if rows else None,',
     '"pct": round(100.0 * len(unconditioned) / len(both), 2) if rows else None,',
     "0.22% -> 5.10% under an unchanged field name"),
    ("MD the confound's server count becomes a pair count",
     'still_roots = {r["root"] for r in still}',
     'still_roots = {(r["root"], r["package"]) for r in still}',
     "13 servers -> 24, and the percentage with it"),
    ("ME trees whose arms agree are skipped",
     "        for k, fver in fz.items():",
     "        if set(fz) == set(lv) and fz:\n            continue\n"
     "        for k, fver in fz.items():",
     "4,638 -> 4,629 and the confound cell 58 -> 55, while the frozen-only "
     "cell, the trees and the pairs all stay put and the gate passes"),
    ("MF the band interval stops being package-clustered",
     '            boot = bootstrap_ci(rs, lambda r: r["package"])',
     '            boot = bootstrap_ci(rs, lambda r: r["root"])',
     "the field still named package_cluster_ci95 reports [83.59, 97.07] for the "
     "youngest band, inverting the one hedge drawn from it"),
]

HARNESS = [
    ("H1 gate disabled",
     "    for name, (want, got) in checks.items():",
     "    for name, (want, got) in []:",
     "M11 pair unit keyed on the advisory"),
    ("H2 category invariant disabled",
     "    require(pre_exact == pre,",
     "    require(True,",
     "M5 swapped classify arguments"),
    ("H3 prerelease probe disabled",
     "        require(len(live) > len(plain),",
     "        require(True,",
     "N7 prerelease dropped from the advisory join"),
]


def run_suite(m):
    global FAILS
    FAILS = []
    for t in (test_parse, test_classify, test_share, test_cluster_and_pctile,
              test_in_cohort, test_bootstrap_percentiles, test_gate,
              test_collect_rows, test_analyse):
        try:
            t(m)
        except Exception as e:
            FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}")
    return list(FAILS)


def mutate(src, old, new):
    assert src.count(old) == 1, f"mutation target not unique ({src.count(old)}): {old!r}"
    return src.replace(old, new)


def main():
    src = open(MODULE).read()

    print("== baseline ==")
    base = run_suite(load(src))
    for f in base:
        print("  FAIL", f)
    print(f"  {sum(RAN.values())} checks, {len(base)} failures")
    if base:
        print("\nBASELINE RED. Fix the code or the golden values before reading "
              "the mutation table.")
        return 1

    print("\n== mutations (each must turn the suite red) ==")
    survived = []
    for name, old, new, measured in MUTATIONS:
        try:
            got = run_suite(load(mutate(src, old, new)))
        except AssertionError as e:
            print(f"  SKIP {name}: {e}")
            survived.append(name + " (target missing)")
            continue
        status = "caught" if got else "SURVIVED"
        print(f"  {status:9s} {name}")
        if got:
            print(f"            first: {got[0][:88]}")
        else:
            survived.append(name)
        print(f"            reviewer measured: {measured}")

    print("\n== harness mutations, each paired with a defect it would hide ==")
    for name, old, new, partner in HARNESS:
        psrc = mutate(src, old, new)
        alone = run_suite(load(psrc))
        print(f"  {name}: alone -> {'red' if alone else 'green (expected)'}")
        po, pn = next((o, n) for nm, o, n, _ in MUTATIONS if nm == partner)
        both = run_suite(load(mutate(psrc, po, pn)))
        print(f"            composite with {partner}: "
              f"{'caught' if both else 'SURVIVED'}")
        if not both:
            survived.append(f"{name} + {partner}")

    print("\n== meta-test: a planted defect must be seen ==")
    planted = mutate(src, '"n": len(rs),', '"n": len(rs) + 1,')
    seen = run_suite(load(planted))
    print(f"  planted off-by-one in the headline n: "
          f"{'caught' if seen else 'SURVIVED'}")
    if not seen:
        survived.append("meta-test")

    print("\n" + "=" * 68)
    if survived:
        print(f"{len(survived)} SURVIVED, so nothing in the suite depends on "
              "them:")
        for s in survived:
            print("  -", s)
        return 1
    print(f"all {len(MUTATIONS)} mutations caught, {len(HARNESS)} composites "
          f"caught, meta-test caught, {sum(RAN.values())} checks ran")
    print("Self-verification bottoms out here: each guard added above can "
          "itself be mutated, and this suite does not mutate its own "
          "golden values.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
