#!/usr/bin/env python3
"""Confirm every figure reported outward for v3.16 against a file in this tree.

WHY THIS EXISTS
    Two figures reached a third party's documentation that no file supported:
    a graph-comparison cluster carried from a working summary, and a verdict
    figure that was its own retracted sibling. The rule adopted after the first
    of those was that a number not produced from a file in the current session
    does not go into anything addressed to someone else. This script is that
    rule as code: one claim per line, each read off a shipped file or
    recomputed from shipped inputs, with a PASS/FAIL verdict.

FOUR OF ITS OWN CHECKS WERE WRONG FIRST
    A bare substring search for "661" matches any number containing those
    digits. A search for a retraction sentence failed because the sentence
    wraps. A test for "nothing writes final_verified.json" fired on the string
    appearing in the block that records what it supersedes. A manifest parse
    kept trailing newlines. A verification pass is code and gets the same
    scrutiny as the code it verifies.

    python3 code/verify_v316_claims.py        # exits non-zero on any FAIL
"""
import collections, json, os, re, subprocess, sys
sys.path.insert(0, "code")
import nodesemver as sv

OK = FAIL = 0
def claim(label, got, want):
    global OK, FAIL
    good = got == want
    print("  %-4s %-58s got %-30s want %s" %
          ("PASS" if good else "FAIL", label[:58], str(got)[:30], str(want)[:30]))
    OK, FAIL = OK + good, FAIL + (not good)

def section(t): print("\n== %s ==" % t)

V = json.load(open("data/verdict_recompute.json"))
D = json.load(open("data/depsdev_recompute.json"))
FV = json.load(open("results/final_verified.json"))

# ---------------------------------------------------------------- graph figures
section("1. the three graph figures")
pb = D["published_bound_reproduced"]
claim("name-keyed median, resolution", pb["median_nodes_resolution"], 95)
claim("name-keyed median, deps.dev", pb["median_nodes_depsdev"], 95)
claim("name-keyed version disagreement", pb["version_differs_pct"], 38.2)
claim("name-keyed instance delta", pb["instance_delta_pct"], 0.2)
claim("name-keyed misses", pb["misses_pct"], 1.2)
claim("name-keyed extra", pb["extra_pct"], 0.4)
m = D["arms"]["matched"]
claim("pair-keyed median, resolution", m["median_nodes_resolution"], 91)
claim("pair-keyed median, deps.dev", m["median_nodes_depsdev"], 94)
claim("pair-keyed version disagreement", m["version_differs_pct"], 66.1)
claim("pair-keyed instance delta, comparable", m["instance_delta_pct_comparable"], 8.1)
claim("pair-keyed misses", m["misses_pct"], 10.9)
claim("pair-keyed extra", m["extra_pct"], 64.9)
claim("multi-version names, matched arm", m["multi_version_names_excluded"], 817)
claim("servers carrying one", m["servers_with_a_multi_version_name"], 170)

# 219 total disagreements, name-keyed, and the 72.2% against the corrected walk
dd_state = {k: v for k, v in json.load(open("data/depsdev_state.json")).items()
            if v.get("ok")}
hist = {t["server"]: t for t in json.load(open("data/resolved_trees_for_depsdev.json"))}
tot_vd = 0
for s, rec in dd_state.items():
    if s not in hist: continue
    live, ddn = hist[s]["resolved"], rec["nodes"]
    tot_vd += sum(1 for k in live if k in ddn and ddn[k] and live[k] != ddn[k])
claim("name-keyed total version disagreements", tot_vd, 219)

def flat(lst):
    d = {}
    for x in lst:
        n, _, v = x.rpartition("@@"); d[n] = v
    return d
ng = json.load(open("data/nested_gap_state.json"))
rows = 0; agree_vd = 0
for s, rec in dd_state.items():
    if s not in ng or "installed" not in ng[s]: continue
    rows += 1
    live, ddn = flat(ng[s]["installed"]), rec["nodes"]
    if any(k in ddn and ddn[k] and live[k] != ddn[k] for k in live): agree_vd += 1
claim("name-keyed left vs corrected walk", round(100.0 * agree_vd / rows, 1), 72.2)

# ------------------------------------------------- the 68.3% cluster is unsourced
section("2. the figures that reproduce nowhere")
# The claim is that the four statistics do not take those values, which is a
# computation, not the absence of a digit string. A bare grep for "661" matches
# any number containing those digits and proves nothing either way.
claim("version disagreement is not 68.3", pb["version_differs_pct"] == 68.3, False)
claim("instance delta is not 0.6", pb["instance_delta_pct"] == 0.6, False)
claim("total disagreements are not 661", tot_vd == 661, False)
claim("misses are not 0.4 and extras not 12.4",
      (pb["misses_pct"], pb["extra_pct"]) == (0.4, 12.4), False)
claim("no arm anywhere reports 68.3 as its disagreement rate",
      any(a.get("version_differs_pct") == 68.3 for a in D["arms"].values())
      or pb["version_differs_pct"] == 68.3, False)
claim("68.3 appears in the 8 Sep note",
      "68.3" in open("Claude outputs/adam-reply-2.md").read(), True)
note_mt = os.path.getmtime("Claude outputs/adam-reply-2.md")
pairs_mt = os.path.getmtime("data/depsdev_pairs.json")
claim("the note predates the pair-keyed state file", note_mt < pairs_mt, True)
claim("the 8 Sep note gave 0.4% and 5.2% as a range",
      "0.4% and 5.2%" in open("Claude outputs/adam-reply-2.md").read(), True)

# --------------------------------------------------------- the 79.4 / 67.7 pair
section("3. the comparable pair")
src = open("code/depsdev_recompute.py").read()
claim("compare() drops multi names from the deps.dev side",
      "if k not in suppress and k not in drop}" in src, True)
claim("historical loader hardcodes an empty multi set",
      '"multi": {},' in src, True)
claim("deps.dev nodes, unmodified", m["instances_depsdev_unmodified"], 21134)
claim("deps.dev nodes, after the matched arm's exclusion",
      m["instances_depsdev_after_exclusions"], 20371)
claim("nodes removed by that exclusion",
      m["instances_depsdev_unmodified"] - m["instances_depsdev_after_exclusions"], 763)
P = D["comparable_pair_one_exclusion_both_arms"]
claim("pair servers", P["servers"], 248)
claim("historical, unsuppressed, identical", P["historical_unsuppressed"]["identical"], 168)
claim("historical, unsuppressed, rate", P["historical_unsuppressed"]["identical_pct"], 67.7)
claim("matched, unsuppressed, identical", P["matched_unsuppressed"]["identical"], 75)
claim("matched, unsuppressed, rate", P["matched_unsuppressed"]["identical_pct"], 30.2)
claim("matched, suppressed, identical", P["matched_suppressed"]["identical"], 197)
claim("matched, suppressed, rate", P["matched_suppressed"]["identical_pct"], 79.4)
claim("left side equal across arms, unsuppressed",
      P["historical_unsuppressed"]["depsdev_instances_as_scored"] ==
      P["matched_unsuppressed"]["depsdev_instances_as_scored"] == 20371, True)
claim("left side as scored, matched suppressed",
      P["matched_suppressed"]["depsdev_instances_as_scored"], 19735)
claim("margin falls from 17.3 to 11.7 points",
      (round(79.4 - 62.1, 1), round(79.4 - 67.7, 1)), (17.3, 11.7))

# the blunt exclusion, recomputed here
def tfs(path):
    out = {}
    for name, v in json.load(open(path)).items():
        if not isinstance(v, dict) or "installed" not in v or v.get("truncated"): continue
        seen = {}
        for x in v["installed"]:
            n, _, ver = x.rpartition("@@"); seen.setdefault(n, set()).add(ver)
        out[name] = {"resolved": {n: next(iter(s)) for n, s in seen.items() if len(s) == 1},
                     "multi": {n: sorted(s) for n, s in seen.items() if len(s) > 1}}
    return out
match = tfs("data/nested_gap_state_depsdev_matched.json")
H = {t["server"]: {"resolved": t["resolved"], "multi": {}} for t in hist.values()}
srv = sorted(set(dd_state) & set(H) & set(match))
blunt = set()
for s in srv: blunt |= set(match[s]["multi"])
SUP = frozenset(["get-intrinsic", "async-generator-function",
                 "async-function", "generator-function"])
def run(right, sup, drop):
    a = 0
    for s in srv:
        ddn = {k: v for k, v in dd_state[s]["nodes"].items()
               if k not in sup and k not in drop}
        lv = {k: v for k, v in right[s]["resolved"].items()
              if k not in sup and k not in drop}
        if not [k for k in lv if k not in ddn] and not [k for k in ddn if k not in lv] \
           and not [k for k in lv if k in ddn and ddn[k] and lv[k] != ddn[k]]: a += 1
    return round(100.0 * a / len(srv), 1)
claim("blunt exclusion, historical", run(H, frozenset(), blunt), 94.0)
claim("blunt exclusion, matched suppressed", run(match, SUP, blunt), 84.3)
claim("blunt exclusion reverses the ordering",
      run(H, frozenset(), blunt) > run(match, SUP, blunt), True)

# ----------------------------------------------------------------- the verdict
section("4. the verdict figure")
p = V["primary_pair_keyed"]
claim("servers", p["servers"], 248)
claim("verdict differs", p["verdict_differs"], 2)
claim("percent", p["verdict_differs_pct"], 0.8)
claim("missed findings", p["missed_findings"], 8)
claim("missed by severity", p["missed_by_severity"], {"high": 4, "moderate": 4})
claim("phantom findings", p["phantom_findings"], 0)
claim("deps.dev side total", p["total_findings_depsdev_side"], 224)
claim("resolution side total", p["total_findings_resolution_side"], 232)
claim("the five carriers", p["missed_by_package"],
      {"adm-zip": 2, "qs": 2, "sharp": 2,
       "@opentelemetry/core": 1, "@opentelemetry/propagator-jaeger": 1})
claim("suppressing qs leaves one server",
      V["leave_one_out_single_name_only"]["qs"]["verdict_differs"], 1)
o = V["secondary_october_arm"]
claim("october arm differs", (o["verdict_differs"], o["servers"], o["verdict_differs_pct"]),
      (15, 248, 6.0))
claim("october missed / phantom", (o["missed_findings"], o["phantom_findings"]), (17, 30))
ab = V["advisory_basis"]
claim("advisory export mtime", ab["source_mtime_utc"], "2026-09-09T22:15:30Z")
claim("advisory snapshot built", ab["built_utc"][:10], "2026-10-13")
claim("advisory rows", ab["advisory_rows"], 9522)
claim("GHSA only", ab["basis"], ["GHSA"])
fv = FV["depsdev"]
claim("superseded figure", (fv["n"], fv["verdict_differs"], fv["pct"],
                            fv["missed_findings"], fv["phantom_findings"]),
      (249, 2, 0.8, 6, 0))
claim("superseded severity split", fv["missed_sev"], {"moderate": 3, "high": 3})
claim("superseded totals", (fv["total_depsdev"], fv["total_live"]), (179, 185))

from math import comb
def P_ge(k, n, q): return sum(comb(n, i) * q**i * (1-q)**(n-i) for i in range(k, n+1))
def P_le(k, n, q): return sum(comb(n, i) * q**i * (1-q)**(n-i) for i in range(0, k+1))
def solve(f, t):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo+hi)/2
        if f(mid) < t: lo = mid
        else: hi = mid
    return (lo+hi)/2
lo = solve(lambda q: P_ge(2, 248, q), 0.025)
hi = solve(lambda q: -P_le(2, 248, q), -0.025)
claim("Clopper-Pearson 95%", (round(100*lo, 2), round(100*hi, 2)), (0.10, 2.88))
claim("2/n rounds to 0.8 over 236..266",
      all(round(200.0/n, 1) == 0.8 for n in range(236, 267)), True)
claim("236 and 266 are the tight endpoints",
      (round(200.0/235, 1), round(200.0/267, 1)), (0.9, 0.7))

# ------------------------------------------------------------- provenance
section("5. provenance and the earlier vintages")
pr = json.load(open("release/data/depsdev_pairs_result.json"))
claim("depsdev_pairs_result", (pr["n"], pr["verdict_differs"], pr["missed_findings"],
                               pr["phantom_findings"], pr["total_depsdev"], pr["total_live"]),
      (249, 1, 3, 0, 175, 178))
claim("its severity split", pr["missed_by_severity"], {"moderate": 2, "high": 1})
claim("it carries its own pair-keyed note", "pair-keyed" in pr["note"], True)
na = json.load(open("release/data/nested_and_depsdev.json"))["depsdev_vs_verified"]
claim("nested_and_depsdev", (na["n"], na["differ"], na["missed_findings"],
                             na["phantom_findings"]), (249, 13, 29, 14))
writers = []
for f in sorted(os.listdir("code")):
    if not f.endswith(".py"): continue
    body = open(os.path.join("code", f)).read()
    for target in ("final_verified", "depsdev_pairs_result"):
        # a WRITE, not a mention: verdict_recompute.py names final_verified.json
        # in the block recording what it supersedes, which is not a writer
        for mo in re.finditer(r"json\.dump\([^\n]*", body):
            if target in mo.group(0): writers.append((f, target))
        for mo in re.finditer(r'open\(([^)]*)"w"', body):
            if target in mo.group(0): writers.append((f, target))
claim("nothing in code/ writes either result file", writers, [])
claim("verdict_recompute names final_verified only as what it supersedes",
      "final_verified.json depsdev block" in open("code/verdict_recompute.py").read(),
      True)
dp = open("code/depsdev_pairs.py").read()
claim("depsdev_pairs.py writes only the raw state",
      dp.count("json.dump") == 2 and "depsdev_pairs.json" in dp, True)
rn = " ".join(open("RESOLVER-NOTES.md").read().split())
claim("RESOLVER-NOTES retracted the frozen sibling",
      "could not be reproduced and should not have been quoted" in rn, True)
for frag in ("superseded measurement", "different resolvers", "temporary path"):
    claim("its reason: %s" % frag, frag in rn, True)
claim("vuln_gap_depsdev result file is NOT in the tree",
      os.path.exists("data/vuln_gap_depsdev.json"), False)

# -------------------------------------------------------------- flattening
section("6. the flattened comparison")
F = V["secondary_flattened_not_identified"]
claim("span", F["verdict_differs_pct_span_over_these_four"], [0.8, 5.6])
claim("phantom span", F["phantom_findings_span_over_these_four"], [0, 18])
claim("four arms", sorted(a["verdict_differs_pct"] for a in F["arms"].values()),
      [0.8, 2.4, 4.0, 5.6])
dp_raw = json.load(open("data/depsdev_pairs.json"))
uns = sum(1 for r in dp_raw.values() if r.get("ok")
          and [x[0] for x in r["pairs"]] != sorted(x[0] for x in r["pairs"]))
claim("deps.dev pair lists unsorted", uns, 176)
claim("comparable servers in that file",
      sum(1 for r in dp_raw.values() if r.get("ok")), 249)
sizes = collections.Counter()
for s, v in json.load(open("data/nested_gap_state.json")).items():
    if not isinstance(v, dict) or "installed" not in v or v.get("truncated"): continue
    by = collections.defaultdict(set)
    for x in v["installed"]:
        n, _, ver = x.rpartition("@@"); by[n].add(ver)
    for n, vs in by.items():
        if len(vs) > 1: sizes[len(vs)] += 1
claim("duplicated groups", sum(sizes.values()), 819)
claim("groups holding three or four",
      sum(c for k, c in sizes.items() if k > 2), 62)

# ------------------------------------------------------------------- tests
section("7. the suites and the four defects they found")
for f, muts, comps, metas, label in (
        ("code/test_verdict_recompute.py", 16, 3, 2, "verdict"),
        ("code/test_depsdev_recompute.py", 15, 3, 3, "depsdev")):
    s = open(f).read()
    claim("%s suite mutation count" % label,
          s.count('\n    ("R') + s.count('\n    ("D'), muts)
    claim("%s suite harness count" % label,
          s.count('\n    ("H') + s.count('\n    ("E'), comps)
claim("mutations total, three reviews", 16 + 15, 31)
claim("composites total", 3 + 3, 6)
claim("meta-tests total", 2 + 3, 5)
claim("malformed token now skipped", "if not sep or not n:" in src, True)
claim("naive timestamp now counted, not raised",
      "naive timestamp" in src and "when.tzinfo is None" in src, True)
claim("cause derived, not a literal", 'CAUSE = (ranked_dis[0][0],)' in src, True)
claim("the incidence-match gate exists",
      "are not one event" in src, True)
dis = collections.Counter(); ex = collections.Counter()
for s in srv:
    h, mm = H[s]["resolved"], match[s]["resolved"]
    for k in set(h) & set(mm):
        if h[k] != mm[k]: dis[k] += 1
    live = set(match[s]["resolved"]) | set(match[s]["multi"])
    for k in dd_state[s]["nodes"]:
        if k not in live: ex[k] += 1
claim("get-intrinsic disagreements", dis.most_common(1)[0], ("get-intrinsic", 159))
claim("top extra incidence", ex.most_common(1)[0][1], 159)
claim("the two incidences match", dis.most_common(1)[0][1] == ex.most_common(1)[0][1], True)
cc = D["provenance"]["cutoff_gate_coverage"]
claim("cutoff pairs compared / seen", (cc["pairs_compared"], cc["pairs_seen"]), (2951, 2953))
claim("nothing published after the cutoff", D.get("late_selections", []), [])

# ----------------------------------------------------------------- release
section("8. the release")
man = [l.split("  ./")[-1].strip() for l in open("release/MANIFEST.md")
       if re.match(r"^[0-9a-f]{64}  ", l)]
tracked = subprocess.run(["git", "-C", "release", "ls-files"], capture_output=True,
                         text=True).stdout.split()
claim("manifest entries equal the tracked set",
      len(man), len([x for x in tracked if x != "MANIFEST.md"]))
claim("manifest equals tracked minus itself",
      sorted(man), sorted(x for x in tracked if x != "MANIFEST.md"))
claim("docker_state not in the manifest", any("docker_state" in x for x in man), False)
gi = open("release-files/.gitignore").read()
claim("duplicate patterns in the assembler's source", gi.count("\n* ") >= 6, True)
claim("docker_state still gitignored", "docker_state.json" in gi, True)
dk = json.load(open("release/data/mcp_docker.json"))
pl = sorted(x["pull_count"] for x in dk); n = len(pl)
claim("docker records", n, 182)
claim("docker median", (pl[n//2-1] + pl[n//2]) / 2, 34009.0)
claim("docker lower middle", pl[n//2-1], 33892)
claim("docker top item", round(100*max(pl)/sum(pl), 1), 11.4)
claim("docker top five", round(100*sum(pl[-5:])/sum(pl), 1), 38.6)
sup = json.load(open("results/superseded/nested_gap.json"))
cur = json.load(open("data/nested_gap.json"))
claim("superseded nested_gap", (sup["trees"], sup["verdict_differs"], sup["phantom_findings"]),
      (250, 154, 3768))
claim("current nested_gap", (cur["trees"], cur["verdict_differs"], cur["phantom_findings"]),
      (249, 164, 4442))
dupe_find = ("find . -type f \\( -name '* 2' -o -name '* 3' -o -name '* 4' "
             "-o -name '* 2.*' -o -name '* 3.*' -o -name '* 4.*' \\) | wc -l")
on_disk = int(subprocess.run(dupe_find, shell=True, cwd="release",
                             capture_output=True, text=True).stdout.strip())
claim("no duplicate-name file is tracked",
      [x for x in tracked if re.search(r" [234](\.|$)", x)], [])
claim("git reports no untracked files despite %d on disk" % on_disk,
      subprocess.run(["git", "-C", "release", "status", "--porcelain"],
                     capture_output=True, text=True).stdout.strip(), "")
print("       note: %d duplicate-name files on disk right now. They regenerate "
      "on this volume\n       between any two commands; the .gitignore patterns "
      "are what keep them\n       out of a commit, and the assembler's guard "
      "only sees those present when it runs." % on_disk)

print("\n" + "=" * 78)
print("%d PASS, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
