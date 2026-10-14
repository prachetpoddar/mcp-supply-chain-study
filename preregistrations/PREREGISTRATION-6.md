# Pre-registration: why does a frozen SBOM over-report?

Written 13 October 2026, before the advisory snapshot carries publication dates
and before any decomposition is computed. The causes, the decision rule, the
denominators, the clustering treatment, the downgrade rule and the expected
direction are all fixed below.

## Why

The frozen-versus-live measurement is settled and published: an advisory scanner
reading a tree frozen at each root's release date flags 130 of 249 servers
(52.2%) that are clean when installed, flags none in the other direction, and
produces 4,442 findings on the frozen side against 15 on the live side. Section
13 of the lock spec and `RESOLVER-NOTES.md` carry it, and the LinkedIn post of
13 October states the limitation this study removes: the design cannot say
whether a frozen-side finding is there because the install moved past a fix, or
because the advisory did not exist when the package shipped. The advisory
snapshot discards `published`, so the question is currently unanswerable from
the released data rather than merely unanswered.

## Population

Every **frozen-side-only finding** in the existing measurement: one record per
`(tree, package, advisory id)` present in the frozen tree's advisory join and
absent from the live tree's. That is the 4,442. The 906 `(tree, package)` pairs
and the 130 trees are the two coarser units, both reported.

No root, package or advisory is added or removed. This study re-reads the same
`data/nested_gap_state.json` and the same advisory basis (`GHSA`, prereleases
included, one finding per `(package, advisory id)` per tree). If the headline
crosstab is not reproduced bit-for-bit as `130 / 0 / 37 / 82` after the snapshot
rebuild, this study stops and the rebuild is treated as a defect rather than as
a new vintage.

## The decision rule, fixed now

For a finding on package `P` at frozen version `Vf` under advisory `A`, in a
tree whose root was published at `Dr` (`root_published` in the walk state):

- **post_ship** if `A.published > Dr`. The advisory did not exist when the root
  shipped. The flag is not a stale description of the software; it is new
  information landing on an old pin.
- **pre_ship_stable** if `A.published <= Dr` and `A.modified <= Dr`. The
  advisory was already public when the root shipped, so the root shipped a pin
  that was already covered by a published advisory, and the install has since
  moved past the fix.
- **pre_ship_modified** if `A.published <= Dr` and `A.modified > Dr`. The
  advisory existed but its affected range may have been widened afterwards, so
  whether it covered `Vf` at ship time is not established. Reported separately
  and never merged into `pre_ship_stable`.
- **undated** if `A.published` is absent from the export. Reported, excluded
  from the split denominator, and assigned to each side in turn as a
  sensitivity.

`pre_ship_modified` and `undated` together form the indeterminate band.

## Quantities reported

1. The split over findings, with the indeterminate band shown, not folded in.
2. The same split over `(tree, package)` pairs.
3. A tree-level classification of each of the 130: all of its frozen-side-only
   findings `post_ship`, all `pre_ship_stable`, or mixed.
4. The split among roots published within the previous 30 days, where the rate
   is already 42 of 75. If the young cohort is mostly `pre_ship_stable`, the
   30-day result means something different from what it means if it is mostly
   `post_ship`.

## Clustering, fixed now because the counts are concentrated

Findings are not independent: 56 packages carry the 4,442 and five hold 82%,
with `hono` alone at 2,017. Every finding-level proportion is reported with the
publisher and package cluster bootstrap already in the codebase, and with the
value recomputed after suppressing `hono`, by the same mechanism as
`code/gap_leave_one_out.py`. A finding-level proportion is not reported alone.

## Expected direction, stated before computing

`post_ship` is expected to dominate, because advisories accrue continuously
while a root's frozen tree does not, and because the existing age gradient (56%
of roots under 30 days old disagreeing, rising to 93.3% past 180 days) is what
accrual would produce. The informative outcome is the other one: a large
`pre_ship_stable` share would say that MCP servers ship pins already covered by
published advisories, which is a claim about publisher behaviour rather than
about SBOM staleness, and it is not the claim the post makes.

## Downgrade rule

If the indeterminate band exceeds 10% of findings, the split is reported as a
bound rather than a point estimate, at every unit of analysis. If it exceeds
25%, the decomposition is reported as unestimable and the limitation in the
published post stands unchanged.

## What this still cannot settle

`published` in the OSV export is when the advisory entered OSV, which can lag
the upstream GHSA publication. `post_ship` is therefore an **upper bound** on
"no one could have known at ship time", and this study makes no claim about when
knowledge of a vulnerability became available. Separately, the snapshot is dated
2026-09-09, so advisories published after that date are invisible to both arms
and cannot enter the split in either direction.

## Adequacy floor

The decomposition is reported only if the rebuilt snapshot reproduces the
existing crosstab exactly, and only after an independent adversarial review of
the new code with reviewer-designed semantic mutations. Nothing here is reported
on the strength of the author's own reading of the output.

## Amendment one, 13 October 2026

Written after rebuilding the snapshot with dates and inspecting the date fields,
before any decomposition is computed.

1. **The `undated` category is empty in this export.** Every one of the 9,522
   advisory rows carries a `published` timestamp (`rows_without_published: 0`,
   `advisories_without_published: 0` in the rebuilt metadata), so the
   indeterminate band is `pre_ship_modified` alone. This is recorded now so that
   an empty category cannot later be presented as a design choice. The
   `undated` branch and its sensitivity stay in the code and report zero.

2. **`modified` is not monotone with `published`.** 199 rows, covering 178
   distinct advisories across 161 packages, carry `modified` *earlier* than
   `published`. All 178 were published between 2020 and 2022 and the gap is 0 to
   11 days, median 2, so this is a historical quirk in older OSV entries rather
   than a systematic defect. It nonetheless makes `modified` unusable on its own
   as a last-change timestamp. The `pre_ship_modified` test therefore uses
   `last_change = max(published, modified)`, which is monotone by construction
   and can only move a row from `pre_ship_stable` into the indeterminate band,
   never the reverse. The 199 rows are reported with the result.

3. **The reproduction gate is met.** Stripping `published` and `modified` from
   the rebuilt snapshot yields a structure identical to the shipped
   `data/advisories_npm.json`, whose sha256 matches the value recorded in the
   gap result's provenance. The rebuild adds fields and changes nothing else.

## Amendment two, 13 October 2026

Written after an independent adversarial review of the first run, and after
verifying its central finding against the data directly. The first run's
headline is withdrawn and replaced. Recorded before the corrected analysis is
written, and the numbers quoted here are the verification figures, not the
corrected run's output.

1. **The population in this protocol was the wrong one, and the conclusion it
   licensed is withdrawn.** A finding is frozen-side-*only* precisely when the
   advisory covers the frozen version and not the installed one, which requires
   a fixed version inside the root's declared range published after the root
   shipped. Since GHSA advisories are published at or after the fix in all but
   a small minority of cases (`data/cra_advisory_delay.json` records
   advisory-before-fix in 312 of 7,084 pairs, 4.4%, median exposure window 11.7
   days), `post_ship` is close to forced on that population. The first run's
   99.8% is arithmetically correct and structurally uninformative as a contrast.
   Nothing may be concluded from it about publisher behaviour.

2. **The headline population becomes all frozen-side findings**, that is
   frozen-only plus both-arms-flag: 4,638 findings rather than 4,442. That
   population carries no fix-timing filter. Verification figure: 98.4%
   `post_ship`, 64 `pre_ship_stable`, 12 `pre_ship_modified`.

3. **The excluded cell becomes a reported quantity in its own right.** Among
   the 196 findings that both arms flag, 58 are `pre_ship_stable` and 8
   indeterminate, so 66.3% `post_ship` against 99.8% in the frozen-only cell.
   The 58 are advisories already published when the root shipped, on versions
   the root still installs today. Verification figure: 13 of 249 servers, 5.2%,
   across 18 packages, with 38 high and 3 critical. This is the publisher-side
   question the frozen-only population structurally excludes, and it is
   reported at the server level because the finding level is concentrated.

4. **Three deviations in the first run are declared rather than quietly
   carried.** `undated` was inside the split denominator where item 4 of the
   original protocol excludes it; it is zero-valued in this export so no
   reported number moved, and the corrected code implements the pre-registered
   denominator. The tree-level unit was 164 and this protocol named 130: 164 is
   correct for findings (130 frozen-clean trees plus the 34 both-flag trees
   whose advisory lists differ), and both populations are now reported, with the
   note that 24.5% of the 4,442 come from servers that are not clean when
   installed. The publisher-level cluster bootstrap this protocol promised was
   not run, and cannot be run as promised, because the existing publisher map
   keys root MCP packages while the clusters here are dependency packages;
   npm scope is used as a declared approximation and the result is reported
   across four cluster units rather than behind one interval.

5. **The interval is reported to two decimals.** `[99.0, 100.0]` was a rounding
   artifact of a 97.5th percentile at 99.98, and an upper bound printed at the
   parameter boundary invites the reading that 100% cannot be excluded.

6. **The age gradient is quoted as the code prints it.** The original protocol
   cited "56% rising to 93.3% past 180 days". `nested_gap.py` prints 56%, 54%,
   70%, 97%, 86%: the oldest bucket falls, and 93.3% is the pooled 181-plus
   figure. The gradient is still consistent with accrual and is no longer
   quoted as monotone.

7. **Gate and parser requirements, added now and binding on the corrected
   run.** The reproduction gate stops being prose: the corrected code asserts
   the published crosstab, finding counts and pair counts against
   `data/nested_gap.json` at run time, and asserts that the count of negative
   publication gaps equals the count of pre-ship findings. The timestamp parser
   raises on anything it cannot read rather than returning a null that the
   change test silently reads as an absent date, because that null moved rows
   out of the indeterminate band and inverted the guarantee amendment one item 2
   states. Full provenance is recorded: interpreter version, code hash, and
   hashes of both inputs.

## Amendment three, 13 October 2026

Written after a second independent adversarial review, by a reviewer that had
not seen the first, and after verifying its load-bearing findings directly. Two
reviews in a row found the same defect in different clothes: an attempt to read
publisher behaviour out of a design that cannot produce it. This amendment stops
that attempt rather than making a third one.

1. **The headline is the age gradient, not the pooled share.** A finding exists
   only if its advisory is in the 2026-09-09 snapshot, so for a root shipped *d*
   days before the snapshot the window for a post-ship advisory is *d* days while
   the window for a pre-ship one is the whole history of OSV. The pooled share is
   therefore non-decreasing in root age *in expectation*. Observed, it is not:
   90.6% at 30 days or less, 98.8% at 31 to 90, **98.2% at 91 to 180**, 99.7% at
   181 to 365, 100.0% past 365. The third band sits below the second, the bands'
   intervals overlap heavily, and the inversion is carried by a handful of
   roots, so only the endpoints are a safe statement. Amendment four replaces
   the monotone wording this item used. The pooled 98.4% is a property of this corpus's age mix and is reported
   only alongside the gradient, never as a standalone rate.

2. **The behavioural question gets its pre-registered answer, and it is a
   null.** Both cells carry a fix-availability condition, in opposite
   directions: a frozen-only finding requires an in-range fix published after
   the root shipped, and a both-arms finding requires that no in-range fix exists
   even today. Verified: all 66 pre-ship findings in the both cell have
   `frozen_version == live_version`, so that cell selects dependencies that have
   not moved at all. The cell free of both conditions, a pre-ship advisory on a
   pin that later became fixable, holds **10 findings of 4,638, 0.2%**. That is
   the answer to "do these servers ship pins already covered by published
   advisories", and amendment two item 2's claim that the pooled population
   "carries no fix-timing filter" is withdrawn as false.

3. **Amendment two item 3 is withdrawn in full.** It reported 58 findings across
   13 named servers as a publisher-side result. In 7 of the 24 (root, package)
   pairs, covering 19 of the 58 findings, the tree carries two copies of the
   flagged package, the flagged one and a strictly newer one the advisory does
   not cover (13 is the server count, not the pair count; amendment four
   corrects the parentage wording here too): `@fluxweave/cli`
   installs `form-data` 2.3.3 and 2.5.6 with the finding on 2.3.3,
   `@kahflane/whatsapp-mcp` installs `protobufjs` 6.8.8 and 8.8.0 with the
   finding on 6.8.8, `hyros-mcp` installs `@modelcontextprotocol/sdk` 1.23.0 and
   1.32.1 with the findings on 1.23.0. A root that installs both a clean and a
   covered copy did not choose the covered one. No server is named in any
   reported quantity, and the cell is reported as what it is: dependencies that
   have not moved since ship, confounded by nested duplicate copies, with the
   duplicate count given.

4. **Every finding-level proportion carries its interval and its leave-one-out,
   which the original protocol required and neither earlier run produced.** The
   two that were reported bare do not survive it: the both-cell 66.3% has a
   package-cluster 95% interval of [47.37, 80.00], and the young-cohort 90.6%
   has [28.89, 96.64], falling to 86.1%, 75.0% and 25.6% as `hono`, `fast-uri`
   and `qs` are removed in turn. The young cohort is the one item 4 of the
   original protocol said decides the interpretation, and its interval does not
   exclude "mostly pre-ship", so no interpretation is drawn from it.

5. **The gate stops depending on `assert`.** `python3 -O` removed the whole
   reproduction gate, the category invariant and the undated check, and the
   output was byte-indistinguishable between a gated and an ungated run. The
   checks now raise explicitly, and the recorded provenance carries `__debug__`
   and the number of checks that ran.

6. **The gate covers the populations actually reported.** It constrained only
   the withdrawn frozen-only cell, so dropping `include_prerelease` from the
   advisory join left that cell at exactly 4,442 while moving the headline, the
   both cell and every figure derived from it. A prerelease-sensitive behaviour
   check is added, because the pre-registered join rule includes prereleases and
   nothing tested that it was on.

7. **Three pre-registered quantities that were missing are added**: the
   pair-level split, the `undated` sensitivity in place of an assertion
   forbidding the category, and the indeterminate band counted as
   `pre_ship_modified` plus `undated` rather than the first alone.

8. **One docstring claim is corrected.** "30% of rows depend on the
   fractional-second path" is true of `modified` and false of `published`, which
   is the field that decides the category: no `published` value in the snapshot
   carries a fractional second.

## Amendment four, 14 October 2026

Written after a third independent adversarial review, scoped to the restated
claims and conducted by a reviewer that had seen neither earlier round. Two of
its findings are corrections to amendment three, and both were visible in output
this project had already printed.

1. **The age bands are not monotone, and amendment three said they were.** The
   observed shares are 90.6, 98.8, **98.2**, 99.7, 100.0: the 91-180 band sits
   below the 31-90 band. The mechanism is non-decreasing in expectation, the
   realisation is not, the bands' intervals overlap heavily ([94.55, 99.77]
   against [90.43, 99.72], and the youngest band's [28.89, 96.64] overlaps all
   four others), and the inversion is carried by a handful of roots. This is the
   same error amendment two item 6 said it had retired, reintroduced one
   amendment later in the author's own wording. What may be said is the pair of
   endpoints, 90.6% at 30 days or less against 100.0% past 365, with the bands
   shown and the non-monotonicity stated. The output now carries
   `age_bands_are_monotone`, which reads false, and the band edges, which were
   unpinned.

2. **The confound claimed parentage the released data does not carry.**
   Amendment three item 3 said the flagged copy is "the older nested copy" that
   "the root's own declaration did not select". The walk state keeps flat
   `(name, version)` sets with no edges and no depth, and `nested_gap.py` states
   that it does not model placement, so which copy the root declared is not
   recoverable from the release. The claim is narrowed to what the data
   supports: the tree installs two versions of the flagged package, the flagged
   one and a strictly newer one the advisory does not cover, so the finding
   cannot be attributed to a single declared pin. "Newer" and "not covered" were
   prose; both are now computed, and all 19 duplicate findings satisfy both.

3. **The two cells are walk-date dependent and the age bands are not.** The
   published live arm was resolved about a month after the advisory snapshot.
   This repository already holds an arm resolved at the snapshot instant, and
   the decomposition is now run against both. The age bands and the pooled share
   are **identical** across the two arms, band for band, which is the strongest
   robustness statement available for item 1's result. The cells move: the null
   goes from 10 findings across 7 servers to 3 across 3, all three
   indeterminate, so it survives conservatively; the never-moved cell goes from
   58 findings across 13 servers to 64 across 15. Both arms are reported and
   neither is chosen.

4. **The null is reported split.** Its 10 findings are 6 `pre_ship_stable` and 4
   `pre_ship_modified`, so 40% of it is the band the original protocol says is
   never merged into the stable category. Under the aligned arm it is 3 of 3
   indeterminate. The split is in the output and its denominator is named.

5. **The gate now covers the populations that are reported.** It constrained
   only the withdrawn frozen-only cell, so a plausible one-line change that
   moved the 4,638 and the both cell while leaving the frozen-only cell at
   exactly 4,442 passed it. Both counts are pinned, and the prerelease probe
   raises when its package is absent instead of disappearing.
