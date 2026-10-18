#!/usr/bin/env python3
"""Tests for code/depsdev_recompute.py, with mutations designed by a review.

WHY THE MUTATIONS ARE NOT MINE
    This script shipped in v3.15 with no suite at all. An independent reviewer
    that did not write it designed the fifteen mutations below and the
    checklist they implement. Its own finding was that the headline pairing,
    79.4% against 62.1%, scored the two arms against different left-hand node
    sets: each arm excluded from the deps.dev side the names its own resolution
    carried at several versions, and the historical input carries none, so it
    excluded nothing while the matched arm removed 763 deps.dev nodes. That is
    fixed and the comparable pair is gated here.

WHY A FIXTURE AND NOT THE CORPUS
    Every boundary in this analysis is unreachable from the corpus. No deps.dev
    node has an empty version string, so the falsy-version guard is untestable.
    The gated set has 249 servers and every reported arm has 248, and index
    124 is the true median of the first and the upper middle of the second, so
    the median convention is invisible. Nothing is published at the cutoff
    instant. No extra class has a tie straddling the top-three slice. The
    fixture makes all of them live.

ONE SOURCE OF TRUTH
    `ROWS` is the hand-derived per-server table: deps.dev nodes, the single
    versions the resolution picks, and the names it carries at several. Every
    golden is derived from it.

Run: python3 code/test_depsdev_recompute.py
"""
import collections
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "depsdev_recompute.py")
CUTOFF = "2026-09-08T01:00:00Z"

# ---------------------------------------------------------------- the fixture
#
# Eight servers, so n is EVEN and the upper-median convention is separable from
# the mean-of-middles one. Node counts are deliberately distinct around the
# middle: sorted they are 1, 2, 2, 3, 4, 4, 5, 6, so the two middles are 3 and
# 4 and the two conventions give 4 and 3.5.
#
# T1  identical on both sides. The only agreeing server before suppression.
# T2  one version disagreement on `edge`, the causing package.
# T3  the same disagreement, plus the three downstream extras deps.dev lists.
# T4  the same again, so `edge` is the top disagreement at three servers and
#     `d1` is the top extra at three, which is the incidence match the derived
#     cause now requires.
# T5  deps.dev reports a node with an EMPTY version string. The falsy guard
#     scores that as agreement; without a fixture case nothing can tell.
# T6  the resolution carries `dup` at TWO versions, so the multi exclusion has
#     something to exclude, and the comparable pair has something to equalise.
# T7  the resolution carries `trip` at THREE versions, which neither a
#     first-wins nor a last-wins flattening can fully represent.
# T8  four extras tied at the third rank, so the top-three slice splits a tie.

ROWS = {
    "T1": {"dd": {"a": "1.0.0"}, "single": {"a": "1.0.0"}, "multi": {}},
    "T2": {"dd": {"a": "1.0.0", "edge": "1.3.1"},
           "single": {"a": "1.0.0", "edge": "1.3.0"}, "multi": {}},
    # d4 is inserted BEFORE d3 so the Counter's insertion order disagrees with
    # the explicit (-count, name) tie-break. All four d-names end on the same
    # count, so the top-three slice straddles a tie and the tie-break is the
    # only thing deciding which three are taken.
    "T3": {"dd": {"edge": "1.3.1", "d1": "1.0.0", "d2": "1.0.0",
                  "d4": "1.0.0", "d3": "1.0.0"},
           "single": {"edge": "1.3.0"}, "multi": {}},
    "T4": {"dd": {"edge": "1.3.1", "d1": "1.0.0", "d2": "1.0.0",
                  "d4": "1.0.0", "d3": "1.0.0"},
           "single": {"edge": "1.3.0", "z": "1.0.0"}, "multi": {}},
    "T5": {"dd": {"a": "1.0.0", "blank": ""},
           "single": {"a": "1.0.0", "blank": "9.9.9"}, "multi": {}},
    # b and c on both sides: T6 still agrees, and its post-exclusion node count
    # moves from 1 to 3, which is what separates the upper median from the
    # lower one at n = 8. Without that separation the convention is untestable.
    "T6": {"dd": {"dup": "1.0.0", "a": "1.0.0", "b": "1.0.0", "c": "1.0.0"},
           "single": {"a": "1.0.0", "b": "1.0.0", "c": "1.0.0"},
           "multi": {"dup": ["1.0.0", "2.0.0"]}},
    "T7": {"dd": {"trip": "1.0.0", "a": "1.0.0", "b": "1.0.0"},
           "single": {"a": "1.0.0", "b": "1.0.0"},
           "multi": {"trip": ["1.0.0", "2.0.0", "3.0.0"]}},
    "T8": {"dd": dict({"e%d" % i: "1.0.0" for i in range(1, 13)},
                      d1="1.0.0", d2="1.0.0", d4="1.0.0", d3="1.0.0", a="1.0.0"),
           "single": {"a": "1.0.0"}, "multi": {}},
}

# Publish times. T2/T3/T4 select edge@1.3.0, published before the cutoff.
# `late` is published AFTER it and is used only by the cutoff tests.
TIMES = {
    "a": {"1.0.0": "2026-01-01T00:00:00Z"},
    "b": {"1.0.0": "2026-01-01T00:00:00Z"},
    "z": {"1.0.0": "2026-01-01T00:00:00Z"},
    "edge": {"1.3.0": "2026-01-01T00:00:00Z", "1.3.1": "2026-09-20T00:00:00Z"},
    "dup": {"1.0.0": "2026-01-01T00:00:00Z", "2.0.0": "2026-01-02T00:00:00Z"},
    "trip": {"1.0.0": "2026-01-01T00:00:00Z", "2.0.0": "2026-01-02T00:00:00Z",
             "3.0.0": "2026-01-03T00:00:00Z"},
    # exactly AT the instant: the boundary the corpus never reaches
    "atinstant": {"1.0.0": CUTOFF},
    # a naive timestamp, which made the comparison raise TypeError outside the
    # try that caught ValueError around the parse
    "naive": {"1.0.0": "2026-01-01T00:00:00"},
    "blank": {"9.9.9": "2026-01-01T00:00:00Z"},
}
for _n in ["d1", "d2", "d3", "d4", "c"] + ["e%d" % i for i in range(1, 13)]:
    TIMES[_n] = {"1.0.0": "2026-01-01T00:00:00Z"}

MCPLIB_SHIM = '''"""Fixture shim. Mode comes from MCPLIB_MODE."""
import json, os
TIMES = json.loads(os.environ["MCPLIB_TIMES"])
def npm_packument(name):
    mode = os.environ.get("MCPLIB_MODE", "warm")
    if mode == "raise":
        raise RuntimeError("fixture: lookup failed")
    if mode == "none":
        return None
    if mode == "late":
        return {"time": {v: "2026-12-31T00:00:00Z"
                         for v in (TIMES.get(name) or {})}}
    return {"time": TIMES.get(name) or {}}
'''


def _hist_single(r):
    """The pre-correction resolution: edge at 1.3.1 where the corrected arm
    takes 1.3.0. Without this the two arms are identical, the derived cause
    has no disagreement to rank, and the comparable pair compares a thing to
    itself."""
    out = dict(r["single"])
    if out.get("edge") == "1.3.0":
        out["edge"] = "1.3.1"
    # the historical input is already one version per name, so a name the
    # corrected arm carries several times appears once here
    for n, vs in r["multi"].items():
        out[n] = vs[0]
    return out


def _state(rows):
    """A nested_gap-shaped state file from the row table."""
    out = {}
    for s, r in rows.items():
        inst = ["%s@@%s" % (n, v) for n, v in r["single"].items()]
        for n, vs in r["multi"].items():
            inst += ["%s@@%s" % (n, v) for v in vs]
        out[s] = {"installed": sorted(inst), "published": sorted(inst),
                  "root_version": "1.0.0",
                  "root_published": "2026-01-01T00:00:00Z", "truncated": False}
    return out


# ------------------------------------------------- hand-derived goldens

def _compare_by_hand(rows, servers, suppress=(), exclude=None):
    """The comparison, worked by hand from the table, for the golden."""
    agree = 0
    classes = collections.Counter()
    tl = td = fewer = 0
    for s in servers:
        r = rows[s]
        drop = set(r["multi"]) if exclude is None else set(exclude.get(s) or ())
        ddn = {k: v for k, v in r["dd"].items()
               if k not in suppress and k not in drop}
        live = {k: v for k, v in r["single"].items()
                if k not in suppress and k not in drop}
        miss = [k for k in live if k not in ddn]
        extra = [k for k in ddn if k not in live]
        # the falsy guard: an empty deps.dev version scores as agreement
        vdiff = [k for k in live if k in ddn and ddn[k] and live[k] != ddn[k]]
        if miss:
            classes["miss"] += 1
        if extra:
            classes["extra"] += 1
        if vdiff:
            classes["vdiff"] += 1
        if not miss and not extra and not vdiff:
            agree += 1
        tl += len(live)
        td += len(ddn)
        if len(ddn) < len(live):
            fewer += 1
    return agree, dict(classes), tl, td, fewer


SERVERS = sorted(ROWS)
# The gated block reproduces the HISTORICAL arm, which is already one version
# per name and therefore excludes nothing from the deps.dev side. The golden
# has to be computed the same way, with an empty exclusion on every server, or
# it is the matched arm's answer wearing the historical arm's label.
HIST_ROWS = {s: dict(r, single=_hist_single(r), multi={})
             for s, r in ROWS.items()}
AGREE, CLASSES, TL, TD, FEWER = _compare_by_hand(
    HIST_ROWS, SERVERS, exclude={s: set() for s in SERVERS})
# and the medians come from the node counts AFTER exclusions, not from the raw
# deps.dev counts
MATCH_AGREE, MATCH_CLASSES, _, _, _ = _compare_by_hand(ROWS, SERVERS)
N = len(SERVERS)
PCT = lambda k: round(100.0 * k / N, 1)
GOLD_PUBLISHED = {
    "comparable": N,
    "identical": AGREE,
    "identical_pct": PCT(AGREE),
    "version_differs_pct": PCT(CLASSES.get("vdiff", 0)),
    "fewer_pct": PCT(FEWER),
    "instance_delta_pct": round(100.0 * (TL - TD) / max(TD, 1), 1),
}
# node counts on the deps.dev side, for the median convention
DD_N = sorted(len([k for k in ROWS[s]["dd"] if k not in ROWS[s]["multi"]])
              for s in SERVERS)
UPPER_MEDIAN = DD_N[len(DD_N) // 2]
LOWER_MEDIAN = DD_N[(len(DD_N) - 1) // 2]

RAN = collections.Counter()
FAILS = []


def check(name, got, want):
    RAN[name] += 1
    if got != want:
        FAILS.append("%s: got %r, want %r" % (name, got, want))
    return got == want


def load(src=None, mode="warm"):
    d = tempfile.mkdtemp()
    data = os.path.join(d, "data")
    os.makedirs(data, exist_ok=True)
    json.dump({s: {"ok": True, "nodes": r["dd"]} for s, r in ROWS.items()},
              open(os.path.join(data, "depsdev_state.json"), "w"))
    json.dump([{"server": s, "root_version": "1.0.0",
                "resolved": _hist_single(r)} for s, r in ROWS.items()],
              open(os.path.join(data, "resolved_trees_for_depsdev.json"), "w"))
    st = _state(ROWS)
    json.dump(st, open(os.path.join(data, "nested_gap_state_depsdev_matched.json"), "w"))
    # the aligned and October files must DIFFER from the matched one, or the
    # pairwise-distinct hash gate cannot pass
    json.dump(dict(st, _aligned_marker={"skip": "fixture"}),
              open(os.path.join(data, "nested_gap_state_aligned.json"), "w"))
    json.dump(dict(st, _october_marker={"skip": "fixture"}),
              open(os.path.join(data, "nested_gap_state.json"), "w"))
    os.environ.update({"RECOMPUTE_DATA": data,
                       "RECOMPUTE_OUT": os.path.join(data, "out.json"),
                       "MATCHED_CUTOFF": CUTOFF,
                       "MCPLIB_TIMES": json.dumps(TIMES),
                       "MCPLIB_MODE": mode})
    # check_cutoff does sys.path.insert(0, HERE); import mcplib, where HERE is
    # the directory of the copy under test. The shim must sit beside it, and
    # the meta-test proves the shim is the one being used.
    open(os.path.join(d, "mcplib.py"), "w").write(MCPLIB_SHIM)
    path = os.path.join(d, "mod_under_test.py")
    open(path, "w").write(src if src is not None else open(MODULE).read())
    for mod in [k for k in sys.modules if k in ("mcplib", "mod_under_test")]:
        del sys.modules[mod]
    spec = importlib.util.spec_from_file_location("mod_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # the gate's golden is the real corpus figure; against the fixture it has
    # to be the fixture's own answer, derived from the table above
    m.PUBLISHED = dict(GOLD_PUBLISHED)
    return m


# ------------------------------------------------------------- unit level

def test_tree_from_state(m):
    data = os.environ["RECOMPUTE_DATA"]
    t = m.tree_from_state(os.path.join(data,
                                       "nested_gap_state_depsdev_matched.json"))
    check("T6 single excludes the duplicated name", "dup" in t["T6"]["resolved"],
          False)
    check("T6 multi holds both versions", t["T6"]["multi"]["dup"],
          ["1.0.0", "2.0.0"])
    check("T7 multi holds three", len(t["T7"]["multi"]["trip"]), 3)
    check("T1 has no multi", t["T1"]["multi"], {})
    # a token with no separator: rpartition yields an empty name, which used to
    # enter `resolved` and inflate the node count by one
    bad = os.path.join(os.environ["RECOMPUTE_DATA"], "bad_state.json")
    json.dump({"X": {"installed": ["noseparator", "a@@1.0.0"],
                     "published": [], "root_version": "1.0.0",
                     "truncated": False}}, open(bad, "w"))
    t2 = m.tree_from_state(bad)
    check("malformed token not admitted as a name", "" in t2["X"]["resolved"],
          False)


def test_instance_totals_counts_both_sides_alike(m):
    data = os.environ["RECOMPUTE_DATA"]
    dd = json.load(open(os.path.join(data, "depsdev_state.json")))
    right = m.tree_from_state(os.path.join(
        data, "nested_gap_state_depsdev_matched.json"))
    servers = sorted(ROWS)
    res, ddn, pct = m.instance_totals(right, dd, servers)
    # every (name, version) pair on the resolution side, duplicates included
    want_res = sum(len(ROWS[s]["single"]) + sum(len(v) for v in ROWS[s]["multi"].values())
                   for s in servers)
    want_dd = sum(len(ROWS[s]["dd"]) for s in servers)
    check("resolution instances count pairs", res, want_res)
    check("deps.dev instances are unreduced", ddn, want_dd)
    check("delta from the two totals", pct,
          round(100.0 * (want_res - want_dd) / max(want_dd, 1), 1))


def test_compare_against_the_table(m):
    data = os.environ["RECOMPUTE_DATA"]
    dd = json.load(open(os.path.join(data, "depsdev_state.json")))
    right = m.tree_from_state(os.path.join(
        data, "nested_gap_state_depsdev_matched.json"))
    r, rows = m.compare(dd, right, sorted(ROWS))
    # compare() reports the two delta conventions under their own names. The
    # bare `instance_delta_pct` alias is added only in the gated block, which
    # is itself worth pinning: the two conventions collapse whenever the multi
    # set is empty, so on the historical arm the alias is untestable.
    check("compare reports both delta conventions",
          {"instance_delta_pct_as_compared", "instance_delta_pct_comparable"}
          <= set(r), True)
    check("bare alias absent from compare", "instance_delta_pct" in r, False)
    want_matched, _, _, _, _ = _compare_by_hand(ROWS, sorted(ROWS))
    check("compare identical, matched arm", r["identical"], want_matched)
    check("rows per server", len(rows), len(ROWS))
    # the falsy deps.dev version: T5 is scored as AGREEING even though the
    # resolution has 9.9.9 and deps.dev has nothing usable
    t5 = next(x for x in rows if x["server"] == "T5")
    check("falsy deps.dev version scores as agreement", t5["version_differs"], 0)
    # the multi exclusion, per arm
    check("multi excluded, T6", next(x for x in rows if x["server"] == "T6")
          ["multi_version_in_resolution"], 1)
    check("multi excluded total", r["multi_version_names_excluded"], 2)
    check("servers with a multi name", r["servers_with_a_multi_version_name"], 2)
    check("deps.dev instances after exclusions differ from unmodified",
          r["instances_depsdev_after_exclusions"] <
          r["instances_depsdev_unmodified"], True)


def _rows_of(m):
    data = os.environ["RECOMPUTE_DATA"]
    dd = json.load(open(os.path.join(data, "depsdev_state.json")))
    right = m.tree_from_state(os.path.join(
        data, "nested_gap_state_depsdev_matched.json"))
    return m.compare(dd, right, sorted(ROWS))[1]


def test_median_is_the_upper_middle(m):
    data = os.environ["RECOMPUTE_DATA"]
    dd = json.load(open(os.path.join(data, "depsdev_state.json")))
    right = m.tree_from_state(os.path.join(
        data, "nested_gap_state_depsdev_matched.json"))
    r, _ = m.compare(dd, right, sorted(ROWS))
    # eight servers, two distinct middles. Pinning the shipped convention so a
    # change to it shows up rather than passing on a coincidence of n.
    check("median is the upper middle, not the lower",
          r["median_nodes_depsdev"], UPPER_MEDIAN)
    check("deps.dev node counts after exclusions", DD_N,
          sorted(x["depsdev_n"] for x in _rows_of(m)))
    check("upper and lower medians differ in the fixture",
          UPPER_MEDIAN != LOWER_MEDIAN, True)
    check("the mean differs from the upper median in the fixture",
          round(sum(DD_N) / len(DD_N)) != UPPER_MEDIAN, True)


def test_cutoff_coverage_and_modes(m):
    data = os.environ["RECOMPUTE_DATA"]
    arm = m.tree_from_state(os.path.join(
        data, "nested_gap_state_depsdev_matched.json"))
    servers = sorted(ROWS)
    late, cov = m.check_cutoff(arm, servers, CUTOFF)
    check("warm: nothing late", late, [])
    check("warm: pairs compared is non-zero", cov["pairs_compared"] > 0, True)
    check("warm: every pair compared", cov["pairs_compared"], cov["pairs_seen"])
    os.environ["MCPLIB_MODE"] = "raise"
    late2, cov2 = m.check_cutoff(arm, servers, CUTOFF)
    check("raise: still reports no violation", late2, [])
    check("raise: coverage is zero, which is the point", cov2["pairs_compared"], 0)
    check("raise: failures counted", cov2["packument_lookup_failed"] > 0, True)
    os.environ["MCPLIB_MODE"] = "none"
    _, cov3 = m.check_cutoff(arm, servers, CUTOFF)
    check("none: coverage is zero", cov3["pairs_compared"], 0)
    os.environ["MCPLIB_MODE"] = "late"
    late4, _ = m.check_cutoff(arm, servers, CUTOFF)
    check("late: violations found", len(late4) > 0, True)
    os.environ["MCPLIB_MODE"] = "warm"


def test_cutoff_boundary_and_naive(m):
    """At the instant, a microsecond after, and a naive timestamp."""
    arm = {"B": {"resolved": {"atinstant": "1.0.0"}, "multi": {}}}
    late, cov = m.check_cutoff(arm, ["B"], CUTOFF)
    check("at the instant is not late", late, [])
    check("at the instant was compared", cov["pairs_compared"], 1)
    after = {"B": {"resolved": {"edge": "1.3.1"}, "multi": {}}}
    late2, _ = m.check_cutoff(after, ["B"], CUTOFF)
    check("after the instant is late", len(late2), 1)
    naive = {"B": {"resolved": {"naive": "1.0.0"}, "multi": {}}}
    late3, cov3 = m.check_cutoff(naive, ["B"], CUTOFF)
    check("a naive timestamp does not raise", late3, [])
    check("a naive timestamp is counted, not compared",
          cov3["timestamp_unparseable"], 1)


def test_comparable_pair_uses_one_exclusion(m):
    """Both arms, one exclusion set, so the two rates are comparable."""
    data = os.environ["RECOMPUTE_DATA"]
    dd = json.load(open(os.path.join(data, "depsdev_state.json")))
    matched = m.tree_from_state(os.path.join(
        data, "nested_gap_state_depsdev_matched.json"))
    hist = m.tree_from_depsdev_file(os.path.join(
        data, "resolved_trees_for_depsdev.json"))
    servers = sorted(ROWS)
    excl = {s: set(matched[s]["multi"]) for s in servers}
    # The historical arm's own multi set is empty, so WITHOUT the override it
    # loses nothing from the deps.dev side while the matched arm loses two
    # names. That asymmetry is the defect; the override removes it.
    h_own, _ = m.compare(dd, hist, servers)
    h_common, _ = m.compare(dd, hist, servers, exclude=excl)
    m_own, _ = m.compare(dd, matched, servers)
    m_common, _ = m.compare(dd, matched, servers, exclude=excl)
    # The defect, stated as a measurement: with each arm using its own
    # exclusion the two left-hand sides are different sizes, because the
    # historical arm excludes nothing. With one exclusion they match.
    check("own exclusions give the two arms different left sides",
          h_own["instances_depsdev_after_exclusions"] ==
          m_own["instances_depsdev_after_exclusions"], False)
    check("one exclusion gives them the same left side",
          h_common["instances_depsdev_after_exclusions"],
          m_common["instances_depsdev_after_exclusions"])
    check("the exclusion reduces the historical left side too",
          h_common["instances_depsdev_after_exclusions"] <
          h_own["instances_depsdev_after_exclusions"], True)
    want = _compare_by_hand(
        {s: dict(ROWS[s], single=hist[s]["resolved"], multi={}) for s in servers},
        servers, exclude=excl)[0]
    check("historical under the common exclusion matches the table",
          h_common["identical"], want)
    m_common, _ = m.compare(dd, matched, servers, exclude=excl)
    check("both arms run on the same server count",
          h_common["comparable"], m_common["comparable"])


def test_derived_cause_and_the_slice(m):
    """The cause is computed, and its incidence must match the extra class."""
    out = _run_main(m)
    loo = out["arms"]["matched"]["leave_one_out"]
    check("cause_only suppresses one name", len(loo["cause_only"]["suppressed"]), 1)
    check("the derived cause is the top disagreement",
          loo["cause_only"]["suppressed"], ["edge"])
    check("symptom_only suppresses three", len(loo["symptom_only"]["suppressed"]), 3)
    check("cause not among the downstream three",
          set(loo["cause_only"]["suppressed"]) &
          set(loo["symptom_only"]["suppressed"]), set())
    # the tie at rank three: T8 contributes e1..e4 at one server each, d1..d3
    # at more, so the slice boundary sits inside a tie and the ORDER matters
    conc = dict(out["extra_class_concentration"])
    check("the extra class is ranked", conc["d1"] >= conc["e1"], True)
    # Twelve names tied at one occurrence each. The top-three slice therefore
    # sits above a tie of twelve, and the ORDER of the ranking decides nothing
    # about which three are taken only because the tie-break is explicit. Drop
    # the tie-break and the suppressed list becomes insertion-ordered.
    ties = sorted(v for k, v in conc.items() if k.startswith("e"))
    check("a tie of twelve sits below the slice", ties, [1] * 12)
    check("the slice takes the dominant three, not a tie member",
          all(not k.startswith("e") for k in
              out["arms"]["matched"]["leave_one_out"]["symptom_only"]["suppressed"]),
          True)


def test_leave_one_out_values(m):
    """Suppression must move the figures, and move them by the right amount."""
    out = _run_main(m)
    loo = out["arms"]["matched"]["leave_one_out"]
    servers = sorted(ROWS)
    excl = {s: set(ROWS[s]["multi"]) for s in servers}
    cause = loo["cause_only"]["suppressed"]
    sym = loo["symptom_only"]["suppressed"]
    both = loo["cause_and_symptom"]["suppressed"]
    check("suppressed lists are ordered, cause first", both[:1], cause)
    check("suppressed lists concatenate", both, list(cause) + list(sym))
    # The ordered list, not the set. Four extras are tied at the slice
    # boundary and the Counter's insertion order disagrees with the explicit
    # tie-break, so dropping the tie-break changes WHICH three are taken.
    check("symptom_only takes the tie-break's three, in order",
          sym, ["d1", "d2", "d3"])
    for label, sup in (("cause_only", cause), ("symptom_only", sym),
                       ("cause_and_symptom", both)):
        want = _compare_by_hand(ROWS, servers, suppress=tuple(sup))[0]
        check("loo %s identical_pct" % label, loo[label]["identical_pct"],
              round(100.0 * want / len(servers), 1))
    # suppression must actually move something, or the arms prove nothing
    check("cause_and_symptom beats the unsuppressed arm",
          loo["cause_and_symptom"]["identical_pct"] >
          out["arms"]["matched"]["identical_pct"], True)


def test_resolver_only_block(m):
    out = _run_main(m)
    ro = out["matched_vs_historical_all_four_rules"]
    n = ro["servers"]
    check("package-set partition sums", ro["identical_package_set"] +
          ro["differing_package_set"], n)
    check("version partition sums", ro["no_version_disagreement"] +
          ro["with_a_version_disagreement"], n)
    # the historical arm carries a multi name at one version; the matched arm
    # carries it at several. Counting the multi names in the package-set
    # comparison is what makes T6 and T7 agree on NAMES.
    # The historical arm carries dup and trip at one version each; the matched
    # arm carries them at several. Counting the multi names in the package-set
    # comparison is what makes those two servers agree on NAMES, and dropping
    # it moves this number, so the exact value is pinned.
    want_same = sum(
        1 for s_ in sorted(ROWS)
        if set(_hist_single(ROWS[s_])) ==
        set(ROWS[s_]["single"]) | set(ROWS[s_]["multi"]))
    check("identical package sets", ro["identical_package_set"], want_same)
    check("edge disagrees on three servers",
          ro["with_a_version_disagreement"], 3)


def test_comparable_pair_values(m):
    out = _run_main(m)
    pair = out["comparable_pair_one_exclusion_both_arms"]
    servers = sorted(ROWS)
    excl = {s: set(ROWS[s]["multi"]) for s in servers}
    hist = {s: dict(ROWS[s], single=_hist_single(ROWS[s]), multi={})
            for s in servers}
    sup = tuple(out["arms"]["matched"]["leave_one_out"]
                ["cause_and_symptom"]["suppressed"])
    for label, rows, s_ in (("historical_unsuppressed", hist, ()),
                            ("historical_suppressed", hist, sup),
                            ("matched_unsuppressed", ROWS, ()),
                            ("matched_suppressed", ROWS, sup)):
        want = _compare_by_hand(rows, servers, suppress=s_, exclude=excl)[0]
        check("pair %s identical" % label, pair[label]["identical"], want)
        check("pair %s pct" % label, pair[label]["identical_pct"],
              round(100.0 * want / len(servers), 1))
    # every row scored against the same left side: the field that proves the
    # common exclusion was applied, since the agreement count need not move
    # the two arms must agree in left-side size at each suppression level;
    # suppression itself shrinks both sides, so the levels differ from each other
    for level in ("unsuppressed", "suppressed"):
        check("pair scores one left side at the %s level" % level,
              len({v["depsdev_instances_as_scored"] for k, v in pair.items()
                   if isinstance(v, dict)
                   and k.rsplit("_", 1)[-1] == level}), 1)
    check("suppression shrinks the left side",
          pair["matched_suppressed"]["depsdev_instances_as_scored"] <
          pair["matched_unsuppressed"]["depsdev_instances_as_scored"], True)


def test_shipped_defaults(m):
    fresh = open(MODULE).read()
    check("cutoff default ships as 2026-09-08T01:00:00Z",
          'os.environ.get("MATCHED_CUTOFF", "2026-09-08T01:00:00Z")' in fresh,
          True)
    check("PUBLISHED ships six keys",
          fresh.count('PUBLISHED = {"comparable": 249'), 1)
    for frag in ('"identical": 154', '"identical_pct": 61.8',
                 '"version_differs_pct": 38.2', '"fewer_pct": 1.2',
                 '"instance_delta_pct": 0.2'):
        check("PUBLISHED carries %s" % frag, frag in fresh, True)
    check("no bare assert in the module", "\n    assert " not in fresh, True)
    check("require raises", "raise GateFailed" in fresh, True)


def _run_main(m):
    m.main()
    return json.load(open(m.OUT))


def test_main_end_to_end(m):
    out = _run_main(m)
    pair = out["comparable_pair_one_exclusion_both_arms"]
    for label in ("historical_unsuppressed", "historical_suppressed",
                  "matched_unsuppressed", "matched_suppressed"):
        check("pair has %s" % label, label in pair, True)
    check("pair reports a server count", pair["servers"], len(ROWS))
    check("pair names the exclusion", "exclusion" in pair, True)
    check("gated block reproduces the hand golden",
          {k: out["published_bound_reproduced"][k] for k in GOLD_PUBLISHED},
          GOLD_PUBLISHED)
    cov = out["provenance"]["cutoff_gate_coverage"]
    check("coverage reaches the output", cov["pairs_compared"] > 0, True)
    check("four arms reported", sorted(out["arms"]), 
          ["aligned", "historical", "matched", "october"])
    for arm in out["arms"].values():
        check("every arm covers the same servers", arm["comparable"], len(ROWS))


def test_cold_cache_is_refused(m):
    """A gate whose coverage is zero must raise, not pass."""
    os.environ["MCPLIB_MODE"] = "raise"
    try:
        try:
            m.main()
            check("cold cache refused", False, True)
        except m.GateFailed as e:
            check("cold cache refused", "not interpretable" in str(e), True)
    finally:
        os.environ["MCPLIB_MODE"] = "warm"


def test_identical_state_files_are_refused(m):
    """Two arms reading the same file is what the hashes exist to catch."""
    data = os.environ["RECOMPUTE_DATA"]
    a = os.path.join(data, "nested_gap_state_aligned.json")
    keep = open(a).read()
    open(a, "w").write(open(os.path.join(
        data, "nested_gap_state_depsdev_matched.json")).read())
    try:
        try:
            m.main()
            check("identical inputs refused", False, True)
        except m.GateFailed as e:
            check("identical inputs refused", "hash identically" in str(e), True)
    finally:
        open(a, "w").write(keep)


TESTS = (test_leave_one_out_values, test_resolver_only_block,
         test_comparable_pair_values,
         test_tree_from_state, test_instance_totals_counts_both_sides_alike,
         test_compare_against_the_table, test_median_is_the_upper_middle,
         test_cutoff_coverage_and_modes, test_cutoff_boundary_and_naive,
         test_comparable_pair_uses_one_exclusion,
         test_derived_cause_and_the_slice, test_shipped_defaults,
         test_main_end_to_end, test_cold_cache_is_refused,
         test_identical_state_files_are_refused)


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


# ------------------------------------------- mutations, designed by the review
# (name, old, new, what the reviewer said it would move)
MUTATIONS = [
    ("D1 lower median for upper median",
     '    med = lambda f: sorted(f(r) for r in rows)[n // 2] if n else None',
     '    med = lambda f: sorted(f(r) for r in rows)[(n - 1) // 2] if n else None',
     "mutation 1: moves all eight median fields by one order statistic; the "
     "gate is blind because its set has 249 servers and every reported arm "
     "has 248, where the two indices coincide"),
    ("D2 mean for median",
     '    med = lambda f: sorted(f(r) for r in rows)[n // 2] if n else None',
     '    med = lambda f: round(sum(f(r) for r in rows) / n) if n else None',
     "mutation 2: median_nodes_resolution 95 -> 85 inside a block whose name "
     "claims reproduction; PUBLISHED has no median key"),
    ("D3 multi exclusion dropped from the deps.dev side",
     "        ddn = {k: v for k, v in dd[name][\"nodes\"].items()\n"
     "               if k not in suppress and k not in drop}",
     "        ddn = {k: v for k, v in dd[name][\"nodes\"].items()\n"
     "               if k not in suppress}",
     "mutation 3: instances_depsdev_after_exclusions 20371 -> 21134, "
     "median_nodes_depsdev 94 -> 95, and the suppressed figure falls from "
     "79.4%; the gate is blind because the historical multi set is empty"),
    ("D4 suppression dropped from the resolution side",
     "        live = {k: v for k, v in live.items()\n"
     "                if k not in suppress and k not in drop}",
     "        live = {k: v for k, v in live.items() if k not in drop}",
     "mutation 4: the cause and its downstream names leave one side only, so "
     "cause_and_symptom collapses and misses_pct jumps; the gate never "
     "passes suppress"),
    ("D5 the falsy-version guard dropped",
     '        vdiff = [k for k in live if k in ddn and ddn[k] and live[k] != ddn[k]]',
     '        vdiff = [k for k in live if k in ddn and live[k] != ddn[k]]',
     "mutation 5: every deps.dev node with an empty version becomes a "
     "disagreement; the corpus has none, so only a fixture can catch it"),
    ("D6 multi names counted once instead of per version",
     '    res = sum(len(r["resolved"]) + sum(len(v) for v in r["multi"].values())',
     '    res = sum(len(r["resolved"]) + len(r["multi"])',
     "mutation 6: instances_resolution_all_pairs 22849 -> 21996 and the "
     "comparable delta 8.1 -> 4.1; the gate is blind on an empty multi"),
    ("D7 instance_totals reduces the left side",
     '    ddn = sum(len(dd[n]["nodes"]) for n in servers)',
     '    ddn = sum(len([k for k in dd[n]["nodes"] if k not in right[n]["multi"]])\n'
     '              for n in servers)',
     "mutation 7: the withdrawn defect returning; the comparable delta 8.1 "
     "-> 12.2 while instances_depsdev_unmodified still reads 21134"),
    ("D8 the multi diagnostic counts pairs, not names",
     '                     "multi_version_in_resolution": len(multi)})',
     '                     "multi_version_in_resolution":\n'
     '                         sum(len(v) for v in multi.values())})',
     "mutation 8: multi_version_names_excluded 817 -> 1670 while every "
     "headline percentage is untouched, a corrupted diagnostic behind "
     "correct verdicts"),
    ("D9 the single/multi boundary off by one",
     '        multi = {n: sorted(vs) for n, vs in seen.items() if len(vs) > 1}',
     '        multi = {n: sorted(vs) for n, vs in seen.items() if len(vs) > 2}',
     "mutation 9: names at exactly two versions fall out of single AND out of "
     "multi, so they vanish from the right side and become extras"),
    ("D10 TOP3 read off the wrong end of the ranking",
     '    TOP3 = tuple(k for k, _ in ranked_extras[:3])',
     '    TOP3 = tuple(k for k, _ in ranked_extras[-3:])',
     "mutation 10: suppresses the three rarest extras instead of the three "
     "dominant ones; cause_and_symptom 79.4 -> about 30.2"),
    ("D11 tie-break dropped from the extra ranking",
     '    ranked_extras = sorted(extra_counts.items(), key=lambda kv: (-kv[1], kv[0]))',
     '    ranked_extras = sorted(extra_counts.items(), key=lambda kv: -kv[1])',
     "mutation 11: near-equivalent on the corpus because both tied names sit "
     "inside the top three either way; live the moment a tie straddles the "
     "slice, which the fixture arranges"),
    ("D12 the resolver-only block stops counting multi names",
     '        names_h, names_m = set(h), set(m) | set(m_multi)',
     '        names_h, names_m = set(h), set(m)',
     "mutation 12: identical_package_set 76 falls and differing_package_set "
     "rises; resolver_only has no gate at all"),
    ("D13 the comparable pair loses its common exclusion",
     '        r, _ = compare(dd, arms[arm], pair_servers, suppress=sup,\n'
     '                       exclude=common_excl)',
     '        r, _ = compare(dd, arms[arm], pair_servers, suppress=sup)',
     "the defect the pair exists to remove: each arm back to its own "
     "exclusion, so the two rates are not comparable again"),
    ("D14 the derived cause back to a literal",
     '    CAUSE = (ranked_dis[0][0],)',
     '    CAUSE = ("get-intrinsic",)',
     "defect 9: a string literal under a comment claiming it was derived, "
     "which on any other input suppresses a name that does nothing"),
    ("D15 the cutoff coverage floor loosened to zero",
     '    require(cut_cover["pairs_compared"] * 4 >= cut_cover["pairs_seen"],',
     '    require(cut_cover["pairs_compared"] >= 0,',
     "defect 3: a cold cache, a None return or a raising lookup all pass, "
     "which is the shape of the check this one replaced"),
]

HARNESS = [
    ("E1 gate tolerance loosened to one unit",
     "        require(hist[k] == want,",
     "        require(abs(hist[k] - want) <= 1 if isinstance(want, (int, float))\n"
     "                else hist[k] == want,",
     "D5 the falsy-version guard dropped"),
    ("E2 the gate iterates only part of PUBLISHED",
     "    for k, want in PUBLISHED.items():",
     "    for k, want in list(PUBLISHED.items())[:3]:",
     "D1 lower median for upper median"),
    ("E3 the cutoff gate reads the wrong arm",
     '    late, cut_cover = check_cutoff(arms["matched"], cut_servers, CUTOFF)',
     '    late, cut_cover = check_cutoff(arms["historical"], cut_servers, CUTOFF)',
     "D15 the cutoff coverage floor loosened to zero"),
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
            ("off-by-one in the agreeing-server count",
             '        "identical": agree,', '        "identical": agree + 1,'),
            ("off-by-one in the comparable pair only",
             '        pair[label] = {"identical": r["identical"],',
             '        pair[label] = {"identical": r["identical"] + 1,'),
            ("the mcplib shim replaced by a late-publishing one",
             'CUTOFF = os.environ.get("MATCHED_CUTOFF", "2026-09-08T01:00:00Z")',
             'CUTOFF = "2020-01-01T00:00:00Z"')):
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
