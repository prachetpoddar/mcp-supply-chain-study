#!/usr/bin/env python3
"""Tests for code/verdict_recompute.py, with mutations designed by two reviews.

WHY THE MUTATIONS ARE NOT MINE
    A self-authored mutation set measures the author's imagination. The first
    review of this analysis found two gate checks that could not fail, a
    secondary arm that was not identified, a leave-one-out drawing from
    truncated data and a parse counter that instrumented nothing. The second
    review, which had not seen the first, attacked the repairs and demonstrated
    by execution that two one-line changes inverted or inflated the headline
    with every gate green. The mutations below are theirs.

WHY A FIXTURE AND NOT THE CORPUS
    The corpus sits far from every boundary. No version in it is unparseable, so
    the parse counter reads zero whatever the code does. No advisory of a
    package carries two distinct ranges containing a version that is not a bare
    lower bound, so the double-count probe mined a degenerate case twice before
    it was fixed. The comparable set happens to agree on every root version, so
    a rule that ran on zero servers reported clean. And the forward floor sits
    at 100 against 2,040 observed, so no corpus run can tell the floor from its
    absence. The fixture makes all four live.

ONE SOURCE OF TRUTH
    `EXPECT` is the hand-derived finding table: one row per (server, package,
    advisory) the analysis should produce, with the side it falls on. Every
    scalar golden below is derived from it rather than copied from a run, so a
    wrong row cannot agree with a wrong total.

Run: python3 code/test_verdict_recompute.py
"""
import collections
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "verdict_recompute.py")

# ---------------------------------------------------------------- the fixture
#
# alpha  A1 covers <2.0.0, A2 covers <3.0.0. Two DISTINCT ranges under one id
#        (A3) both contain 1.5.0, which is what the double-count probe needs
#        and what the corpus does not have away from a bare lower bound.
# delta  one advisory, matched by a PRERELEASE only, so the prerelease probe
#        has something to find.
# gamma  no advisory at all, so a node can exist without contributing.

ADVISORIES = {
    # Two rows, one id, the SAME range string twice. The probe must skip this
    # and find alpha's A3 instead; a premise that counts raw rows rather than
    # distinct ranges selects it and passes vacuously, which is what the corpus
    # case (ghost at 0.0.0) did twice before it was fixed.
    "aardvark": [
        {"id": "AA1", "severity": "low", "vulnerable_versions": ">=1.0.0 <4.0.0"},
        {"id": "AA1", "severity": "low", "vulnerable_versions": ">=1.0.0 <4.0.0"},
    ],
    "alpha": [
        {"id": "A1", "severity": "high", "vulnerable_versions": ">=0.0.0 <2.0.0"},
        {"id": "A2", "severity": "low", "vulnerable_versions": ">=0.0.0 <3.0.0"},
        {"id": "A3", "severity": "moderate", "vulnerable_versions": ">=1.0.0 <2.0.0"},
        {"id": "A3", "severity": "moderate", "vulnerable_versions": ">=1.4.0 <1.9.0"},
    ],
    "beta": [
        {"id": "B1", "severity": "critical", "vulnerable_versions": ">=0.0.0 <5.0.0"},
    ],
    "delta": [
        {"id": "D1", "severity": "high", "vulnerable_versions": ">=0.0.0 <1.0.0"},
    ],
}
ADV_META = {"built_utc": "2026-10-13T00:00:00Z", "source": "fixture",
            "advisory_rows": 8}

# Servers. The count is EIGHT, an even number, so a median convention that
# takes the upper middle is distinguishable from one that averages the two.
#
# S1  deps.dev and the resolution agree exactly. No finding either side.
# S2  resolution carries alpha@1.5.0 (A1, A2, A3), deps.dev carries alpha@9.0.0
#     (clean). Three MISSED findings, the scanner's wrong answer.
# S3  deps.dev carries beta@1.0.0 (B1), the resolution does not carry beta at
#     all. One PHANTOM finding.
# S4  both carry beta@1.0.0, so B1 appears on both sides and CANCELS. This is
#     the two-sided cause the symmetry probe needs: suppressing beta changes
#     nothing two-sided and changes the answer one-sided.
# S5  resolution carries delta@0.5.0-rc.1, inside D1 only when prereleases are
#     included. One MISSED finding, and the probe's reason to exist.
# S6  resolution carries alpha at TWO versions, 1.5.0 and 2.5.0. Pair-keyed
#     both contribute; flattened one is discarded, and which one depends on the
#     tie-break, which is the point of the four flattened arms.
# S7  resolution carries an UNPARSEABLE version, so the parse counter has
#     something to count and zero stops being the only possible answer.
# S8  gamma only, no advisories anywhere. A server that is identical and
#     contributes nothing, so `servers_with_a_finding` cannot be a server count.

def srv(pairs_dd, installed, published=None, root="1.0.0", trunc=False):
    return {"dd": {"ok": True, "pairs": [list(p) for p in pairs_dd]},
            "state": {"installed": ["%s@@%s" % (n, v) for n, v in installed],
                      "published": ["%s@@%s" % (n, v)
                                    for n, v in (published or installed)],
                      "root_version": root,
                      "root_published": "2026-01-01T00:00:00Z",
                      "truncated": trunc},
            "root": root}


FIX = {
    # delta on the resolution side only. Without it the two sides have the same
    # NUMBER of servers carrying a finding, and a counter that reads the wrong
    # side still prints the right answer.
    "S1": srv([("gamma", "1.0.0")],
              [("gamma", "1.0.0"), ("delta", "0.5.0-rc.1")]),
    # delta@0.5.0-rc.1 on the DEPS.DEV side: without it, turning
    # include_prerelease off for one side alone changes no left-side total and
    # the side-binding check cannot see it.
    "S2": srv([("alpha", "9.0.0"), ("delta", "0.5.0-rc.1")],
              [("alpha", "1.5.0")]),
    "S3": srv([("beta", "1.0.0"), ("gamma", "1.0.0")], [("gamma", "1.0.0")]),
    # beta on both sides cancels, which is what the symmetry probe needs; alpha
    # on the resolution side only breaks the missed/phantom symmetry, without
    # which an arm swap is invisible in every reported field.
    "S4": srv([("beta", "1.0.0")], [("beta", "1.0.0"), ("alpha", "1.5.0")]),
    "S5": srv([("delta", "9.0.0")], [("delta", "0.5.0-rc.1")]),
    "S6": srv([("alpha", "1.5.0")], [("alpha", "1.5.0"), ("alpha", "2.5.0")]),
    "S7": srv([("alpha", "1.5.0")], [("alpha", "not-a-version")]),
    # S8 keeps gamma, for the October forward move, and adds a missed-only
    # finding so missed findings do not equal phantom findings. With the two
    # equal, binding the arms to compare in the wrong order is invisible.
    "S8": srv([("gamma", "2.0.0")], [("gamma", "2.0.0"), ("beta", "1.0.0")]),
}

# The October arm: every server's version moved FORWARD, which is what the
# cutoff probe requires, plus one backward move so the reported backward count
# is non-zero and its listing is exercised.
OCTOBER = {}
for _s, _r in FIX.items():
    _inst = []
    for _x in _r["state"]["installed"]:
        _n, _, _v = _x.rpartition("@@")
        if _n == "gamma":
            _inst.append("gamma@@9.9.9")              # forward on every server
        elif _s == "S2" and _n == "alpha":
            # forward, and out of every advisory: the published arm then has
            # three findings the installed arm does not, so the harness gate
            # reproduces real numbers rather than a table of zeros
            _inst.append("alpha@@9.0.0")
        elif _s == "S4":
            _inst.append("beta@@0.0.1")               # the one backward move
        else:
            _inst.append(_x)
    OCTOBER[_s] = dict(_r["state"], installed=_inst)

# ------------------------------------------------- the hand-derived golden table
# (server, package, advisory id, side) where side is "missed" or "phantom".
EXPECT = [
    ("S2", "alpha", "A1", "missed"),
    ("S2", "alpha", "A2", "missed"),
    ("S2", "alpha", "A3", "missed"),
    ("S3", "beta", "B1", "phantom"),
    ("S5", "delta", "D1", "missed"),
    ("S2", "delta", "D1", "phantom"),
    ("S8", "beta", "B1", "missed"),
    ("S1", "delta", "D1", "missed"),
    ("S4", "alpha", "A1", "missed"),
    ("S4", "alpha", "A2", "missed"),
    ("S4", "alpha", "A3", "missed"),
    # S7's resolution version does not parse, so its side yields nothing and
    # deps.dev's three alpha findings have nothing to cancel against. This is
    # the parse-failure signature a review identified as the one mechanism that
    # would produce "zero phantom with a subset left side", here inverted: the
    # unparseable side is the right one, so the findings land as phantoms. The
    # fixture exists to make it visible, and the table has to carry it.
    ("S7", "alpha", "A1", "phantom"),
    ("S7", "alpha", "A2", "phantom"),
    ("S7", "alpha", "A3", "phantom"),
    ("S6", "alpha", "A1", "missed"),
    ("S6", "alpha", "A2", "missed"),
    ("S6", "alpha", "A3", "missed"),
]
# S6: the resolution has alpha at 1.5.0 and 2.5.0. 1.5.0 is inside A1, A2, A3;
# 2.5.0 is inside A2 only. Findings are keyed on (package, advisory id), so the
# set is {A1, A2, A3}. deps.dev carries alpha@1.5.0, the same three. They
# CANCEL, so S6 contributes nothing. Corrected below.
EXPECT = [r for r in EXPECT if r[0] != "S6"]

SEV = {"A1": "high", "A2": "low", "A3": "moderate", "B1": "critical",
       "D1": "high"}


def _derived():
    missed = [r for r in EXPECT if r[3] == "missed"]
    phantom = [r for r in EXPECT if r[3] == "phantom"]
    msev, psev = collections.Counter(), collections.Counter()
    for r in missed:
        msev[SEV[r[2]]] += 1
    for r in phantom:
        psev[SEV[r[2]]] += 1
    differ = {r[0] for r in EXPECT}
    # Servers whose RESOLUTION side carries at least one finding. Derived from
    # the fixture, not listed, so the field a swapped diagnostic would corrupt
    # has a golden that moves with the table.
    right_any = set()
    for sv, rec in FIX.items():
        for x in rec["state"]["installed"]:
            n, _, v = x.rpartition("@@")
            if any(r[1] == n for r in EXPECT) or n in ("alpha", "beta", "delta"):
                try:
                    import nodesemver as _sv
                    for a in ADVISORIES.get(n) or []:
                        if _sv.satisfies(v, a["vulnerable_versions"],
                                         loose=True, include_prerelease=True):
                            right_any.add(sv)
                            break
                except Exception:
                    pass
    # Leave-one-out, derived: the findings that survive removing one package.
    loo = {}
    for pkg in sorted({r[1] for r in EXPECT}):
        kept = [r for r in EXPECT if r[1] != pkg]
        loo[pkg] = {
            "verdict_differs": len({r[0] for r in kept}),
            "missed_findings": sum(1 for r in kept if r[3] == "missed"),
            "phantom_findings": sum(1 for r in kept if r[3] == "phantom")}
    return {
        "servers": len(FIX),
        "leave_one_out": loo,
        "servers_with_a_finding_on_the_resolution_side": len(right_any),
        "verdict_differs": len(differ),
        "missed_findings": len(missed),
        "phantom_findings": len(phantom),
        "missed_servers": len({r[0] for r in missed}),
        "phantom_servers": len({r[0] for r in phantom}),
        "missed_by_severity": {k: v for k, v in sorted(msev.items())},
        "phantom_by_severity": {k: v for k, v in sorted(psev.items())},
    }


GOLD = _derived()

# ------------------------------------------------------------------ harness

RAN = collections.Counter()
FAILS = []


def check(name, got, want):
    RAN[name] += 1
    if got != want:
        FAILS.append("%s: got %r, want %r" % (name, got, want))
    return got == want


def load(src=None):
    """Import the module (optionally mutated) against the fixture."""
    d = tempfile.mkdtemp()
    data = os.path.join(d, "data")
    os.makedirs(data, exist_ok=True)
    json.dump({k: v["dd"] for k, v in FIX.items()},
              open(os.path.join(data, "depsdev_pairs.json"), "w"))
    json.dump({k: v["state"] for k, v in FIX.items()},
              open(os.path.join(data, "nested_gap_state_depsdev_matched.json"), "w"))
    json.dump(OCTOBER, open(os.path.join(data, "nested_gap_state.json"), "w"))
    json.dump(ADVISORIES, open(os.path.join(data, "advisories_npm.json"), "w"))
    json.dump(ADV_META, open(os.path.join(data, "advisories_npm_meta.json"), "w"))
    json.dump({"trees": 0}, open(os.path.join(data, "nested_gap.json"), "w"))
    json.dump([{"server": k, "root_version": v["root"]} for k, v in FIX.items()],
              open(os.path.join(data, "resolved_trees_for_depsdev.json"), "w"))
    os.environ["VERDICT_DATA"] = data
    path = os.path.join(d, "mod_under_test.py")
    open(path, "w").write(src if src is not None else open(MODULE).read())
    spec = importlib.util.spec_from_file_location("mod_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # The harness gate's golden is the real corpus figure; against the fixture
    # it must be the fixture's own frozen-vs-live answer, derived below.
    m.PUBLISHED_NESTED = _harness_golden(m)
    # Eight servers cannot produce 100 forward moves. The shipped value is
    # asserted separately, in test_shipped_defaults.
    m.FORWARD_FLOOR = 1
    # delta@0.5.0-rc.1 is inside D1 only when prereleases are included, which
    # is what multer@1.4.5-lts.2 is in the corpus.
    m.PRERELEASE_PROBE = ("delta", "0.5.0-rc.1")
    return m


def _harness_golden(m):
    """The fixture's own frozen-vs-live answer, computed with the module's join.

    Derived rather than transcribed so the gate still gates: if the join
    changes, this moves with it and the mutation shows up in the unit tests
    instead of being absorbed here.
    """
    s = {k: v for k, v in OCTOBER.items()
         if "skip" not in v and not v.get("truncated")}
    differ = ph = m_tr = live = 0
    msev, psev = collections.Counter(), collections.Counter()
    for v in s.values():
        p = m.findings(m.split(x) for x in v["published"])
        q = m.findings(m.split(x) for x in v["installed"])
        mi, pa = q - p, p - q
        if q:
            live += 1
        if mi or pa:
            differ += 1
        if pa:
            ph += 1
        if mi:
            m_tr += 1
        msev += m.sev_counts(mi)
        psev += m.sev_counts(pa)
    return {"trees": len(s), "phantom_trees": ph,
            "phantom_findings": sum(psev.values()),
            "missed_findings": sum(msev.values()),
            "missed_trees": m_tr, "verdict_differs": differ,
            "trees_with_live_findings": live,
            "missed_by_severity": dict(sorted(m.by_sev(msev).items())),
            "phantom_by_severity": dict(sorted(m.by_sev(psev).items()))}


# ------------------------------------------------------------- unit level

def test_vids(m):
    check("vids alpha 1.5.0", sorted(m.vids("alpha", "1.5.0")),
          ["A1", "A2", "A3"])
    check("vids alpha 2.5.0", sorted(m.vids("alpha", "2.5.0")), ["A2"])
    check("vids alpha 9.0.0", sorted(m.vids("alpha", "9.0.0")), [])
    check("vids gamma", sorted(m.vids("gamma", "1.0.0")), [])
    # A3 spans two distinct ranges that BOTH contain 1.5.0 and the finding is
    # one, not two. This is the counting unit the protocol fixes.
    check("A3 counted once", sum(1 for a in m.vids("alpha", "1.5.0") if a == "A3"), 1)
    # the prerelease, which a default-configured satisfies() misses
    check("prerelease matched", sorted(m.vids("delta", "0.5.0-rc.1")), ["D1"])
    check("prerelease off", sorted(m.vids("delta", "0.5.0-rc.1", pre=False)), [])


def test_unparseable(m):
    m.vids("alpha", "not-a-version")
    check("unparseable recorded", ("alpha", "not-a-version") in m.BAD_VERSIONS, True)
    check("parseable not recorded", ("alpha", "1.5.0") in m.BAD_VERSIONS, False)
    check("unparseable counted", m.unparseable([("alpha", "not-a-version"),
                                                ("alpha", "1.5.0")]), 1)


def test_by_sev_sums(m):
    c = collections.Counter({"high": 2, "weird": 1, None: 3})
    out = m.by_sev(c)
    check("by_sev keeps unknown", sum(out.values()), 6)
    check("by_sev names unknown", any(k.startswith("unknown:") for k in out), True)


def test_flatten(m):
    ps = [("a", "1"), ("a", "2"), ("b", "9")]
    check("keep_last", dict(m.keep_last(ps))["a"], "2")
    check("keep_first", dict(m.keep_first(ps))["a"], "1")
    check("four tie-breaks", sorted(m.TIE_BREAKS), sorted([
        "depsdev_first/resolution_first", "depsdev_first/resolution_last",
        "depsdev_last/resolution_first", "depsdev_last/resolution_last"]))


def test_compare_against_the_table(m):
    dd = {k: [tuple(p) for p in v["dd"]["pairs"]] for k, v in FIX.items()}
    right = {k: [m.split(x) for x in v["state"]["installed"]]
             for k, v in FIX.items()}
    servers = sorted(FIX)
    r = m.compare(dd, right, servers)
    for key in ("servers", "verdict_differs", "missed_findings",
                "phantom_findings", "missed_servers", "phantom_servers",
                "missed_by_severity", "phantom_by_severity"):
        check("compare %s" % key, r[key], GOLD[key])
    check("compare parse counter", r["unparseable_versions_resolution_side"], 1)
    check("compare parse counter left", r["unparseable_versions_depsdev_side"], 0)
    # beta is on both sides of S4, where it cancels, and on the deps.dev side
    # only of S3, where it does not. So it carries exactly one phantom and no
    # missed: a package can be two-sided and still appear in one breakdown.
    check("beta phantom count", r["phantom_by_package"].get("beta"), 1)
    # beta is also missed once, on S8, where the resolution carries it and
    # deps.dev does not. One name, one finding each way, on different servers.
    check("beta missed count", r["missed_by_package"].get("beta"), 1)
    # percent, derived from the table rather than written down: 5 of 8
    check("verdict pct", r["verdict_differs_pct"],
          round(100 * GOLD["verdict_differs"] / GOLD["servers"], 1))
    # the field a swapped counter would corrupt while both totals stayed right
    check("resolution-side finders",
          r["servers_with_a_finding_on_the_resolution_side"],
          GOLD["servers_with_a_finding_on_the_resolution_side"])


def test_orientation_is_directional(m):
    """A finding on one side only must land on that side and nowhere else."""
    one = m.compare({"p": [("alpha", "1.5.0")]}, {"p": []}, ["p"])
    check("left only -> phantom", one["phantom_findings"], 3)
    check("left only -> no missed", one["missed_findings"], 0)
    check("left only -> phantom server", one["phantom_servers"], 1)
    check("left only -> no missed server", one["missed_servers"], 0)
    other = m.compare({"p": []}, {"p": [("alpha", "1.5.0")]}, ["p"])
    check("right only -> missed", other["missed_findings"], 3)
    check("right only -> no phantom", other["phantom_findings"], 0)


def test_suppression_is_two_sided(m):
    dd = {k: [tuple(p) for p in v["dd"]["pairs"]] for k, v in FIX.items()}
    right = {k: [m.split(x) for x in v["state"]["installed"]]
             for k, v in FIX.items()}
    servers = sorted(FIX)
    two = m.compare(dd, right, servers, suppress=frozenset(["beta"]))
    one = m.compare(dd, right, servers, suppress=frozenset(["beta"]),
                    suppress_left_only=True)
    # beta is on both sides of S4 and on the deps.dev side of S3. Two-sided
    # suppression removes S3's phantom; one-sided leaves S4's beta on the
    # resolution side, turning it into a missed finding.
    # beta's own phantom goes; S7's three alpha phantoms are untouched
    check("two-sided drops beta's phantom", two["phantom_findings"],
          GOLD["phantom_findings"] - 1)
    check("one-sided manufactures a missed", one["missed_findings"] >
          two["missed_findings"], True)
    cause = m.pick_two_sided_cause(dd, right, servers, {"beta": 1, "delta": 1})
    check("two-sided cause chosen", cause, "beta")
    # gamma carries no advisory on either side, so it is not two-sided and must
    # not be chosen: choosing a name that is absent from one side makes the
    # one-sided and two-sided runs coincide and the gate fail on correct code.
    check("cause absent from both sides rejected",
          m.pick_two_sided_cause(dd, right, servers, {"gamma": 1}), None)


def test_gates_fire_and_pass(m):
    check("orientation gate", bool(m.gate_orientation()), True)
    check("double-count probe", m.gate_double_count_probe()["deduplicated_join"], 1)
    check("double-count probe rows", m.gate_double_count_probe()["row_counting_join"], 2)
    check("prerelease probe", m.gate_prerelease_probe(), 1)
    dd_m = {k: [m.split(x) for x in v["state"]["installed"]] for k, v in FIX.items()}
    dd_o = {k: [m.split(x) for x in v["installed"]] for k, v in OCTOBER.items()}
    cov = m.gate_cutoff_had_an_effect(dd_m, dd_o)
    # gamma is the only name the October fixture moves forward and it appears
    # on three servers (S1, S3, S8), so three (server, name) occurrences move.
    # The gate counts occurrences, not distinct names, which is why the shipped
    # floor of 100 is a loose bound rather than a statement about names.
    # gamma on S1, S3, S8 plus alpha on S2: four (server, name) occurrences
    # move forward. The gate counts occurrences, not distinct names, which is
    # why the shipped floor of 100 is a loose bound and not a claim about names.
    check("cutoff forward moves", cov["names_october_newer"], 4)
    check("cutoff backward moves", cov["names_october_older"], 1)
    check("cutoff lists the backward case", len(cov["backward_cases"]), 1)


def test_shipped_defaults(m):
    """The values that ship, not the values the harness overrides."""
    fresh = open(MODULE).read()
    check("FORWARD_FLOOR ships as 100", "\nFORWARD_FLOOR = 100\n" in fresh, True)
    check("prerelease probe ships as multer@1.4.5-lts.2",
          'PRERELEASE_PROBE = ("multer", "1.4.5-lts.2")' in fresh, True)
    check("cutoff ships as 2026-09-08T01:00:00Z",
          'MATCHED_CUTOFF = "2026-09-08T01:00:00Z"' in fresh, True)
    check("no bare assert in the module", "\n    assert " not in fresh, True)
    check("require raises", "raise GateFailed" in fresh, True)


def test_range_sanity_counts(m):
    r = m.range_sanity()
    check("range sanity reads every range", r["ranges_read"], 8)
    check("range sanity finds none odd", r["structurally_odd"], 0)


def test_root_rule_is_enforced(m):
    """A root-version disagreement must stop the run, not be recorded."""
    data = os.environ["VERDICT_DATA"]
    p = os.path.join(data, "resolved_trees_for_depsdev.json")
    good = json.load(open(p))
    bad = [dict(r, root_version="9.9.9") if r["server"] == "S2" else r
           for r in good]
    json.dump(bad, open(p, "w"))
    try:
        try:
            m.main()
            check("root mismatch raises", False, True)
        except m.GateFailed as e:
            check("root mismatch raises", "root-version mismatch" in str(e), True)
    finally:
        json.dump(good, open(p, "w"))


def test_main_end_to_end(m):
    m.main()
    out = json.load(open(m.OUT))
    pr = out["primary_pair_keyed"]
    for key in ("verdict_differs", "missed_findings", "phantom_findings"):
        check("main %s" % key, pr[key], GOLD[key])
    check("main records distinct checks",
          out["provenance"]["distinct_checks"] > 0, True)
    check("main records require calls",
          out["provenance"]["require_calls_made"] >= out["provenance"]["distinct_checks"],
          True)
    flat = out["secondary_flattened_not_identified"]
    check("four flattened arms", len(flat["arms"]), 4)
    check("span is labelled a span",
          "verdict_differs_pct_span_over_these_four" in flat, True)
    # S6 carries alpha twice, so at least one tie-break must differ from
    # another: a span of zero would mean the flattening does nothing
    rates = sorted(a["verdict_differs_pct"] for a in flat["arms"].values())
    check("flattening actually moves the answer", rates[0] != rates[-1], True)
    # The leave-one-out, pinned against the table. Without this, an off-by-one
    # planted inside the suppressed path alone passes the whole suite.
    loo = out["leave_one_out_single_name_only"]
    for pkg, want in GOLD["leave_one_out"].items():
        for key, v in want.items():
            check("loo %s %s" % (pkg, key), loo[pkg][key], v)
    check("exclusions block present", "exclusions" in out, True)
    check("input accounting present", "input_accounting" in out, True)


TESTS = (test_vids, test_unparseable, test_by_sev_sums, test_flatten,
         test_compare_against_the_table, test_orientation_is_directional,
         test_suppression_is_two_sided, test_gates_fire_and_pass,
         test_shipped_defaults, test_range_sanity_counts,
         test_root_rule_is_enforced, test_main_end_to_end)


def run_suite(m):
    global FAILS
    FAILS = []
    for t in TESTS:
        try:
            t(m)
        except Exception as e:
            FAILS.append("%s raised %s: %s" % (t.__name__, type(e).__name__, e))
    return list(FAILS)


def mutate(src, old, new):
    assert src.count(old) == 1, \
        "mutation target not unique (%d): %r" % (src.count(old), old)
    return src.replace(old, new)


# ------------------------------------------------- mutations, designed by review
# (name, old, new, what the reviewer said it would do)
MUTATIONS = [
    ("R1 argument order inverted at the primary call site",
     "    primary = compare(dd, matched, servers)\n",
     "    primary = compare(matched, dd, servers)\n",
     "second review, executed: inverts missed and phantom; the orientation "
     "probe builds its own dicts so it stayed green"),
    ("R2 one-sided semver flag inside compare",
     "        L, R = findings(lp), findings(rp)\n",
     "        L = {(n, a) for n, v in lp for a in vids(n, v, pre=False)}\n"
     "        R = findings(rp)\n",
     "second review, executed: missed findings 15 -> 37 on real data, all "
     "five gates green"),
    ("R3 per-server counters swapped",
     "        if missed:\n            miss_srv += 1\n"
     "        if phantom:\n            ph_srv += 1\n",
     "        if missed:\n            ph_srv += 1\n"
     "        if phantom:\n            miss_srv += 1\n",
     "second review, executed: eight missed findings over zero missed "
     "servers, internally contradictory and green"),
    ("R4 by-package accumulators swapped",
     "        for n, _ in missed:\n            mby[n] += 1\n"
     "        for n, _ in phantom:\n            pby[n] += 1\n",
     "        for n, _ in missed:\n            pby[n] += 1\n"
     "        for n, _ in phantom:\n            mby[n] += 1\n",
     "second review, executed: the named packages carrying the result land "
     "under the wrong heading"),
    ("R5 severity mis-keyed on package alone",
     "        c[SEV_OF.get((nm, a))] += 1\n",
     "        c[SEV_OF.get(nm)] += 1\n",
     "second review, executed: every severity becomes unknown while the "
     "harness gate discarded the breakdowns that would catch it"),
    ("R6 missed/phantom assignments swapped",
     "        missed, phantom = R - L, L - R\n",
     "        missed, phantom = L - R, R - L\n",
     "first review, mutation 1: no gate read orientation"),
    ("R7 verdict percent over the wrong denominator",
     '        "verdict_differs_pct": round(100 * differ / n, 1) if n else None,',
     '        "verdict_differs_pct": round(100 * differ / right_any, 1) if right_any else None,',
     "first review, mutation 3: plausible-but-wrong denominator under the "
     "same field name"),
    ("R8 verdict guard weakened to left-side-nonempty",
     "        if L != R:\n",
     "        if L and L != R:\n",
     "first review, mutation 2: a server where deps.dev reports nothing and "
     "the resolution reports findings stops counting as differing"),
    ("R9 resolution-side finder counted off the left",
     "        if R:\n            right_any += 1\n",
     "        if L:\n            right_any += 1\n",
     "first review, mutation 4: corrupted diagnostic behind a correct "
     "boolean verdict"),
    ("R10 severity breakdown drops a class",
     '    out = {k: c.get(k, 0) for k in SEV if c.get(k, 0)}\n',
     '    out = {k: c.get(k, 0) for k in SEV[:3] if c.get(k, 0)}\n',
     "first review, mutation 7: low findings vanish while the totals keep "
     "them, and nothing checked the decomposition sums"),
    ("R11 flatten first-wins instead of last-wins",
     "def keep_last(pairs):\n    \"\"\"One version per name, last occurrence wins.\"\"\"\n"
     "    m = {}\n    for n, v in pairs:\n        m[n] = v\n    return list(m.items())\n",
     "def keep_last(pairs):\n    \"\"\"One version per name, last occurrence wins.\"\"\"\n"
     "    m = {}\n    for n, v in pairs:\n        m.setdefault(n, v)\n    return list(m.items())\n",
     "first review, mutation 5: measured 185 -> 197 findings on the October "
     "arm; the two keep_* rules become the same rule"),
    ("R12 suppression leaks to the deps.dev side only",
     "            if not suppress_left_only:\n",
     "            if False:\n",
     "first review, protocol gate 4's class: every leave-one-out row shifts "
     "with nothing raising"),
    ("R13 root-version rule back to a no-op",
     "        rv = fetch_roots.get(srv)\n",
     "        rv = None\n",
     "second review, defect 1: the rule ran on zero of 248 servers and the "
     "output reported an empty mismatch list"),
    ("R14 unparseable counted before findings fills the set",
     "        L, R = findings(lp), findings(rp)\n"
     "        # After findings(), not before: BAD_VERSIONS is filled lazily inside\n",
     "        bad_l += unparseable(lp)\n        bad_r += unparseable(rp)\n"
     "        L, R = findings(lp), findings(rp)\n"
     "        # After findings(), not before: BAD_VERSIONS is filled lazily inside\n",
     "second review, defect 8: the first compare over an arm reports zero "
     "and later ones report the truth"),
    ("R15 double-count selection stops de-duplicating ranges",
     "            distinct = sorted(set(ranges))\n",
     "            distinct = sorted(ranges)\n",
     "the degenerate case the corpus had: one advisory carried as two "
     "identical range strings. The premise must reject it, and an earlier "
     "premise could not because it read the same local this mutation "
     "corrupts"),
    ("R16 dedup removed from vids",
     "    o = set()\n    tried = raised = 0\n",
     "    o = []\n    tried = raised = 0\n",
     "the counting unit: row counting inflated a published phantom total "
     "from 4,442 to 6,791"),
]

# Harness mutations, each paired with the data defect only that layer catches.
HARNESS = [
    ("H1 orientation probe's findings check neutered",
     '        require(r[want + "_findings"] > 0 and r[other + "_findings"] == 0,',
     '        require(r[want + "_findings"] >= 0 and r[other + "_findings"] >= 0,',
     "R6 missed/phantom assignments swapped"),
    ("H2 harness golden compared key-set only",
     "        require(got[k] == PUBLISHED_NESTED[k],",
     "        require(got[k] >= 0 and PUBLISHED_NESTED[k] >= 0,",
     "R5 severity mis-keyed on package alone"),
    ("H3 side-binding check loosened to one side",
     '    require(primary["total_findings_resolution_side"] == ind_r,',
     '    require(ind_r >= 0,',
     "R1 argument order inverted at the primary call site"),
]


def main():
    src = open(MODULE).read()

    print("== baseline ==")
    base = run_suite(load(src))
    for f in base:
        print("  FAIL", f)
    print("  %d checks, %d failures" % (sum(RAN.values()), len(base)))
    if base:
        print("\nBASELINE RED. Fix the code or the golden table before reading "
              "the mutation results.")
        return 1

    print("\n== mutations (each must turn the suite red) ==")
    survived = []
    for name, old, new, measured in MUTATIONS:
        try:
            got = run_suite(load(mutate(src, old, new)))
        except AssertionError as e:
            print("  SKIP %s: %s" % (name, e))
            survived.append(name + " (target missing)")
            continue
        print("  %-9s %s" % ("caught" if got else "SURVIVED", name))
        if got:
            print("            first: %s" % got[0][:92])
        else:
            survived.append(name)
        print("            reviewer: %s" % measured)

    print("\n== harness mutations, each paired with a defect it would hide ==")
    for name, old, new, partner in HARNESS:
        try:
            psrc = mutate(src, old, new)
        except AssertionError as e:
            print("  SKIP %s: %s" % (name, e))
            survived.append(name + " (target missing)")
            continue
        alone = run_suite(load(psrc))
        print("  %s: alone -> %s" % (name, "red" if alone else "green (expected)"))
        po, pn = next((o, n) for nm, o, n, _ in MUTATIONS if nm == partner)
        both = run_suite(load(mutate(psrc, po, pn)))
        print("            composite with %s: %s"
              % (partner.split()[0], "caught" if both else "SURVIVED"))
        if not both:
            survived.append("%s + %s" % (name, partner.split()[0]))

    print("\n== meta-test: a planted defect must be seen ==")
    for label, old, new in (
            ("off-by-one in the headline server count",
             '        "servers": n,', '        "servers": n + 1,'),
            ("off-by-one inside the leave-one-out only",
             '                   "missed_findings": r["missed_findings"],\n'
             '                   "phantom_findings": r["phantom_findings"]}\n',
             '                   "missed_findings": r["missed_findings"] + 1,\n'
             '                   "phantom_findings": r["phantom_findings"]}\n')):
        seen = run_suite(load(mutate(src, old, new)))
        print("  %s: %s" % (label, "caught" if seen else "SURVIVED"))
        if not seen:
            survived.append("meta-test: " + label)

    print("\n" + "=" * 70)
    if survived:
        print("%d SURVIVED, so nothing in the suite depends on them:" % len(survived))
        for s in survived:
            print("  -", s)
        return 1
    print("all %d mutations caught, %d composites caught, meta-tests caught, "
          "%d checks ran" % (len(MUTATIONS), len(HARNESS), sum(RAN.values())))
    print("Self-verification bottoms out here: every guard above can itself be "
          "mutated, and this suite does not mutate its own golden table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
