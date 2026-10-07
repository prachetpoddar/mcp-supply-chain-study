#!/usr/bin/env python3
"""Tests for cra_advisory_delay.py.

The `classify` docstring in that file says the function was factored out "so the
boundaries can be tested". Until now nothing tested them. This file does, along
with the two estimators and the cell assembly, and it ends with a meta-test that
plants known defects and requires the suite to go red.

The planted mutations are NOT mine. They come from the independent review of
2026-10-06, because a self-authored mutation campaign measures the author's
imagination rather than the tests: every "disable the check" mutation an author
writes gets caught, and the semantic ones a reviewer writes walk straight
through a green suite.

    python3 code/test_advisory_delay.py
"""
import os, sys, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cra_advisory_delay as M

FAILED = []
CHECKS = [0]


def check(cond, what):
    CHECKS[0] += 1
    if not cond:
        FAILED.append(what)
        print(f"  FAIL  {what}")
    return bool(cond)


# ---------------------------------------------------------------- classify
def test_classify():
    print("classify boundaries")
    check(M.classify(-0.001) == "advisory_first", "lag just below zero is advisory_first")
    check(M.classify(-50.0) == "advisory_first", "a clearly negative lag is advisory_first")
    check(M.classify(0.0) == "prompt", "lag of exactly zero is prompt, not advisory_first")
    check(M.classify(29.999) == "prompt", "just inside the window is prompt")
    check(M.classify(float(M.PROMPT_DAYS)) == "prompt",
          "exactly PROMPT_DAYS is prompt (the protocol says within 30 days)")
    check(M.classify(M.PROMPT_DAYS + 0.001) == "delayed",
          "just past PROMPT_DAYS is delayed")
    check(M.classify(4000.0) == "delayed", "a long lag is delayed")


# ---------------------------------------------------------------- holm
def test_holm():
    print("holm step-down")
    ps = [0.01, 0.04, 0.03, 0.2]
    got = M.holm(ps)
    # sorted raw: .01 x4 = .04; .03 x3 = .09; .04 x2 = .08 but the running max
    # holds it at .09; .2 x1 = .2. Back in input order that is:
    want = [0.04, 0.09, 0.09, 0.2]
    check(all(abs(a - b) < 1e-12 for a, b in zip(got, want)),
          f"holm of {ps} is {want}, got {[round(x,4) for x in got]}")
    check(got[1] == got[2],
          "the running max holds a later smaller multiple at the earlier value")
    # input order, not sorted order: the smallest adjusted value must sit at the
    # index of the smallest raw p, which is index 0 here and index 2 below.
    ps2 = [0.2, 0.04, 0.01]
    g2 = M.holm(ps2)
    check(g2.index(min(g2)) == 2, "holm aligns adjusted values to input positions")
    check(all(b >= a for a, b in zip(sorted(g2), sorted(g2)[1:])), "holm is monotone")
    check(all(x <= 1.0 for x in M.holm([0.5, 0.6, 0.9])), "holm never exceeds 1")
    tied = M.holm([0.02, 0.02, 0.02])
    check(abs(tied[0] - 0.06) < 1e-12 and len({round(t, 12) for t in tied}) == 1,
          "equal p-values get equal adjusted values")


# ---------------------------------------------------------------- mh_odds
def test_mh():
    print("Mantel-Haenszel")
    # one stratum, a=10 b=5 c=5 d=10, n=30: num=10*10/30, den=5*5/30 -> OR 4
    check(abs(M.mh_odds([(10, 5, 5, 10)]) - 4.0) < 1e-12, "single stratum OR is a*d/b*c")
    # two strata pooled by weight, hand-computed
    tab = [(10, 5, 5, 10), (2, 8, 4, 6)]
    num = 10 * 10 / 30 + 2 * 6 / 20
    den = 5 * 5 / 30 + 8 * 4 / 20
    check(abs(M.mh_odds(tab) - num / den) < 1e-12, "two strata pool by 1/n weights")
    check(M.mh_odds([(0, 0, 0, 0)]) is None, "an empty table is not estimable")
    check(M.mh_odds([(5, 0, 0, 5)]) is None,
          "a zero denominator returns None rather than infinity")
    check(M.mh_odds([(0, 5, 5, 0)]) == 0.0,
          "a zero numerator returns 0.0, which is not None and must not be "
          "reported as 'too few resamples'")
    # the vectorised form must agree with the scalar one it replaces
    rnd = random.Random(7)
    worst = 0.0
    for _ in range(400):
        t = [tuple(rnd.randint(0, 20) for _ in range(4)) for _ in range(rnd.randint(1, 6))]
        a = M.mh_odds(t)
        b = M.mh_from_cells(np.array([t], dtype=float))[0]
        if a is None:
            if not np.isnan(b):
                worst = float("inf")
        else:
            worst = max(worst, abs(a - float(b)))
    check(worst < 1e-9, "mh_from_cells agrees with mh_odds on random tables")


# ---------------------------------------------------------------- cells
def row(pkg, year, cls, **kw):
    r = {"package": pkg, "fix_year": year, "cls": cls}
    r.update(kw)
    return r


def test_cells():
    print("cell assembly and orientation")
    rows = [row("a", 2024, "delayed", x=True),
            row("a", 2024, "prompt", x=True),
            row("b", 2024, "delayed", x=False),
            row("b", 2024, "prompt", x=False),
            row("b", 2024, "prompt", x=False)]
    pk, Mx = M.cells_by_package(rows, ["x"], [2024])
    tot = Mx.sum(0)[0, 0]
    check(list(tot) == [1, 1, 1, 2],
          f"cells are (exposed&delayed, exposed&prompt, unexposed&delayed, "
          f"unexposed&prompt); got {list(tot)}")
    # orientation: exposure concentrated in the delayed arm must give OR > 1
    rows2 = [row("p%d" % i, 2024, "delayed", x=True) for i in range(20)] + \
            [row("q%d" % i, 2024, "prompt", x=False) for i in range(20)] + \
            [row("r%d" % i, 2024, "prompt", x=True) for i in range(2)] + \
            [row("s%d" % i, 2024, "delayed", x=False) for i in range(2)]
    _, M2 = M.cells_by_package(rows2, ["x"], [2024])
    orr = float(M.mh_from_cells(M2.sum(0))[0])
    check(orr > 5, f"exposure concentrated in the delayed arm gives OR well above 1, got {orr:.2f}")
    # unknown exposure is excluded, not counted as the reference level
    rows3 = rows + [row("c", 2024, "delayed", x=None), row("c", 2024, "prompt", x=None)]
    _, M3 = M.cells_by_package(rows3, ["x"], [2024])
    check(list(M3.sum(0)[0, 0]) == [1, 1, 1, 2],
          "a row with unknown exposure changes no cell")
    # strata are kept apart
    rows4 = [row("a", 2023, "delayed", x=True), row("a", 2024, "prompt", x=True)]
    _, M4 = M.cells_by_package(rows4, ["x"], [2023, 2024])
    s = M4.sum(0)[0]
    check(list(s[0]) == [1, 0, 0, 0] and list(s[1]) == [0, 1, 0, 0],
          "rows land in the stratum of their own fix year")


# ------------------------------------------------- p-value and interval shape
def test_pvalue_convention():
    print("bootstrap p-value convention")
    # the convention used in family(): p = (2*k + 1)/(B + 1), so an all-one-sided
    # bootstrap gives a small p, never exactly zero.
    def p_of(bs):
        bs = np.sort(np.asarray(bs, dtype=float))
        neg, pos, zer = int((bs < 0).sum()), int((bs > 0).sum()), int((bs == 0).sum())
        return min(1.0, (2 * min(neg + zer, pos + zer) + 1) / (bs.size + 1))
    allpos = np.full(4000, 0.5)
    check(p_of(allpos) > 0.0, "an entirely one-sided bootstrap does not give p = 0")
    check(abs(p_of(allpos) - 1 / 4001) < 1e-12, "that p is 1/(B+1)")
    half = np.concatenate([np.full(2000, -0.5), np.full(2000, 0.5)])
    check(abs(p_of(half) - (2 * 2000 + 1) / 4001) < 1e-12, "a symmetric bootstrap gives p near 1")
    ties = np.concatenate([np.full(10, 0.0), np.full(3990, 0.5)])
    check(p_of(ties) == min(1.0, (2 * 10 + 1) / 4001), "a tie at zero counts on one side only")


# --------------------------------------------- family(), end to end, pinned
def synth_rows():
    """Deterministic rows: two strata, a known association, and packages of
    seven rows each, so that dropping the bootstrap's multiplicity weight or
    moving a quantile changes the published numbers."""
    rows = []
    for st, year in enumerate((2024, 2025)):
        for i in range(400):
            ex = (i % 4) in (0, 1)
            dl = (i % 10) < (3 if ex else 6)
            rows.append({"package": f"p{st}-{i // 7}", "fix_year": year,
                         "cls": "delayed" if dl else "prompt",
                         "x": ex, "y": (i % 3) == 0})
    return rows


# Golden values from the reviewed code at these settings and this seed. They pin
# the SHIPPED behaviour, not an overridden knob: a quantile moved from .975, a
# normal approximation in place of the percentile, the +1 dropped from the
# p-value denominator, or the multinomial weight dropped from the bootstrap all
# change at least one of these. Recorded 2026-10-07.
GOLD = {
    "x": (0.2857142857142857, 0.22118629994234773, 0.363644927449713,
          0.0004997501249375312, 0.0009995002498750624),
    "y": (0.9864864864864864, 0.7856781781506597, 1.2422952859719463,
          0.9480259870064968, 0.9480259870064968),
}
GOLD_THR = 1.365240336154284


def test_family_pinned():
    print("family(), end to end, against pinned values")
    keep = (M.BOOTSTRAP, M.PERMUTATIONS, M.CHUNK, M.BOOT_FLOOR)
    M.BOOTSTRAP, M.PERMUTATIONS, M.CHUNK, M.BOOT_FLOOR = 2000, 200, 500, 100
    try:
        out = {}
        M.family(synth_rows(), [("x", "exposure x", +1), ("y", "exposure y", 0)],
                 "synthetic", out)
    finally:
        M.BOOTSTRAP, M.PERMUTATIONS, M.CHUNK, M.BOOT_FLOOR = keep
    f = out["synthetic"]
    check(f["n_analysed"] == 800, "every synthetic row is analysed")
    got = {x["key"]: x for x in f["findings"]}
    check(set(got) == {"x", "y"}, "both synthetic contrasts are estimated")
    for key, (orr, lo, hi, pv, hl) in GOLD.items():
        g = got.get(key)
        if not g:
            continue
        check(abs(g["or"] - orr) < 1e-12, f"{key}: pooled odds ratio is pinned")
        check(abs(g["ci"][0] - lo) < 1e-12, f"{key}: lower interval bound is pinned")
        check(abs(g["ci"][1] - hi) < 1e-12, f"{key}: upper interval bound is pinned")
        check(abs(g["p"] - pv) < 1e-15, f"{key}: bootstrap p-value is pinned")
        check(abs(g["holm"] - hl) < 1e-15, f"{key}: adjusted p-value is pinned")
    check(abs(f["permutation_family_threshold_or"] - GOLD_THR) < 1e-12,
          "the permutation threshold is pinned")
    check(f["permutation_family_threshold_or"] > 1.0,
          "the permutation threshold exceeds 1, as any spread of |log OR| must")
    check(got["x"]["p"] > 0.0, "a one-sided bootstrap never reports p of exactly zero")
    check(abs(got["x"]["p"] - 1 / 2001) < 1e-12,
          "an entirely one-sided bootstrap reports (0+1)/(B+1), not 0")
    # the interval must contain the point estimate it belongs to
    for key, g in got.items():
        check(g["ci"][0] <= g["or"] <= g["ci"][1],
              f"{key}: the interval contains its own point estimate")


# --------------------------------------------- homogeneity
def test_breslow_day():
    print("Breslow-Day and the chi-square tail")
    for x, k, want in ((3.841, 1, 0.05), (5.991, 2, 0.05), (16.919, 9, 0.05)):
        check(abs(M.chi_sf(x, k) - want) < 0.002,
              f"chi_sf({x}, {k}) is about {want}, got {M.chi_sf(x, k):.4f}")
    check(M.chi_sf(0.0, 4) > 0.99, "a statistic of zero does not reject")
    check(M.chi_sf(1e4, 4) < 1e-9, "a huge statistic rejects")
    check(M.chi_sf(5.0, 0) == 1.0, "no degrees of freedom means no test")
    # identical strata cannot be heterogeneous; opposed strata must be
    same = [(20, 40, 40, 40), (10, 20, 20, 20), (30, 60, 60, 60)]
    X, df = M.breslow_day(same, M.mh_odds(same))
    check(X < 1e-6 and df == 2, f"identical strata give X2 of 0 on 2 df, got {X:.3g} on {df}")
    opp = [(60, 10, 10, 60), (10, 60, 60, 10)]
    X2, df2 = M.breslow_day(opp, M.mh_odds(opp))
    check(M.chi_sf(X2, df2) < 1e-6,
          f"strata with opposite associations reject homogeneity, p={M.chi_sf(X2, df2):.3g}")
    # a stratum with an empty margin carries no information about homogeneity
    X3, df3 = M.breslow_day(same + [(5, 0, 9, 0)], M.mh_odds(same + [(5, 0, 9, 0)]))
    check(df3 == 2, f"an empty-margin stratum does not add a degree of freedom, got {df3}")
    n, dn = M.mh_parts([(5, 0, 0, 5)])
    check(n > 0 and dn == 0, "mh_parts separates perfect separation from an empty table")
    n2, dn2 = M.mh_parts([(0, 5, 5, 0)])
    check(n2 == 0 and dn2 > 0, "mh_parts shows a zero numerator as zero, not as None")


# ---------------------------------------------------------------- meta-test
def meta():
    """Plant the reviewer's mutations and require the suite to notice.

    An equivalent mutant (one whose branch is unreachable in a healthy run) is
    not a finding and is not listed here.
    """
    print("\nmeta-test: planting the reviewer's mutations")
    planted = [
        ("classify: lag <= 30 becomes lag < 30 (reviewer mutation 1)",
         lambda: setattr(M, "classify",
                         lambda lag: "advisory_first" if lag < 0
                         else ("prompt" if lag < M.PROMPT_DAYS else "delayed")),
         test_classify),
        ("classify: lag < 0 becomes lag <= 0 (reviewer mutation 2)",
         lambda: setattr(M, "classify",
                         lambda lag: "advisory_first" if lag <= 0
                         else ("prompt" if lag <= M.PROMPT_DAYS else "delayed")),
         test_classify),
        ("cells: a and b swapped (reviewer mutation 3)",
         lambda: setattr(M, "cells_by_package", _swapped_cells),
         test_cells),
        ("Mantel-Haenszel: a*c over b*d (reviewer mutation 4)",
         lambda: setattr(M, "mh_odds", _mispaired_mh),
         test_mh),
        ("holm: adjusted values returned in sorted order, not input order",
         lambda: setattr(M, "holm", lambda ps: sorted(M_holm_original(ps))),
         test_holm),
        ("bootstrap: multiplicity weight dropped, a 63% subsample (mutation M5)",
         lambda: setattr(M, "bootstrap_logs", _unweighted_bootstrap),
         test_family_pinned),
        ("Breslow-Day: expected count from the marginal product, ignoring the "
         "common odds ratio (mutation M13)",
         lambda: setattr(M, "breslow_day", _marginal_bd),
         test_breslow_day),
    ]
    originals = {k: getattr(M, k) for k in
                 ("classify", "cells_by_package", "mh_odds", "holm",
                  "bootstrap_logs", "breslow_day")}
    caught = 0
    for name, apply_mutation, suite in planted:
        for k, v in originals.items():
            setattr(M, k, v)
        apply_mutation()
        before = len(FAILED)
        try:
            suite()
        except Exception as e:
            FAILED.append(f"{name}: raised {type(e).__name__}")
        went_red = len(FAILED) > before
        del FAILED[before:]
        print(f"  {'caught  ' if went_red else 'SURVIVED'} {name}")
        caught += went_red
    for k, v in originals.items():
        setattr(M, k, v)
    return caught, len(planted)


def _swapped_cells(rows, keys, years):
    pk, Mx = M_cells_original(rows, keys, years)
    out = Mx.copy()
    out[..., 0], out[..., 1] = Mx[..., 1].copy(), Mx[..., 0].copy()
    return pk, out


def _unweighted_bootstrap(Mx, n_pkg, n_keys, n_strata, seed=None):
    """Mutation M5: the multiplicity weight dropped, so each draw becomes an
    unweighted subsample of the packages that happened to be drawn at least
    once. The point estimate barely moves; every interval widens."""
    rng = np.random.default_rng(M.SEED if seed is None else seed)
    flat = Mx.reshape(n_pkg, -1)
    logs = np.full((M.BOOTSTRAP, n_keys), np.nan)
    at = 0
    while at < M.BOOTSTRAP:
        ch = min(M.CHUNK, M.BOOTSTRAP - at)
        mult = rng.multinomial(n_pkg, np.full(n_pkg, 1.0 / n_pkg), size=ch)
        cnt = ((mult > 0).astype(float) @ flat).reshape(ch, n_keys, n_strata, 4)
        orr = M.mh_from_cells(cnt)
        good = (orr > 0) & np.isfinite(orr)
        blk = np.full(orr.shape, np.nan)
        blk[good] = np.log(orr[good])
        logs[at:at + ch] = blk
        at += ch
    return logs


def _marginal_bd(cells, mh):
    X, used = 0.0, 0
    for a, b, c, d in cells:
        n1, n0 = a + b, c + d
        m1, n = a + c, a + b + c + d
        if min(n1, n0, m1, n - m1) == 0:
            continue
        ea = n1 * m1 / n
        eb, ec, ed = n1 - ea, m1 - ea, n0 - m1 + ea
        v = 1.0 / (1 / ea + 1 / eb + 1 / ec + 1 / ed)
        X += (a - ea) ** 2 / v
        used += 1
    return X, max(used - 1, 0)


def _mispaired_mh(tab):
    num = den = 0.0
    for a, b, c, d in tab:
        n = a + b + c + d
        if n == 0:
            continue
        num += a * c / n
        den += b * d / n
    return (num / den) if den > 0 else None


M_holm_original = M.holm
M_cells_original = M.cells_by_package
M_bootstrap_original = M.bootstrap_logs

if __name__ == "__main__":
    for t in (test_classify, test_holm, test_mh, test_cells, test_pvalue_convention,
              test_breslow_day, test_family_pinned):
        t()
    real_failures = list(FAILED)
    caught, total = meta()
    print(f"\n{CHECKS[0]} checks ran")
    if real_failures:
        print(f"FAILURES ({len(real_failures)}):")
        for f in real_failures:
            print("  -", f)
    print(f"mutations caught: {caught} of {total}")
    print("\nWhere this stops: covered are classify, holm, both Mantel-Haenszel "
          "forms, the cell assembly, Breslow-Day and chi_sf, and family() end to "
          "end against pinned values, which reaches its quantiles, its p-value "
          "and its permutation threshold. NOT covered: _rows() and report(), so "
          "a mutation in the row builder (exposure on names, a swapped operand "
          "in the follow-up gate, the horizon field) still passes. Each guard "
          "added here can itself be mutated; this is where the regress stops.")
    bad = bool(real_failures) or caught != total
    sys.exit(1 if bad else 0)
