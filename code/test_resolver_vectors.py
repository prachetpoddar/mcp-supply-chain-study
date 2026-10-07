#!/usr/bin/env python3
"""
Check mcplib.npm_resolve against npm's own answers.

THE ORACLE IS npm, NOT ITS DOCUMENTATION
    Every expected value below was produced by running npm-pick-manifest 11.0.3,
    as bundled in npm 11, against the packument beside it on 2026-09-11. None of
    them were derived by reading the README, which still documents 8.0.2: the
    dist-tag fast path gained engineOk, !deprecated, !restricted and !staged in
    10.0.0 and the prose never followed. npm 8 and 9 return a deprecated latest
    that satisfies the range; npm 10 and 11 do not.

    Two of these were also confirmed against a real `npm install` on npm 10.9.7:
    array-includes@3.1.9 declares get-intrinsic ^1.3.0 and npm installs 1.3.0
    although 1.3.1 exists, and koa@3.2.1 declares koa-compose ^4.1.0 and npm
    installs 4.1.0 although 4.2.0 exists and is deprecated.

    Run:  python3 code/test_resolver_vectors.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib


def P(latest, versions, extra_tags=None):
    tags = {"latest": latest}
    tags.update(extra_tags or {})
    out = {}
    for v, o in versions.items():
        m = {"name": "fixture", "version": v,
             "dist": {"tarball": "https://example.invalid/f-%s.tgz" % v}}
        m.update(o)
        out[v] = m
    return {"name": "fixture", "dist-tags": tags, "versions": out}


D = {"deprecated": "deprecated by the maintainer"}
E = lambda r: {"engines": {"node": r}}

# (id, packument, range, node_version_for_engines, npm's answer, why it is here)
VECTORS = [
    ("tag_satisfies_prefers_latest",
     P("1.3.0", {"1.2.0": {}, "1.3.0": {}, "1.3.1": {}}), "^1.3.0", None, "1.3.0",
     "the rule this resolver lacked: latest satisfies, so npm takes it over a higher match"),
    ("tag_satisfies_star",
     P("22.20.2", {"22.20.2": {}, "26.5.1": {}}), "*", None, "22.20.2",
     "selector * with a higher untagged version present"),
    ("tag_satisfies_gte",
     P("22.20.2", {"18.19.130": {}, "22.20.2": {}, "26.5.1": {}}), ">=13.7.0", None, "22.20.2",
     "open lower bound, latest satisfies"),
    ("tag_outside_range_falls_through",
     P("2.0.0", {"1.0.0": {}, "1.5.0": {}, "2.0.0": {}}), "^1", None, "1.5.0",
     "latest does not satisfy, so the sort decides"),
    ("higher_is_deprecated_latest_clean",
     P("4.1.0", {"4.1.0": {}, "4.2.0": dict(D)}), "^4.1.0", None, "4.1.0",
     "koa-compose shape: the higher version is deprecated and latest is clean"),
    ("latest_deprecated_clean_alternative",
     P("2.0.0", {"1.0.0": {}, "1.5.0": {}, "2.0.0": dict(D)}), "^1 || ^2", None, "1.5.0",
     "fast path skipped for deprecation, and the SORT must prefer non-deprecated"),
    ("all_deprecated",
     P("2.0.0", {"1.0.0": dict(D), "2.0.0": dict(D)}), "*", None, "2.0.0",
     "deprecation is a preference, not an exclusion"),
    ("latest_engines_exclude_host",
     P("2.0.0", {"1.0.0": E(">=14"), "2.0.0": E(">=22")}), "*", "18.20.4", "1.0.0",
     "engines exclude the host, so the fast path is skipped and the sort prefers engine-ok"),
    ("latest_engines_admit_host",
     P("2.0.0", {"1.0.0": E(">=14"), "2.0.0": E(">=22")}), "*", "22.11.0", "2.0.0",
     "same packument, a host that satisfies: resolution is host-dependent"),
    ("exact_version_pin",
     P("2.0.0", {"1.0.0": {}, "2.0.0": {}}), "1.0.0", None, "1.0.0",
     "an exact selector ignores the tag"),
    ("named_tag_selector",
     P("2.0.0", {"1.0.0": {}, "2.0.0": {}, "3.0.0-beta.1": {}}, {"next": "3.0.0-beta.1"}),
     "next", None, "3.0.0-beta.1", "a non-default tag as the selector"),
    ("prerelease_excluded_from_range",
     P("1.0.0", {"1.0.0": {}, "1.1.0-beta.1": {}}), "^1.0.0", None, "1.0.0",
     "prereleases do not satisfy a caret range"),
    ("tag_points_below_everything",
     P("1.0.0", {"1.0.0": {}, "1.9.9": {}, "1.10.0": {}}), "^1.0.0", None, "1.0.0",
     "the sharpest case: latest is the LOWEST version and still wins"),
]


def run(prefer):
    orig = mcplib.npm_packument
    results = []
    try:
        for vid, pack, rng, nodev, want, why in VECTORS:
            mcplib.npm_packument = lambda _n, _p=pack: _p
            try:
                got, _ = mcplib.npm_resolve("fixture", rng,
                                            prefer_dist_tag=prefer, node_version=nodev)
            except Exception as e:
                got = "raised %s" % type(e).__name__
            results.append((vid, want, got, got == want, why))
    finally:
        mcplib.npm_packument = orig
    return results


def main():
    print(__doc__.strip().split("\n\n")[0])
    print("\noracle: npm-pick-manifest 11.0.3 (bundled in npm 11), measured 2026-09-11\n")
    summary = {}
    for prefer in (False, True):
        res = run(prefer)
        ok = sum(1 for r in res if r[3])
        summary[prefer] = (ok, len(res), res)
        label = "PREFER_DIST_TAG on " if prefer else "PREFER_DIST_TAG off"
        print(f"=== {label} : {ok} of {len(res)} vectors match npm ===")
        for vid, want, got, good, why in res:
            if not good:
                print(f"  MISMATCH {vid:<36} npm {want:<14} ours {got}")
                print(f"           {why}")
        if ok == len(res):
            print("  all vectors match")
        print()
    off_ok, n, _ = summary[False]
    on_ok, _, on_res = summary[True]
    print(f"off: {off_ok}/{n}   on: {on_ok}/{n}")
    if on_ok != n:
        print("\nFAIL: the resolver does not match npm even with the preference on.")
        sys.exit(1)
    if off_ok == n:
        print("\nFAIL: the flag changes nothing, so one of the two paths is not being taken.")
        sys.exit(1)
    print("\nPASS: matches npm with the preference on, and the off path is still the")
    print("      pre-change behaviour, so the published corpus reproduces unchanged.")


if __name__ == "__main__":
    main()
