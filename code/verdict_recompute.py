#!/usr/bin/env python3
"""
PREREGISTRATION-8. The deps.dev advisory verdict, recomputed on shipping inputs.

WHAT THIS SUPERSEDES, AND DOES NOT REPRODUCE
    results/final_verified.json reports, under `depsdev`, 2 of 249 servers,
    0.8%, six missed findings at three high and three moderate, zero phantom.
    That figure carries the three defects RESOLVER-NOTES.md already records for
    its frozen sibling: both sides were keyed on package name at one version
    each, its arms predate the dist-tag, deprecation and time-travel
    corrections that landed 11 to 17 September, and its inputs lived in
    /tmp/mcpres, which is gone. Bit-reproduction is therefore impossible and is
    not attempted. The protocol fixes that before any figure is computed so a
    close result cannot be presented as a reproduction.

COUNTING UNIT
    One finding per (package name, advisory id) per server, matching
    code/nested_gap.py so the two studies are commensurable. An advisory
    covering two version ranges of one package counts once; counting rows
    instead is what inflated a published phantom count from 4,442 to 6,791.

    python3 code/verdict_recompute.py

    Writes data/verdict_recompute.json. Reads nothing from the network.
"""
import collections, hashlib, json, os, sys
import nodesemver as sv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Overridable so a test suite can point every input at a fixture
# directory. The module reads its advisory snapshot at import time,
# so the harness cannot rebind the path after importing.
DATA = os.environ.get("VERDICT_DATA") or os.path.join(ROOT, "data")

DEPSDEV_PAIRS = os.path.join(DATA, "depsdev_pairs.json")
# depsdev_pairs.py stored only the node pairs, never the root version it queried,
# so the root-version rule in the protocol's population definition degraded to a
# no-op and the result reported an empty mismatch list from a check that ran on
# zero servers. The queried version is recoverable: the fetcher read its roots
# from this file.
FETCH_ROOTS = os.path.join(DATA, "resolved_trees_for_depsdev.json")
MATCHED = os.path.join(DATA, "nested_gap_state_depsdev_matched.json")
OCTOBER = os.path.join(DATA, "nested_gap_state.json")
ADVISORIES = os.path.join(DATA, "advisories_npm.json")
ADV_META = os.path.join(DATA, "advisories_npm_meta.json")
NESTED_PUBLISHED = os.path.join(DATA, "nested_gap.json")
OUT = os.path.join(DATA, "verdict_recompute.json")

MATCHED_CUTOFF = "2026-09-08T01:00:00Z"
# A module constant so a fixture suite can lower it AND assert the shipped
# value. A knob exercised only by overriding it proves the knob works and says
# nothing about the number that ships.
FORWARD_FLOOR = 100
# The prerelease probe's case, as a module constant so a fixture suite can
# substitute its own. The shipped value is asserted by the suite separately.
PRERELEASE_PROBE = ("multer", "1.4.5-lts.2")
SEV = ["critical", "high", "moderate", "low"]

# The harness gate reproduces these from data/nested_gap.json, which was
# computed by code/nested_gap.py on the same advisory snapshot. It gates the
# advisory join, not the new comparison.
# The severity breakdowns and the tree-level counts are in the same published
# file and the harness gate used to compute them and throw them away. With only
# the four totals checked, mis-keying the severity lookup from (package,
# advisory) to package alone turned every severity into "unknown" and walked
# through the whole suite. Whatever the gate computes, it now checks.
PUBLISHED_NESTED = {"trees": 249, "phantom_trees": 164,
                    "phantom_findings": 4442, "missed_findings": 15,
                    "missed_trees": 2, "verdict_differs": 164,
                    "trees_with_live_findings": 37,
                    "missed_by_severity": {"high": 12, "moderate": 3},
                    "phantom_by_severity": {"critical": 8, "high": 1346,
                                            "low": 283, "moderate": 2805}}

# Recorded so the result can state what it supersedes. Never compared against.
SUPERSEDED = {"source": "results/final_verified.json depsdev block",
              "n": 249, "verdict_differs": 2, "pct": 0.8,
              "missed_findings": 6, "phantom_findings": 0,
              "why_not_reproducible": [
                  "name-keyed on both sides",
                  "arms predate the 11-17 September resolver corrections",
                  "inputs lived in /tmp/mcpres, which is gone"]}


class GateFailed(RuntimeError):
    pass


CHECKS = []


def require(cond, msg):
    """Record a gate check and raise if it fails.

    A raise, not an assert: python3 -O strips assertions and would leave the
    output byte-indistinguishable from a gated run.
    """
    CHECKS.append(msg)
    if not cond:
        raise GateFailed(msg)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def split(x):
    """'name@@version' -> (name, version). Scoped names contain one @ already."""
    i = x.rindex("@@")
    return x[:i], x[i + 2:]


ADV = json.load(open(ADVISORIES))

SEV_OF = {}
for _nm, _rows in ADV.items():
    for _r in _rows:
        SEV_OF.setdefault((_nm, _r.get("id")), _r.get("severity"))

_VIDS = {}

# (name, version) pairs for which every range comparison raised. Amendment two:
# vids swallowed these silently, so a quietly sparse side could not be told
# apart from a clean one. A side whose versions do not parse can only produce
# missed findings, never phantom, which is the signature the primary arm
# reports, so this must be countable per side.
BAD_VERSIONS = set()


def vids(name, ver, pre=True, loose=True):
    """Advisory ids whose vulnerable range contains this version, deduplicated.

    include_prerelease is required: >=0.0.0 does not otherwise match
    1.4.5-lts.2, which is how multer was once reported clean while sitting
    inside eleven advisories.
    """
    k = (name, ver, pre, loose)
    if k in _VIDS:
        return _VIDS[k]
    o = set()
    tried = raised = 0
    for a in ADV.get(name) or []:
        r = a.get("vulnerable_versions")
        if not r:
            continue
        tried += 1
        try:
            if sv.satisfies(ver, r, loose=loose, include_prerelease=pre):
                o.add(a.get("id"))
        except Exception:
            raised += 1
    if tried and raised == tried:
        BAD_VERSIONS.add((name, ver))
    o = frozenset(o)
    _VIDS[k] = o
    return o


def _safe_satisfies(ver, rng):
    try:
        return sv.satisfies(ver, rng, loose=True, include_prerelease=True)
    except Exception:
        return False


def unparseable(pairs):
    """How many (name, version) on this side had every range comparison raise."""
    return sum(1 for n, v in pairs if (n, v) in BAD_VERSIONS)


def findings(pairs):
    """Finding set for an iterable of (name, version). One per (name, id)."""
    return {(n, a) for n, v in pairs for a in vids(n, v)}


def sev_counts(fset):
    c = collections.Counter()
    for nm, a in fset:
        c[SEV_OF.get((nm, a))] += 1
    return c


def by_sev(c):
    """Severity breakdown that cannot silently drop a finding.

    The earlier version keyed only on the four names in SEV, so any other
    severity, None included, vanished from the breakdown while the total kept
    it. Unknown keys are now carried under their own name and the caller
    asserts the breakdown sums to the total.
    """
    out = {k: c.get(k, 0) for k in SEV if c.get(k, 0)}
    for k, v in c.items():
        if k not in SEV and v:
            out["unknown:%s" % k] = v
    return out


def keep_last(pairs):
    """One version per name, last occurrence wins."""
    m = {}
    for n, v in pairs:
        m[n] = v
    return list(m.items())


def keep_first(pairs):
    """One version per name, first occurrence wins."""
    m = {}
    for n, v in pairs:
        m.setdefault(n, v)
    return list(m.items())


# Amendment two. The flattened comparison is not identified, so it is reported
# as a range over every tie-break combination rather than as a point estimate.
# The resolution side's node list is sorted, so last-wins is the semver maximum
# in all 819 duplicated groups; the deps.dev side's pair list is unsorted on 176
# of 249 servers, so last-wins there is whatever order the API returned.
TIE_BREAKS = {"depsdev_last/resolution_last": (keep_last, keep_last),
              "depsdev_first/resolution_last": (keep_first, keep_last),
              "depsdev_last/resolution_first": (keep_last, keep_first),
              "depsdev_first/resolution_first": (keep_first, keep_first)}


def arm_pairs(state):
    """server -> list of (name, version) from a nested_gap state file."""
    out = {}
    for srv, rec in state.items():
        if not isinstance(rec, dict) or "installed" not in rec:
            continue
        if rec.get("truncated"):
            continue
        out[srv] = [split(x) for x in rec["installed"]]
    return out


def depsdev_pairs(state):
    out = {}
    for srv, rec in state.items():
        if not isinstance(rec, dict) or not rec.get("ok"):
            continue
        out[srv] = [(p[0], p[1]) for p in rec["pairs"]]
    return out


def compare(left, right, servers, suppress=frozenset(), flat=None,
            suppress_left_only=False):
    """Verdict comparison over a fixed server set.

    left is the deps.dev side, right the resolution side. Both sides go through
    the same finding function and the same suppression, so a reduction applied
    to one is applied to the other. `flat`, when given, is a pair of
    flattening functions, one per side.

    suppress_left_only exists so the symmetry gate can prove that a one-sided
    reduction changes the answer. It is never used by a reported arm.
    """
    differ = miss_srv = ph_srv = right_any = 0
    msev, psev = collections.Counter(), collections.Counter()
    mby, pby = collections.Counter(), collections.Counter()
    tot_l = tot_r = bad_l = bad_r = 0
    for s in servers:
        lp, rp = left[s], right[s]
        if flat:
            lp, rp = flat[0](lp), flat[1](rp)
        L, R = findings(lp), findings(rp)
        # After findings(), not before: BAD_VERSIONS is filled lazily inside
        # vids, which findings() is the first thing to reach. Counting first
        # reported zero on the first compare over any given arm and the true
        # count on every later one.
        bad_l += unparseable(lp)
        bad_r += unparseable(rp)
        if suppress:
            L = {(n, a) for n, a in L if n not in suppress}
            if not suppress_left_only:
                R = {(n, a) for n, a in R if n not in suppress}
        tot_l += len(L)
        tot_r += len(R)
        missed, phantom = R - L, L - R
        if R:
            right_any += 1
        if L != R:
            differ += 1
        if missed:
            miss_srv += 1
        if phantom:
            ph_srv += 1
        msev += sev_counts(missed)
        psev += sev_counts(phantom)
        for n, _ in missed:
            mby[n] += 1
        for n, _ in phantom:
            pby[n] += 1
    n = len(servers)
    mf, pf = sum(msev.values()), sum(psev.values())
    msev_out, psev_out = by_sev(msev), by_sev(psev)
    # Amendment two: the breakdowns are presented as a decomposition, so they
    # must sum to the totals they decompose. Nothing asserted this before.
    require(sum(msev_out.values()) == mf,
            "missed severity breakdown sums to %d, total is %d"
            % (sum(msev_out.values()), mf))
    require(sum(psev_out.values()) == pf,
            "phantom severity breakdown sums to %d, total is %d"
            % (sum(psev_out.values()), pf))
    rank = lambda d: dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))
    return {
        "servers": n,
        "servers_with_a_finding_on_the_resolution_side": right_any,
        "verdict_differs": differ,
        "verdict_differs_pct": round(100 * differ / n, 1) if n else None,
        "missed_servers": miss_srv,
        "missed_findings": mf,
        "missed_by_severity": msev_out,
        "missed_by_package": rank(mby),
        "phantom_servers": ph_srv,
        "phantom_findings": pf,
        "phantom_by_severity": psev_out,
        "phantom_by_package": rank(pby),
        "total_findings_depsdev_side": tot_l,
        "total_findings_resolution_side": tot_r,
        "unparseable_versions_depsdev_side": bad_l,
        "unparseable_versions_resolution_side": bad_r,
    }


def gate_harness_reproduction():
    """Reproduce data/nested_gap.json's figures through this file's join.

    Gates the advisory join and the counting unit. If this drifts, every figure
    below is suspect regardless of how plausible it looks.
    """
    state = json.load(open(OCTOBER))
    s = {k: v for k, v in state.items()
         if isinstance(v, dict) and "skip" not in v and not v.get("truncated")}
    differ = ph_tr = m_tr = live_any = 0
    msev, psev = collections.Counter(), collections.Counter()
    for v in s.values():
        p = findings(split(x) for x in v["published"])
        q = findings(split(x) for x in v["installed"])
        missed, phantom = q - p, p - q
        if q:
            live_any += 1
        if missed or phantom:
            differ += 1
        if phantom:
            ph_tr += 1
        if missed:
            m_tr += 1
        msev += sev_counts(missed)
        psev += sev_counts(phantom)
    got = {"trees": len(s), "phantom_trees": ph_tr,
           "phantom_findings": sum(psev.values()),
           "missed_findings": sum(msev.values()),
           "missed_trees": m_tr, "verdict_differs": differ,
           "trees_with_live_findings": live_any,
           "missed_by_severity": dict(sorted(by_sev(msev).items())),
           "phantom_by_severity": dict(sorted(by_sev(psev).items()))}
    require(set(got) == set(PUBLISHED_NESTED),
            "harness reproduction: key sets differ, %r vs %r"
            % (sorted(got), sorted(PUBLISHED_NESTED)))
    for k in sorted(PUBLISHED_NESTED):
        require(got[k] == PUBLISHED_NESTED[k],
                "harness reproduction: %s is %r, published is %r"
                % (k, got[k], PUBLISHED_NESTED[k]))
    return got


def range_sanity():
    """Ranges that no structural read can make sense of.

    The second review established that nodesemver in loose mode does NOT raise
    on a malformed range: `satisfies("1.2.3", ">=1.0.0 <<>> 2", loose=True)`
    returns True, manufacturing a finding out of a garbled string. It raises
    only on an unparseable VERSION. So BAD_VERSIONS instruments a channel that
    is empty on this snapshot and is blind by construction to the channel that
    can silently inflate a finding count. This counts ranges whose comparator
    tokens do not read as semver comparators, which is a weak structural test
    and is reported as a count rather than gated on.
    """
    import re
    tok = re.compile(r"^(\^|~|>=|<=|>|<|=|v)?[0-9xX*][0-9a-zA-Z.\-+*xX]*$")
    bad, total = [], 0
    for nm, rows in ADV.items():
        for r in rows:
            vr = r.get("vulnerable_versions")
            if not vr:
                continue
            total += 1
            parts = [t for t in vr.replace("||", " ").split() if t]
            if parts and not all(tok.match(t) or t == "-" for t in parts):
                bad.append("%s %s %s" % (nm, r.get("id"), vr))
    return {"ranges_read": total, "structurally_odd": len(bad),
            "examples": sorted(bad)[:8],
            "note": "a count, not a gate: loose mode does not raise on a "
                    "malformed range, so this is the only visibility into that "
                    "channel and it is a weak structural test"}


def gate_prerelease_probe():
    nm, ver = PRERELEASE_PROBE
    got = vids(nm, ver)
    require(len(got) > 0,
            "prerelease probe: %s@%s matched no advisory, so "
            "include_prerelease was lost" % (nm, ver))
    require(len(vids(nm, ver, pre=False)) < len(got),
            "prerelease probe is vacuous: %s@%s matches the same advisories "
            "with include_prerelease off, so it cannot detect the flag"
            % (nm, ver))
    return len(got)


def gate_double_count_probe():
    """One advisory spanning two DISTINCT ranges of one package yields one finding.

    Amendment two. The earlier probe counted matching ids inside the frozenset
    vids returns, so its count was bounded at one for every possible input and
    the check could not fail. It also selected a degenerate case: ghost at
    0.0.0, a version mined out of a >=0.0.0 lower bound, whose advisory carried
    the same range string twice.

    This version builds the row-counting join alongside the deduplicated one and
    requires the row count to EXCEED the deduplicated count. Reintroducing the
    row-counting defect makes rows == dedup and this raises.
    """
    case = None
    for nm, rows in ADV.items():
        per = collections.defaultdict(list)
        for r in rows:
            vr = r.get("vulnerable_versions")
            if vr:
                per[r.get("id")].append(vr)
        for aid, ranges in per.items():
            distinct = sorted(set(ranges))
            if len(distinct) < 2:
                continue
            cands = set()
            for vr in distinct:
                for tok in vr.replace("<", " ").replace(">", " ").replace("=", " ").split():
                    if tok and tok[0].isdigit() and tok != "0.0.0":
                        cands.add(tok)
            for c in sorted(cands):
                hit = sum(1 for rr in distinct
                          if _safe_satisfies(c, rr))
                if hit >= 2:
                    case = (nm, c, aid, hit, len(distinct), tuple(ranges))
                    break
            if case:
                break
        if case:
            break
    require(case is not None,
            "double-count probe: no package in the snapshot has one advisory "
            "with two distinct ranges both containing a non-zero version, so "
            "the probe cannot run")
    nm, ver, aid, hit, ndistinct, raw_ranges = case
    # Re-derive distinctness from the raw rows rather than from the local the
    # selection loop built. The earlier premise check read that same local, so a
    # mutation that stopped de-duplicating ranges defeated the check meant to
    # catch it: a guard that reads the thing it guards is not a guard.
    fresh = {r["vulnerable_versions"] for r in ADV[nm]
             if r.get("id") == aid and r.get("vulnerable_versions")}
    require(len(fresh) >= 2,
            "double-count probe premise violated: %s carries %d distinct "
            "ranges for %s (raw rows %d), two distinct are required"
            % (nm, len(fresh), aid, len(raw_ranges)))
    require(sum(1 for rr in fresh if _safe_satisfies(ver, rr)) >= 2,
            "double-count probe premise violated: fewer than two of %s's "
            "distinct ranges contain %s" % (aid, ver))
    require(hit >= 2,
            "double-count probe premise violated: only %d of %s's distinct "
            "ranges contain %s" % (hit, aid, ver))
    rows_join = sum(1 for r in ADV[nm]
                    if r.get("id") == aid and r.get("vulnerable_versions")
                    and _safe_satisfies(ver, r["vulnerable_versions"]))
    dedup_join = sum(1 for x in vids(nm, ver) if x == aid)
    require(dedup_join == 1,
            "double-count probe: %s@%s produced %d findings for %s, expected 1"
            % (nm, ver, dedup_join, aid))
    require(rows_join > dedup_join,
            "double-count probe is vacuous on this case: the row-counting join "
            "gives %d and the deduplicated join gives %d, so the probe cannot "
            "detect row counting" % (rows_join, dedup_join))
    return {"package": nm, "version": ver, "advisory": aid,
            "distinct_ranges_for_that_advisory": len(fresh),
            "distinct_ranges_containing_the_version": hit,
            "row_counting_join": rows_join, "deduplicated_join": dedup_join}


def gate_orientation():
    """missed is resolution-side-only; phantom is deps.dev-side-only.

    The planted-defect run showed that swapping the two assignments in
    compare() changes every reported figure and trips nothing, because no gate
    reads orientation. This fixes the direction on a constructed pair where the
    answer is known in advance and cannot move with the data: a left side
    carrying a package at a vulnerable version against a right side carrying
    nothing must produce a phantom and no missed, and the reverse must produce a
    missed and no phantom.
    """
    probe = None
    for nm, rows in ADV.items():
        for r in rows:
            vr = r.get("vulnerable_versions") or ""
            for tok in vr.replace("<", " ").replace(">", " ").replace("=", " ").split():
                if tok and tok[0].isdigit() and tok != "0.0.0":
                    if _safe_satisfies(tok, vr):
                        probe = (nm, tok)
                        break
            if probe:
                break
        if probe:
            break
    require(probe is not None,
            "orientation probe: no (package, version) in the snapshot sits "
            "inside one of its own ranges, so the probe cannot run")
    nm, ver = probe
    require(len(vids(nm, ver)) > 0,
            "orientation probe: %s@%s matched no advisory" % (nm, ver))
    left_only = compare({"p": [(nm, ver)]}, {"p": []}, ["p"])
    right_only = compare({"p": []}, {"p": [(nm, ver)]}, ["p"])
    # Every PAIRED field, not just the two totals. Swapping the per-server
    # counters, or the by-package accumulators, left the two totals correct and
    # walked through the earlier version of this probe while printing output
    # that contradicted itself: eight missed findings over zero missed servers.
    for label, r, want in (("deps.dev side only", left_only, "phantom"),
                           ("resolution side only", right_only, "missed")):
        other = "missed" if want == "phantom" else "phantom"
        require(r[want + "_findings"] > 0 and r[other + "_findings"] == 0,
                "orientation probe, %s: findings came out missed %d phantom %d, "
                "expected %s only"
                % (label, r["missed_findings"], r["phantom_findings"], want))
        require(r[want + "_servers"] == 1 and r[other + "_servers"] == 0,
                "orientation probe, %s: servers came out missed %d phantom %d, "
                "expected one %s server"
                % (label, r["missed_servers"], r["phantom_servers"], want))
        require(r[want + "_by_package"] and not r[other + "_by_package"],
                "orientation probe, %s: by-package breakdowns came out missed "
                "%r phantom %r, expected %s only"
                % (label, r["missed_by_package"], r["phantom_by_package"], want))
        require(sum(r[want + "_by_severity"].values()) == r[want + "_findings"],
                "orientation probe, %s: %s severity breakdown does not sum"
                % (label, want))
    return {"probe": "%s@%s" % (nm, ver),
            "advisories_it_sits_in": len(vids(nm, ver)),
            "depsdev_side_only": {"missed": left_only["missed_findings"],
                                  "phantom": left_only["phantom_findings"]},
            "resolution_side_only": {"missed": right_only["missed_findings"],
                                     "phantom": right_only["phantom_findings"]}}


def pick_two_sided_cause(left, right, servers, candidates):
    """A cause carrying findings on BOTH sides, which is what the gate needs.

    Taking the largest cause instead made the gate data-dependent: a cause
    present on only one side makes a one-sided and a two-sided suppression
    coincide ON CORRECT CODE, so the gate would abort a healthy run. Note that
    two-sided means present in both finding sets, not present in both the
    missed and phantom breakdowns: a package can appear on both sides, cancel
    where it agrees, and still carry a missed finding where it does not.

    Returns None when no candidate is two-sided, and the caller records that
    the gate could not run rather than reporting it as passed.
    """
    for nm in sorted(candidates):
        on_left = on_right = False
        for srv in servers:
            if not on_left and any(n == nm for n, _ in findings(left[srv])):
                on_left = True
            if not on_right and any(n == nm for n, _ in findings(right[srv])):
                on_right = True
            if on_left and on_right:
                return nm
    return None


def gate_suppression_is_two_sided(left, right, servers, cause):
    """A one-sided reduction must change the answer.

    Amendment two. The earlier symmetry check compared primary["servers"]
    against flat["servers"], both the length of the same list object, so it was
    unconditionally true. This runs the same suppression on one side only and
    requires a different result. If suppression ever leaks to a single side,
    the two-sided and one-sided runs converge and this raises.
    """
    sup = frozenset([cause])
    two = compare(left, right, servers, suppress=sup)
    one = compare(left, right, servers, suppress=sup, suppress_left_only=True)
    require((two["missed_findings"], two["phantom_findings"])
            != (one["missed_findings"], one["phantom_findings"]),
            "symmetry probe: suppressing %r on both sides and on the deps.dev "
            "side alone gave the same result, so suppression is not reaching "
            "both sides" % cause)
    return {"cause_used": cause,
            "two_sided": {"missed": two["missed_findings"],
                          "phantom": two["phantom_findings"]},
            "left_side_only": {"missed": one["missed_findings"],
                               "phantom": one["phantom_findings"]}}


def gate_cutoff_had_an_effect(matched, october):
    """Amendment one. The two arms differ only in cutoff.

    A per-node publish-time check is impossible: the packument cache was
    temporary and is gone. This is the falsifiable replacement. A later cutoff
    admits a superset of candidates, so a name's October version should be the
    same or newer. The older count is not required to be zero because a
    dist-tag that moved backward and the deprecation preference each produce one
    legitimately.
    """
    shared = sorted(set(matched) & set(october))
    diff_servers = 0
    newer = older = same = 0
    backward = []
    for s in shared:
        m = dict(matched[s])
        o = dict(october[s])
        if set(matched[s]) != set(october[s]):
            diff_servers += 1
        for nm in set(m) & set(o):
            if m[nm] == o[nm]:
                same += 1
                continue
            try:
                if sv.gt(o[nm], m[nm], loose=True):
                    newer += 1
                else:
                    older += 1
                    backward.append("%s %s -> %s" % (nm, m[nm], o[nm]))
            except Exception:
                older += 1
                backward.append("%s %s -> %s (unparseable)" % (nm, m[nm], o[nm]))
    require(diff_servers > 0,
            "cutoff probe: the matched and October arms are identical on every "
            "server, so LIVE_CUTOFF had no effect")
    require(newer > older,
            "cutoff probe: October is older than matched on %d names and newer "
            "on %d, so the cutoff is ignored or inverted" % (older, newer))
    # Magnitude, not only direction. The reviewer's point: newer > older passes
    # at 1 against 0, so a cutoff applied to a small minority of names, for
    # instance one that fell back to live resolution whenever a packument fetch
    # failed, would pass while being substantially un-aligned. The two arms are
    # forty days apart over a corpus of about 21,000 nodes, so a cutoff that was
    # applied throughout must move hundreds of names. FLOOR is a loose bound on
    # that reasoning, not a threshold fitted to the observed count.
    FLOOR = FORWARD_FLOOR
    require(newer >= FLOOR,
            "cutoff probe: only %d names moved forward between the two arms, "
            "below the floor of %d, so the cutoff may have been applied to a "
            "minority of names" % (newer, FLOOR))
    return {"shared_servers": len(shared), "servers_differing": diff_servers,
            "names_october_newer": newer, "names_october_older": older,
            "names_identical": same, "forward_floor": FLOOR,
            "backward_cases": sorted(backward)[:10],
            "backward_note": "a dist-tag that moved backward and the "
                             "deprecation preference each produce one "
                             "legitimately; they are listed rather than "
                             "required to be absent"}


def flag_sensitivity(left, right, servers):
    """Absolute finding totals under each semver flag.

    Amendment two. Gate 1 reproduces its figures byte-identically with
    include_prerelease off and with loose off, so it constrains neither flag.
    multer@1.4.5-lts.2 sits inside eleven advisories with the flag on and zero
    with it off, but appears at the same version on both sides of both trees
    that contain it, so it cancels in every set difference. These are absolute
    totals, where the flag does show, so a reader can see its size.
    """
    out = {}
    for label, (pre, loose) in {"as_run_prerelease_on_loose_on": (True, True),
                                "prerelease_off": (False, True),
                                "loose_off": (True, False)}.items():
        tl = tr = 0
        for srv in servers:
            tl += len({(n, x) for n, v in left[srv]
                       for x in vids(n, v, pre=pre, loose=loose)})
            tr += len({(n, x) for n, v in right[srv]
                       for x in vids(n, v, pre=pre, loose=loose)})
        out[label] = {"findings_depsdev_side": tl,
                      "findings_resolution_side": tr}
    return out


def main():
    dd_raw = json.load(open(DEPSDEV_PAIRS))
    matched_raw = json.load(open(MATCHED))
    october_raw = json.load(open(OCTOBER))
    dd = depsdev_pairs(dd_raw)
    matched = arm_pairs(matched_raw)
    october = arm_pairs(october_raw)
    matched_roots = {k: v.get("root_version") for k, v in matched_raw.items()
                     if isinstance(v, dict)}

    # Amendment two: every input is accounted for, not just the comparable set.
    def drops(raw):
        skipped = sorted(k for k, v in raw.items()
                         if isinstance(v, dict) and "skip" in v)
        trunc = sorted(k for k, v in raw.items()
                       if isinstance(v, dict) and v.get("truncated"))
        return {"records": len(raw), "skipped": skipped,
                "cap_truncated": trunc}
    accounting = {
        "depsdev_pairs": {"records": len(dd_raw),
                          "fetch_not_ok": sorted(k for k, v in dd_raw.items()
                                                 if not v.get("ok")),
                          "usable": len(dd)},
        "matched_walk": dict(drops(matched_raw), usable=len(matched)),
        "october_walk": dict(drops(october_raw), usable=len(october)),
    }

    gate = {}
    gate["orientation_probe"] = gate_orientation()
    gate["harness_reproduction"] = gate_harness_reproduction()
    gate["prerelease_probe_advisories_matched"] = gate_prerelease_probe()
    gate["double_count_probe"] = gate_double_count_probe()
    gate["cutoff_probe"] = gate_cutoff_had_an_effect(matched, october)

    # Comparable set, with every exclusion named.
    absent_from_depsdev = sorted(set(matched) - set(dd))
    absent_from_matched = sorted(set(dd) - set(matched))
    fetch_roots = {t["server"]: t.get("root_version")
                   for t in json.load(open(FETCH_ROOTS))}
    root_mismatch, root_unchecked = [], []
    for srv in sorted(set(dd) & set(matched)):
        rv = fetch_roots.get(srv)
        mv = matched_roots.get(srv)
        if not rv or not mv:
            root_unchecked.append(srv)
        elif rv != mv:
            root_mismatch.append({"server": srv, "depsdev_queried": rv,
                                  "matched_walk": mv})
    bad = {m["server"] for m in root_mismatch}
    servers = sorted((set(dd) & set(matched)) - bad)
    require(len(servers) > 0, "comparable set is empty")
    # The rule is now enforced rather than recorded. A server whose two sides
    # are trees of different roots would otherwise sit in the denominator with
    # every downstream disagreement attributed to resolver divergence.
    require(not root_unchecked,
            "root-version rule could not be evaluated for %d servers (%s), so "
            "the comparable set is not the population the protocol defines"
            % (len(root_unchecked), ", ".join(root_unchecked[:5])))
    require(not root_mismatch,
            "root-version mismatch on %d servers: %r"
            % (len(root_mismatch), root_mismatch[:5]))

    primary = compare(dd, matched, servers)

    # Both sides, recomputed here from the named arms with the default finding
    # function, and required to match what compare reported. This is the check
    # protocol gate 4 asked for and the earlier replacement did not provide. It
    # closes two holes the second review demonstrated on real data: binding the
    # arms to compare in the wrong order, which inverted missed and phantom
    # while the orientation probe stayed green because it builds its own dicts;
    # and giving one side a different semver configuration inside compare,
    # which moved missed findings by a factor of two and a half with every gate
    # passing.
    ind_l = sum(len(findings(dd[srv])) for srv in servers)
    ind_r = sum(len(findings(matched[srv])) for srv in servers)
    require(primary["total_findings_depsdev_side"] == ind_l,
            "side-binding check: compare reported %d findings on the deps.dev "
            "side, an independent pass over the deps.dev arm gives %d"
            % (primary["total_findings_depsdev_side"], ind_l))
    require(primary["total_findings_resolution_side"] == ind_r,
            "side-binding check: compare reported %d findings on the "
            "resolution side, an independent pass over the matched arm gives %d"
            % (primary["total_findings_resolution_side"], ind_r))

    # Amendment two: the flattened arm is not identified. Every tie-break
    # combination is reported and no point estimate is taken from it.
    flat_arms = {k: compare(dd, matched, servers, flat=v)
                 for k, v in TIE_BREAKS.items()}
    flat_rates = sorted(a["verdict_differs_pct"] for a in flat_arms.values())
    flat_phantom = sorted(a["phantom_findings"] for a in flat_arms.values())

    # The October arm runs on the same exclusion rule as the primary, not a
    # looser one: a root-version mismatch disqualifies a server from both.
    oct_servers = sorted((set(dd) & set(october)) - bad)
    secondary = compare(dd, october, oct_servers)

    # Leave-one-out over every package carrying a difference, drawn from the
    # untruncated breakdowns. Single-name suppression only: the pair state
    # carries node sets, not edges, so downstream membership is not derivable.
    causes = collections.Counter()
    for d in (primary["missed_by_package"], primary["phantom_by_package"]):
        for k, v in d.items():
            causes[k] += v
    loo = {}
    for nm in sorted(causes, key=lambda k: (-causes[k], k)):
        r = compare(dd, matched, servers, suppress=frozenset([nm]))
        loo[nm] = {"verdict_differs": r["verdict_differs"],
                   "verdict_differs_pct": r["verdict_differs_pct"],
                   "missed_findings": r["missed_findings"],
                   "phantom_findings": r["phantom_findings"]}
    if causes:
        r = compare(dd, matched, servers, suppress=frozenset(causes))
        loo["__all_causes__"] = {
            "suppressed": sorted(causes),
            "verdict_differs": r["verdict_differs"],
            "note": "arithmetic, not evidence: suppressing every cause must "
                    "drive the difference to zero by construction. Kept as a "
                    "consistency check.",
            "missed_findings": r["missed_findings"],
            "phantom_findings": r["phantom_findings"]}
        cause = pick_two_sided_cause(dd, matched, servers, causes)
        if cause is None:
            gate["symmetry_probe"] = {
                "ran": False,
                "reason": "no cause carries findings on both sides, so a "
                          "one-sided and a two-sided suppression coincide on "
                          "correct code and the gate cannot distinguish them"}
        else:
            gate["symmetry_probe"] = dict(
                gate_suppression_is_two_sided(dd, matched, servers, cause),
                ran=True)

    out = {
        "preregistration": "PREREGISTRATION-8.md",
        "supersedes_without_reproducing": SUPERSEDED,
        "left_side": "deps.dev graphs from data/depsdev_pairs.json, fetched "
                     "2026-09-07/08, pair-keyed, NOT re-fetched",
        "right_side_primary": "data/nested_gap_state_depsdev_matched.json. Its "
                              "cutoff is not recorded in the state file; "
                              "data/depsdev_recompute.json ships it as "
                              + MATCHED_CUTOFF + " bound to a "
                              "matched_state_sha256 that matches this file. "
                              "Nothing re-derives it from the data.",
        "right_side_secondary": "data/nested_gap_state.json, resolved about a "
                                "month later",
        "direction_of_the_comparison":
            "the matched walk includes optional edges without evaluating "
            "os/cpu constraints and auto-installs non-optional peers, so the "
            "resolution side is close to a superset of the deps.dev side by "
            "construction. Read the primary as a one-directional missed rate, "
            "not a symmetric verdict-difference rate.",
        "advisory_basis": json.load(open(ADV_META)),
        "input_accounting": accounting,
        "exclusions": {
            "absent_from_depsdev": absent_from_depsdev,
            "absent_from_the_matched_walk": absent_from_matched,
            "root_version_mismatch": root_mismatch,
            "root_version_unchecked_one_side_missing": root_unchecked,
        },
        "primary_pair_keyed": primary,
        "secondary_flattened_not_identified": {
            "arms": flat_arms,
            "verdict_differs_pct_span_over_these_four": [flat_rates[0],
                                                          flat_rates[-1]],
            "phantom_findings_span_over_these_four": [flat_phantom[0],
                                                      flat_phantom[-1]],
            "note": "no point estimate is taken from this arm, and the span is "
                    "NOT a bound on the statistic. First-wins and last-wins are "
                    "two endpoint rules, and 62 of the 819 duplicated groups "
                    "hold three or four versions, so there are copies neither "
                    "rule can select. Running six flattening rules per side "
                    "widens the span at both ends. Treat these as four samples.",
        },
        "secondary_october_arm": secondary,
        "leave_one_out_single_name_only": loo,
        "flag_sensitivity_absolute_totals": flag_sensitivity(dd, matched, servers),
        "gate": gate,
        "gate_description":
            "Harness reproduction carries the advisory join. The side-binding "
            "check carries which arm is which and that both go through the "
            "same finding function. The orientation probe carries the "
            "direction of missed against phantom, on every paired field. The "
            "root-version requires carry the population. The double-count "
            "probe's reachable power is a membership test on the deduplicated "
            "join; it catches removal of the de-duplication and nothing "
            "subtler. The cutoff check constrains direction and a loose "
            "forward floor, and cannot establish that the cutoff was applied "
            "at all, because that needs per-node publish times and the "
            "packument cache was temporary. The flattening path has no gate.",
        "range_sanity": range_sanity(),
        "what_this_cannot_settle":
            "the deps.dev side is a September snapshot and is not re-fetched, "
            "so this measures the gap between that published graph and a "
            "corrected resolution at the crawl date, not deps.dev's accuracy "
            "today",
        "provenance": {
            "python": sys.version.split()[0],
            "assertions_enabled": __debug__,
            "require_calls_made": len(CHECKS),
            "distinct_checks": len(set(
                c.split(":")[0] for c in CHECKS)),
            "check_count_note": "require_calls_made counts every call, and the "
                                "two breakdown-sum checks live inside compare, "
                                "which runs once per arm and once per "
                                "leave-one-out row, so the total moves with "
                                "the data. distinct_checks is the coverage "
                                "number.",
            "unparseable_version_pairs_seen": len(BAD_VERSIONS),
            "code_sha256": sha(os.path.abspath(__file__)),
            "depsdev_pairs_sha256": sha(DEPSDEV_PAIRS),
            "matched_state_sha256": sha(MATCHED),
            "october_state_sha256": sha(OCTOBER),
            "advisories_sha256": sha(ADVISORIES),
            "nested_published_sha256": sha(NESTED_PUBLISHED),
        },
    }
    json.dump(out, open(OUT, "w"), indent=1)
    print("PRIMARY, pair-keyed, matched date")
    print(json.dumps(primary, indent=1))
    print("\nFLATTENED, not identified: verdict differs %s%% to %s%%, "
          "phantom findings %s to %s"
          % (flat_rates[0], flat_rates[-1], flat_phantom[0], flat_phantom[-1]))
    for k, v in flat_arms.items():
        print("  %-32s %4.1f%%  missed %3d  phantom %3d"
              % (k, v["verdict_differs_pct"], v["missed_findings"],
                 v["phantom_findings"]))
    print("\nOCTOBER arm: %s of %s = %s%%, missed %s, phantom %s"
          % (secondary["verdict_differs"], secondary["servers"],
             secondary["verdict_differs_pct"], secondary["missed_findings"],
             secondary["phantom_findings"]))
    print("\nLEAVE ONE OUT (single name)")
    for k, v in loo.items():
        if k != "__all_causes__":
            print("  suppress %-34s differs %d  missed %2d  phantom %2d"
                  % (k, v["verdict_differs"], v["missed_findings"],
                     v["phantom_findings"]))
    print("\nFLAG SENSITIVITY (absolute totals)")
    for k, v in out["flag_sensitivity_absolute_totals"].items():
        print("  %-32s depsdev %4d  resolution %4d"
              % (k, v["findings_depsdev_side"], v["findings_resolution_side"]))
    print("\ngate checks run:", len(CHECKS), " assertions enabled:", __debug__)
    for k, v in gate.items():
        print("  %s: %s" % (k, v))
    print("\nunparseable (name, version) pairs seen:", len(BAD_VERSIONS))
    print("wrote", os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
