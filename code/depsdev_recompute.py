#!/usr/bin/env python3
"""Recompute the deps.dev divergence bound against the corrected resolver.

Pre-registered in PREREGISTRATION-7.md.

WHY THIS EXISTS
    The published bound (code/depsdev_delta.py) compares deps.dev's graph for
    each MCP server root against a resolved tree from
    data/resolved_trees_for_depsdev.json. That file is a third resolution
    vintage: 90 nodes for `graphweft` where the corrected resolver gives 92
    against the registry as of 2026-09-09 and 87 a month later. The bound rests
    on a resolver that has since been corrected.

WHAT IS HELD FIXED
    The left side. deps.dev's graphs are not re-fetched, so any change in the
    bound is attributable to the right-hand side alone.

THE THREE RIGHT-HAND SIDES
    aligned      the corrected resolver at the advisory snapshot instant,
                 2026-09-09T22:15:30Z, within two days of the deps.dev fetch.
                 This is the primary arm.
    october      the same walk a month later, as a sensitivity.
    historical   the input the published bound used, so the change is visible
                 rather than asserted. This arm MUST reproduce the published
                 figures or the run stops.

Run: python3 code/depsdev_recompute.py
"""
import collections
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Overridable so a test suite can point every input at a fixture
# directory, since the four input paths below are module constants.
DATA = os.environ.get("RECOMPUTE_DATA") or os.path.join(
    os.path.dirname(HERE), "data")
OUT = os.environ.get("RECOMPUTE_OUT", os.path.join(DATA, "depsdev_recompute.json"))

# the published figures this must reproduce on the historical arm, from
# PREREGISTRATION-7's gate. Not defaults to be relaxed.
PUBLISHED = {"comparable": 249, "identical": 154, "identical_pct": 61.8,
             "version_differs_pct": 38.2, "fewer_pct": 1.2, "instance_delta_pct": 0.2}


class GateFailed(RuntimeError):
    """A precondition did not hold. Raised, not asserted, so -O cannot remove it."""


def require(cond, msg):
    if not cond:
        raise GateFailed(msg)


CUTOFF = os.environ.get("MATCHED_CUTOFF", "2026-09-08T01:00:00Z")


def check_cutoff(arm, servers, cutoff):
    """Every selected version must predate the cutoff, or the arm is mislabelled.

    This replaces a root-version check that could not fail. It reads publish
    times from the warm packument cache, so it costs disk rather than network.
    """
    import datetime as dt
    sys.path.insert(0, HERE)
    import mcplib
    want = dt.datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    pairs = set()
    for n in servers:
        for k, v in arm[n]["resolved"].items():
            pairs.add((k, v))
        for k, vs in arm[n]["multi"].items():
            for v in vs:
                pairs.add((k, v))
    late = []
    seen = {}
    # Coverage, because the earlier version returned only its violations. A run
    # that compared 1,300 timestamps and one that compared none were
    # indistinguishable in the output: every packument failure became an empty
    # dict and every missing version was skipped, so an empty `late` meant
    # either "nothing was published late" or "nothing was looked at".
    checked = no_timestamp = lookup_failed = unparseable = 0
    for name, ver in sorted(pairs):
        if name not in seen:
            try:
                seen[name] = (mcplib.npm_packument(name) or {}).get("time") or {}
            except Exception:
                seen[name] = {}
                lookup_failed += 1
        ts = seen[name].get(ver)
        if not ts:
            no_timestamp += 1
            continue
        try:
            when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if when.tzinfo is None:
                # A naive timestamp parses cleanly and then raises TypeError on
                # the comparison below, which is outside this try. Count it as
                # unusable rather than letting it abort the gate.
                raise ValueError("naive timestamp")
        except (ValueError, TypeError):
            unparseable += 1
            continue
        # TypeError is caught alongside ValueError: a naive timestamp in a
        # packument makes the comparison below raise rather than the parse.
        checked += 1
        if when > want:
            late.append({"package": name, "version": ver, "published": ts})
    return late, {"pairs_seen": len(pairs), "pairs_compared": checked,
                  "no_timestamp_in_packument": no_timestamp,
                  "packument_lookup_failed": lookup_failed,
                  "timestamp_unparseable": unparseable}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def tree_from_state(path):
    """{server: {single-version names}, plus the names carried at several.

    The live arm is a list of (name, version) pairs and 827 packages across 170
    servers appear at MORE THAN ONE version. The first version of this function
    collapsed each name with setdefault, which picked whichever came first in
    the list and then scored it against deps.dev's single version, manufacturing
    disagreements out of list order. Amendment one withdrew the figure that
    produced. Multi-version names are now separated out rather than flattened,
    because deps.dev's graph cannot express them and scoring them either way
    would be a choice rather than a measurement.
    """
    out = {}
    malformed = 0
    for name, v in json.load(open(path)).items():
        if "skip" in v or v.get("truncated") or not v.get("installed"):
            continue
        seen = collections.defaultdict(set)
        for x in v["installed"]:
            n, sep, ver = x.rpartition("@@")
            if not sep or not n:
                malformed += 1
                continue
            seen[n].add(ver)
        single = {n: next(iter(vs)) for n, vs in seen.items() if len(vs) == 1}
        multi = {n: sorted(vs) for n, vs in seen.items() if len(vs) > 1}
        out[name] = {"resolved": single, "multi": multi,
                     "root_version": v.get("root_version")}
    if malformed:
        print("  tree_from_state: %d installed tokens had no @@ separator "
              "and were skipped" % malformed)
    return out


def tree_from_depsdev_file(path):
    """The historical input, which is already one version per name."""
    return {t["server"]: {"resolved": t["resolved"], "multi": {},
                          "root_version": t.get("root_version")}
            for t in json.load(open(path))}


def instance_totals(right, dd, servers):
    """Both sides counted the same way: every (name, version) pair against every
    deps.dev node.

    The first version of this compared the resolution's single-version names
    against deps.dev's full node set in one place and against a reduced node set
    in another, and reported +4.0% where the comparable pair is +8.1%. The 8.1%
    has a meaning the 4.0% did not: the corrected resolution carries several
    versions of 817 names, which deps.dev's one-version-per-name graph cannot
    express at all.
    """
    res = sum(len(r["resolved"]) + sum(len(v) for v in r["multi"].values())
              for r in (right[n] for n in servers))
    ddn = sum(len(dd[n]["nodes"]) for n in servers)
    return res, ddn, round(100.0 * (res - ddn) / max(ddn, 1), 1)


def compare(dd, right, servers, suppress=(), exclude=None):  # noqa: C901
    """Compare on the single-version subset. `suppress` drops named packages.

    A name the resolution carries at several versions is excluded from every
    class and counted in `multi_version_in_resolution`, per amendment one.
    """
    rows, agree = [], 0
    for name in servers:
        live = right[name]["resolved"]
        multi = right[name].get("multi") or {}
        # `exclude` overrides the arm's own multi set with one supplied by the
        # caller, so two arms can be scored on IDENTICAL node sets. Without it
        # each arm used its own: the historical input is already one version
        # per name, so its multi set is empty and nothing was removed from the
        # deps.dev side, while the matched arm removed 763 deps.dev nodes
        # across 170 servers. Removal can only help agreement, so the two arms'
        # rates were not comparable and the published pairing of 79.4% against
        # 62.1% scored the two sides against different left-hand node sets.
        drop = set(multi) if exclude is None else set(exclude.get(name) or ())
        ddn = {k: v for k, v in dd[name]["nodes"].items()
               if k not in suppress and k not in drop}
        live = {k: v for k, v in live.items()
                if k not in suppress and k not in drop}
        miss = [k for k in live if k not in ddn]
        extra = [k for k in ddn if k not in live]
        vdiff = [k for k in live if k in ddn and ddn[k] and live[k] != ddn[k]]
        if not miss and not extra and not vdiff:
            agree += 1
        rows.append({"server": name, "live_n": len(live), "depsdev_n": len(ddn),
                     "missing_in_depsdev": len(miss),
                     "extra_in_depsdev": len(extra),
                     "version_differs": len(vdiff),
                     "multi_version_in_resolution": len(multi)})
    n = len(rows)
    med = lambda f: sorted(f(r) for r in rows)[n // 2] if n else None
    pct = lambda f: round(100.0 * sum(1 for r in rows if f(r)) / n, 1) if n else None
    tl = sum(r["live_n"] for r in rows)
    td = sum(r["depsdev_n"] for r in rows)
    return {
        "comparable": n,
        "identical": agree,
        "identical_pct": round(100.0 * agree / n, 1) if n else None,
        "version_differs_pct": pct(lambda r: r["version_differs"] > 0),
        "fewer_pct": pct(lambda r: r["depsdev_n"] < r["live_n"]),
        "misses_pct": pct(lambda r: r["missing_in_depsdev"] > 0),
        "extra_pct": pct(lambda r: r["extra_in_depsdev"] > 0),
        "median_nodes_resolution": med(lambda r: r["live_n"]),
        "median_nodes_depsdev": med(lambda r: r["depsdev_n"]),
        "instances_resolution": tl,
        # the left side as the comparison sees it, after multi-version names are
        # dropped from BOTH sides, and as it actually is. The protocol promised
        # the left side was held fixed; dropping 763 deps.dev nodes broke that,
        # and a +4.0% delta sat beside the historical +0.2% as if comparable.
        "instances_depsdev_after_exclusions": td,
        "instances_depsdev_unmodified": sum(
            len(dd[n]["nodes"]) for n in servers),
        "instance_delta_pct_as_compared": round(100.0 * (tl - td) / max(td, 1), 1),
        # the comparable pair: every (name, version) pair on one side against
        # every deps.dev node on the other
        "instances_resolution_all_pairs": instance_totals(right, dd, servers)[0],
        "instance_delta_pct_comparable": instance_totals(right, dd, servers)[2],
        "multi_version_names_excluded": sum(
            r["multi_version_in_resolution"] for r in rows),
        "servers_with_a_multi_version_name": sum(
            1 for r in rows if r["multi_version_in_resolution"] > 0),
    }, rows


def main():
    dd = json.load(open(os.path.join(DATA, "depsdev_state.json")))
    arms = {
        "historical": tree_from_depsdev_file(
            os.path.join(DATA, "resolved_trees_for_depsdev.json")),
        "aligned": tree_from_state(os.path.join(DATA,
                                                "nested_gap_state_aligned.json")),
        "october": tree_from_state(os.path.join(DATA, "nested_gap_state.json")),
        # the corrected resolver re-run with LIVE_CUTOFF=2026-09-08T01:00:00Z,
        # which covers the deps.dev fetch window. This is the arm that isolates
        # the resolver, because its registry date matches the historical arm's.
        "matched": tree_from_state(os.path.join(
            DATA, "nested_gap_state_depsdev_matched.json")),
    }
    ok_dd = {n for n, v in dd.items() if v.get("ok")}

    # ---- the gate: the historical arm must reproduce what was published ----
    hist_servers = sorted(ok_dd & set(arms["historical"]))
    hist, _ = compare(dd, arms["historical"], hist_servers)
    hist = dict(hist, instance_delta_pct=hist["instance_delta_pct_as_compared"])
    for k, want in PUBLISHED.items():
        require(hist[k] == want,
                f"reproduction gate failed on {k}: published {want}, recomputed "
                f"{hist[k]}. The published bound is not being reproduced, so no "
                f"recomputation is reported.")

    # ---- the comparable set: same root version in both walks ----
    base = arms["historical"]
    comparable, version_mismatch, absent = [], [], []
    for n in sorted(ok_dd & set(base)):
        if n not in arms["aligned"]:
            absent.append(n)
        elif base[n]["root_version"] != arms["aligned"][n]["root_version"]:
            version_mismatch.append(n)
        else:
            comparable.append(n)
    # The root-version equality this used to assert is TAUTOLOGICAL:
    # nested_gap.run copies root_version verbatim out of
    # resolved_trees_for_depsdev.json, the same file the historical arm reads it
    # from, so the two sides cannot disagree by construction. Kept as a
    # structural sanity check and labelled, with a falsifiable check below.
    require(not version_mismatch,
            f"{len(version_mismatch)} servers differ in root version: "
            f"{version_mismatch[:5]}")

    # The real check the matched arm needs: nothing it selected may have been
    # published after the cutoff, or it is not a 2026-09-08 resolution.
    # `comparable` is built from the aligned arm, so a server it holds that the
    # matched arm lacks used to raise KeyError here.
    cut_servers = [n for n in comparable if n in arms["matched"]]
    late, cut_cover = check_cutoff(arms["matched"], cut_servers, CUTOFF)
    require(not late,
            f"{len(late)} selections in the matched arm were published after "
            f"the declared cutoff {CUTOFF}, so it is not a resolution as of "
            f"that instant: {late[:4]}")
    # A coverage floor, so an empty `late` cannot mean "nothing was looked at".
    # The arm carries over a thousand distinct (name, version) pairs; comparing
    # fewer than a quarter of them means the packument cache was cold or the
    # lookups failed, and the gate's verdict is then uninterpretable rather
    # than passed.
    require(cut_cover["pairs_compared"] * 4 >= cut_cover["pairs_seen"],
            "cutoff gate compared only %d of %d (name, version) pairs, so its "
            "verdict is not interpretable: %r"
            % (cut_cover["pairs_compared"], cut_cover["pairs_seen"], cut_cover))

    # The extra class and the dominant version disagreement are ONE event. The
    # corrected resolver picks get-intrinsic@1.3.0, which is npm's latest tag,
    # where the pre-correction resolver and deps.dev carry 1.3.1 -- and 1.3.1
    # declares async-function, async-generator-function and generator-function
    # while 1.3.0 declares none of them. Amendment one suppressed the three
    # downstream names, saw the headline unmoved and read that as the extras
    # being incidental. It was the symptom being removed with the cause left in:
    # suppressing the edge as well takes agreement from 30.2% to 79.4%.
    extra_counts = collections.Counter()
    for n in comparable:
        live = set(arms["matched"][n]["resolved"]) | set(arms["matched"][n]["multi"])
        for k in dd[n]["nodes"]:
            if k not in live:
                extra_counts[k] += 1
    ranked_extras = sorted(extra_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    TOP3 = tuple(k for k, _ in ranked_extras[:3])
    # CAUSE was the string literal "get-intrinsic" sitting under a comment
    # claiming it had been "found by asking which package's version
    # disagreement the extras depend on rather than by assuming". The comment
    # described work the code did not do, and nothing checked that the name
    # still mattered: had it stopped mattering, the suppressed figure would
    # have quietly collapsed to the unsuppressed one with no gate firing.
    #
    # Derived now. The cause is the most frequent version disagreement between
    # the two resolver arms, and the claim that it is the SAME event as the
    # extra class is checked rather than asserted: the two incidences must
    # match, because every server where the edge moves is a server where the
    # downstream names appear and no other.
    dis_counts = collections.Counter()
    for n in comparable:
        if n not in arms["matched"]:
            continue
        h = arms["historical"][n]["resolved"]
        m = arms["matched"][n]["resolved"]
        for k in set(h) & set(m):
            if h[k] != m[k]:
                dis_counts[k] += 1
    ranked_dis = sorted(dis_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    require(bool(ranked_dis), "no version disagreement between the two arms")
    CAUSE = (ranked_dis[0][0],)
    require(ranked_dis[0][1] == ranked_extras[0][1],
            "the cause and the extra class are not one event: %s disagrees on "
            "%d servers and %s is extra on %d, so suppressing the first cannot "
            "be read as removing the second"
            % (ranked_dis[0][0], ranked_dis[0][1],
               ranked_extras[0][0], ranked_extras[0][1]))
    require(CAUSE[0] not in TOP3,
            "the derived cause %r is itself one of the three downstream names, "
            "so cause_only and symptom_only are not distinct arms" % CAUSE[0])

    # ---- the primary comparison: same date, same roots, resolver only ----
    # Any difference here is the resolver correction and nothing else, because
    # both sides resolve against the registry as of the same instant.
    hist_t, match_t = arms["historical"], arms["matched"]
    both = [n for n in comparable if n in match_t]
    same_set = same_ver = node_diff = ver_diff = 0
    ver_examples = []
    for n in both:
        h = hist_t[n]["resolved"]
        m = dict(match_t[n]["resolved"])
        m_multi = match_t[n]["multi"]
        names_h, names_m = set(h), set(m) | set(m_multi)
        if names_h == names_m:
            same_set += 1
        else:
            node_diff += 1
        # sorted, because iterating a set made the examples move with the
        # interpreter's hash seed. nested_gap.ranked() is the same fix.
        dis = sorted(k for k in set(h) & set(m) if h[k] != m[k])
        if dis:
            ver_diff += 1
            for k in dis[:2]:
                if len(ver_examples) < 8:
                    ver_examples.append({"server": n, "package": k,
                                         "pre_correction": h[k], "corrected": m[k]})
        else:
            same_ver += 1
    resolver_only = {
        "servers": len(both),
        "identical_package_set": same_set,
        "identical_package_set_pct": round(100.0 * same_set / len(both), 1),
        "differing_package_set": node_diff,
        "no_version_disagreement": same_ver,
        "no_version_disagreement_pct": round(100.0 * same_ver / len(both), 1),
        "with_a_version_disagreement": ver_diff,
        "examples": ver_examples,
        "note": "both sides resolve against the registry as of 2026-09-08, so "
                "registry drift is controlled. It does NOT isolate the resolver "
                "correction: the historical arm is mcplib.npm_walk, which "
                "defaults to include_peer=False and is name-keyed, and the "
                "matched arm is nested_gap.pair_walk, which includes "
                "non-optional peers, is pair-keyed and applies a BFS reuse "
                "rule. Four rules differ at once and this figure is their sum.",
    }

    results, detail = {}, {}
    for arm in ("historical", "aligned", "october", "matched"):
        servers = [n for n in comparable if n in arms[arm]]
        results[arm], detail[arm] = compare(dd, arms[arm], servers)
        for label, sup in (("symptom_only", TOP3),
                           ("cause_only", CAUSE),
                           ("cause_and_symptom", tuple(CAUSE) + TOP3)):
            s, _ = compare(dd, arms[arm], servers, suppress=sup)
            results[arm].setdefault("leave_one_out", {})[label] = {
                "suppressed": list(sup), "identical_pct": s["identical_pct"],
                "version_differs_pct": s["version_differs_pct"],
                "extra_pct": s["extra_pct"]}

    # ---- the comparable pair, which the published figures were not ----
    # One exclusion set, derived from the matched arm's own multi-version names
    # per server, applied to BOTH sides of BOTH arms. This is the only pairing
    # that supports a statement about which resolver agrees with deps.dev
    # better. A blunter set, every affected name removed from every server, was
    # also tried and is NOT used: it strips names from servers where they are
    # single-version, over-removing disagreement from the historical arm.
    common_excl = {n: set(arms["matched"][n]["multi"] or {})
                   for n in comparable if n in arms["matched"]}
    pair_servers = sorted(common_excl)
    SUP = tuple(CAUSE) + TOP3
    pair = {}
    for label, arm, sup in (("historical_unsuppressed", "historical", ()),
                            ("historical_suppressed", "historical", SUP),
                            ("matched_unsuppressed", "matched", ()),
                            ("matched_suppressed", "matched", SUP)):
        r, _ = compare(dd, arms[arm], pair_servers, suppress=sup,
                       exclude=common_excl)
        pair[label] = {"identical": r["identical"],
                       "identical_pct": r["identical_pct"],
                       "version_differs_pct": r["version_differs_pct"],
                       "extra_pct": r["extra_pct"],
                       "misses_pct": r["misses_pct"],
                       # the size of the left side as scored. Equal across all
                       # four rows is what "comparable" means here, and it is
                       # the only field that shows the common exclusion was
                       # applied: the agreement count can be identical with
                       # and without it.
                       "depsdev_instances_as_scored":
                           r["instances_depsdev_after_exclusions"]}
    # Both arms must now be scored on the same servers and the same exclusion,
    # or the pair is no better than the one it replaces.
    require(len({v["identical"] is not None for v in pair.values()}) == 1,
            "comparable pair did not produce a figure for every arm")
    require(all(r["identical"] <= len(pair_servers) for r in pair.values()),
            "comparable pair reports more identical servers than servers")
    # Equal BETWEEN THE ARMS at the same suppression level. Suppression itself
    # removes names from the left side too, so the suppressed rows are
    # legitimately smaller than the unsuppressed ones; what must not differ is
    # the two arms at one level, which is exactly the defect being repaired.
    # Split on the label's own suffix rather than endswith: "unsuppressed"
    # ends with "suppressed", so an endswith test puts every row in one group
    # and the check passes for the wrong reason.
    for level in ("unsuppressed", "suppressed"):
        sizes = {lbl: pair[lbl]["depsdev_instances_as_scored"]
                 for lbl in pair if lbl.rsplit("_", 1)[-1] == level}
        require(len(set(sizes.values())) == 1,
                "comparable pair scored the two arms against left sides of "
                "different sizes at the %s level, %r, so it is no better than "
                "the pairing it replaces" % (level, sizes))

    out = {
        "preregistration": "PREREGISTRATION-7.md",
        "comparable_pair_one_exclusion_both_arms": dict(
            pair,
            servers=len(pair_servers),
            exclusion="the matched arm's per-server multi-version names, "
                      "removed from both sides of both arms",
            supersedes="the pairing of the matched arm's suppressed rate "
                       "against the historical arm's 62.1%, which scored the "
                       "two against different left-hand node sets because the "
                       "historical input carries no multi-version names and so "
                       "lost nothing from the deps.dev side",
            note="this is the pair that supports a direction. The arm-level "
                 "figures under `arms` keep each arm's own exclusion and are "
                 "not comparable across arms."),
        "left_side": "deps.dev graphs, fetched 2026-09-07/08, NOT re-fetched",
        "comparable_servers": len(comparable),
        "excluded_absent_from_gap_walk": absent,
        "excluded_root_version_mismatch": version_mismatch,
        "published_bound_reproduced": hist,
        "matched_vs_historical_all_four_rules": resolver_only,
        "extra_class_concentration": sorted(extra_counts.items(),
                                            key=lambda kv: (-kv[1], kv[0])),
        "arms": results,
        "what_this_cannot_settle": "the left side is a September snapshot and is "
                                   "not re-fetched, so this measures the gap "
                                   "between that published graph and a corrected "
                                   "resolution, not deps.dev's accuracy today",
        "provenance": {
            "python": sys.version.split()[0],
            "code_sha256": sha(os.path.abspath(__file__)),
            "depsdev_state_sha256": sha(os.path.join(DATA, "depsdev_state.json")),
            "historical_trees_sha256": sha(os.path.join(
                DATA, "resolved_trees_for_depsdev.json")),
            "aligned_state_sha256": sha(os.path.join(
                DATA, "nested_gap_state_aligned.json")),
            # without these the matched arm's identity is unverifiable: pointing
            # it at the aligned file would change nothing a reader could detect
            "matched_state_sha256": sha(os.path.join(
                DATA, "nested_gap_state_depsdev_matched.json")),
            "october_state_sha256": sha(os.path.join(
                DATA, "nested_gap_state.json")),
            "matched_cutoff": CUTOFF,
            "cutoff_gate_coverage": cut_cover,
            "assertions_enabled": __debug__,
        },
    }
    # The five state hashes exist so that one arm silently pointed at another
    # arm's file would be visible. Nothing checked they differ, which is the
    # thing they were added to prevent: the matched arm reading the aligned
    # state would reproduce the aligned figures under the matched label.
    shas = {k: v for k, v in out["provenance"].items()
            if k.endswith("_sha256") and k != "code_sha256"}
    require(len(set(shas.values())) == len(shas),
            "two input files hash identically, so at least one arm is reading "
            "another arm's state: %r" % shas)
    json.dump(out, open(OUT, "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("provenance", "excluded_absent_from_gap_walk")},
                     indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
