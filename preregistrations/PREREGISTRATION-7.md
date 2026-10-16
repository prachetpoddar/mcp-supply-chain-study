# Pre-registration: recomputing the deps.dev divergence bound

Written 16 October 2026, after reproducing the published bound bit-for-bit and
before computing anything with a different input. The populations, the classes,
the alignment choice, the reproduction gate and the absence of a directional
prediction are all fixed below.

## Why

The published bound compares deps.dev's dependency graph for each MCP server
root against a resolved tree taken from
`data/resolved_trees_for_depsdev.json`. That file is a **third resolution
vintage**: it reports 90 nodes for `graphweft` where the corrected resolver
gives 92 against the registry as of 2026-09-09 and 87 against the registry a
month later. The bound therefore rests on a resolver that has since been
corrected, and the maintainer of mcp-audit has labelled it in his own
documentation as measured on 2026-09-08 and not recomputed. This recomputes it.

## Populations

**Left, unchanged.** deps.dev's graph for the exact (root name, root version)
of each server, from `data/depsdev_state.json`, fetched 2026-09-07 and
2026-09-08. Nothing is re-fetched: the left side is held fixed so that any
change in the bound is attributable to the right side alone.

**Right, primary.** The corrected resolver's live tree from
`data/nested_gap_state_aligned.json`, whose live arm resolves against the
registry at the advisory snapshot instant, 2026-09-09T22:15:30Z. This is within
two days of the deps.dev fetch, and is the closest alignment available.

**Right, sensitivity.** The same walk's October arm,
`data/nested_gap_state.json`, resolved about a month later. Reported alongside,
never instead.

**Right, historical.** `data/resolved_trees_for_depsdev.json`, the input the
published bound used, reported so the change is visible rather than asserted.

**Comparable set.** The 248 servers that both walks cover at the **same root
version**. Verified before writing this: root versions agree for 248 of the 249
servers in the published bound, zero disagree, and one is absent from the gap
walk. A server whose root version differs between the two walks would make the
comparison meaningless and is excluded, with the count reported.

## Classes, unchanged from the published measurement

- `missing_in_depsdev`: packages the resolution installs and deps.dev omits.
- `extra_in_depsdev`: packages deps.dev lists and the resolution does not install.
- `version_differs`: packages both sides carry at different versions.

## Quantities reported

Over the comparable set, for each of the three right-hand sides: the share of
servers whose graphs are identical, the share with at least one version
disagreement, the share where deps.dev lists fewer packages, the share with at
least one package deps.dev misses, median nodes on each side, and the total
package-instance delta.

## No directional prediction, and why

Two mechanisms push opposite ways and this study cannot say in advance which
dominates. The corrected resolver is closer to a real `npm install`, validated
at 9,351 of 9,355 nodes across 114 packages on two disjoint out-of-sample
draws, so if deps.dev models npm's selection faithfully the agreement should
rise. If deps.dev instead reports a union over a range's satisfying set without
performing selection, the correction moves the right side away from it and
agreement should fall. Stating no expectation is the honest position here, and
it is recorded so that whichever happens cannot be presented afterwards as the
predicted one.

## Reproduction gate

The recomputation is reported only if the historical right-hand side reproduces
the published figures exactly: 249 comparable servers, 154 identical (61.8%),
38.2% with a version disagreement, 1.2% where deps.dev lists fewer, and a
+0.2% instance delta. Already verified once: re-running `depsdev_delta.py
report` against the shipped inputs produced a `depsdev_delta.json` identical to
the released one.

## What this still cannot settle

The left side is a snapshot of deps.dev from early September and is not
re-fetched, so this measures how far the published graph of that date stands
from a corrected resolution, not how far deps.dev stands from npm today.
Nothing here is a claim about deps.dev's current accuracy.

## Amendment one, 16 October 2026

Written after the first run and after diagnosing two defects in it, before any
figure from it is reported anywhere. The first run's `version_differs` and
`extra_in_depsdev` figures are withdrawn.

1. **The right-hand side is not a one-version-per-name map, and treating it as
   one manufactured disagreements.** The gap walk's live arm is a list of
   `(name, version)` pairs, and **827 packages across 170 of the 248 servers
   appear at more than one version**. The first run collapsed each name to
   whichever version came first in that list and compared the arbitrary pick
   against deps.dev's single version, so a tree carrying both 2.3.3 and 2.5.6
   of a package could be scored as disagreeing on the strength of list order.
   The 70.2% `version_differs` figure that produced is withdrawn.

   The comparison is now defined on the **single-version subset**: names the
   resolution carries at exactly one version. Names it carries at several are
   reported as their own class, `multi_version_in_resolution`, with a count,
   because deps.dev's graph has no way to express them and scoring them either
   way would be a choice rather than a measurement.

2. **`extra_in_depsdev` is concentrated and must be reported as such.** Nine
   distinct packages account for the whole class, and three of them carry it:
   `async-generator-function` on 159 servers, `async-function` on 158,
   `generator-function` on 158. A share of servers computed over that is a
   statement about three names, not about deps.dev's graph in general, so the
   class is reported with its package concentration and with the share
   recomputed after suppressing the three, by the same rule the frozen-side
   counts follow.

3. **The reproduction gate stands and is unaffected.** The historical arm
   reproduced all five published figures exactly on the 249-server set before
   any of this was computed, and that gate is kept as written.

4. **Still no directional prediction.** The first run moved the bound toward
   more divergence, and both defects above push in that direction, so the
   corrected figures may move back. No expectation is recorded now that one run
   has been seen, and the first run's numbers are not treated as a prior.

## Amendment two, 16 October 2026

Written after the first run's version-disagreement figure was traced to its
cause, and before the matched-date walk is run.

1. **The 69.8% was registry drift, not resolver behaviour, and is withdrawn.**
   Of the 413 version disagreements between the corrected arm and deps.dev,
   **412 are cases where the historical arm agreed with deps.dev and the
   corrected arm moved**, and the moves are to newer releases: `@types/node`
   26.4.1 to 26.5.1, `cytoscape` 3.34.2 to 3.34.3, `undici-types` 8.3.0 to
   8.9.0, `electron-to-chromium` 1.5.422 to 1.5.425, `node-releases` 2.0.54 to
   2.0.55. Exactly one of the 413 moves backward, `get-intrinsic` 1.3.1 to
   1.3.0, which is the shape a selection-rule difference would take. The
   historical trees were resolved on 2026-09-07, the same day as the deps.dev
   fetch; the aligned arm resolves on 2026-09-09. Two days of npm moved 413
   picks, so the comparison confounds the resolver correction with churn and no
   number from it is reported.

2. **A matched-date walk is run.** `nested_gap.py` takes a `LIVE_CUTOFF` that
   discards registry versions published after a given instant. The live arm is
   re-resolved with the cutoff set to **2026-09-08T01:00:00Z**, which covers the
   deps.dev fetch window (the state file was written 2026-09-07T23:15Z and the
   pair file 2026-09-08T01:00Z). Output goes to a new state file; neither
   existing arm is overwritten.

3. **The primary comparison changes, because a better control exists.** With the
   date matched, the informative comparison is the **matched-date corrected arm
   against the historical arm**: same roots, same root versions, same registry
   date, differing only in the resolver. Any disagreement there is the
   correction and nothing else. The deps.dev comparison becomes the secondary
   question it should always have been: whether deps.dev's published graph
   tracks the pre-correction resolver or the corrected one.

4. **The cutoff is a proxy and is labelled as one.** deps.dev crawls and caches,
   so its graph is not guaranteed to reflect the state at the moment of the
   fetch. The matched cutoff aligns the resolution with the fetch, which is the
   closest control available, and no claim is made that it aligns with whenever
   deps.dev actually crawled. If the matched-date arm fails to reproduce the
   historical arm's agreement with deps.dev to within a few servers, that
   assumption is wrong and the result says so rather than being reported.

5. **Expected direction, stated now.** With the date matched, agreement between
   the corrected arm and deps.dev should return close to the historical 62% if
   deps.dev's graph is insensitive to the resolver correction, and should stay
   well below it if deps.dev encodes the same selection the old resolver used.
   The first outcome would mean the published bound survives recomputation; the
   second would mean it understated the divergence.

## Amendment three, 16 October 2026

Written after an independent adversarial review of the matched-date run and
after verifying each of its load-bearing findings directly. **The conclusion of
the matched-date run is withdrawn, and it is withdrawn in the opposite
direction from the previous two amendments.**

1. **The published bound does not understate the divergence. One package edge
   produced the whole effect.** The corrected resolver selects
   `get-intrinsic@1.3.0`, which is npm's own `latest` tag, where the
   pre-correction resolver and deps.dev both carry `1.3.1`. Verified from the
   cached packuments: `1.3.1` declares `async-function`,
   `async-generator-function` and `generator-function`; `1.3.0` declares none of
   them; `dist-tags.latest` is `1.3.0`. So that one choice produces both the
   version disagreement and the entire `extra_in_depsdev` class.

   Leave-one-out on the matched arm, 248 servers:

   | suppressed | identical to deps.dev |
   |---|---|
   | nothing | 75, 30.2% |
   | the three extra names only | 75, 30.2% |
   | `get-intrinsic` only | 75, 30.2% |
   | `get-intrinsic` and the three | **197, 79.4%** |

   79.4% is *higher* than the pre-correction resolver's 62.1%, so corrected for
   this artifact the corrected resolver agrees with deps.dev better than the old
   one did. 128 of the 248 servers disagree on nothing but `get-intrinsic`, and
   all 290 remaining disagreements have deps.dev matching the pre-correction
   pick, with none landing on a third version. The earlier leave-one-out
   suppressed the three downstream names and reported the headline unchanged,
   which read as reassurance and was in fact the symptom being removed while the
   cause stayed in.

2. **Amendment two item 3 is withdrawn: the two arms do not differ only in the
   resolver.** `mcplib.npm_walk`, which produced the historical trees, defaults
   to `include_peer=False`; `nested_gap.pair_walk` includes non-optional peers
   deliberately, and is pair-keyed with a BFS reuse rule. Four rules differ at
   once, so the 30.6% identical-package-set figure is not the size of the
   selection correction and is not reported as one.

3. **The left side was not held fixed, contrary to this protocol's own
   promise.** Dropping multi-version names removed them from the deps.dev side
   too: 21,134 deps.dev instances become 20,371, which is why a +4.0% delta sat
   beside the historical +0.2% as though both were computed the same way. The
   delta is now reported with the left side genuinely fixed, and the
   multi-excluded variant is labelled as such.

4. **The root-version check in this protocol was vacuous.** `nested_gap.run`
   copies `root_version` verbatim from `resolved_trees_for_depsdev.json`, the
   same file the historical arm reads it from, so the check compared a value
   against itself. It is replaced by a falsifiable one: no version selected in
   the matched arm may have been published after the cutoff.

5. **What survives.** The reproduction gate on the historical arm. The finding
   that the `extra` class is three names. The measured bound on the
   multi-version exclusion. And the substantive result, which is not about
   deps.dev's accuracy in general: on one widely shared edge, deps.dev's
   published graph carries a version that is not the package's `latest` tag and
   that npm would not install by default.
