# Pre-registration: the deps.dev advisory verdict, recomputed on shipping inputs

Written 18 October 2026, before computing any verdict figure from the matched
arm. The populations, the counting unit, the decision rules, the gate and the
absence of a directional prediction are fixed below.

## Why

`results/final_verified.json` reports, under `depsdev`, that deps.dev's
published graph and a live resolution differ in advisory verdict on 2 of 249
servers, 0.8%, with six missed findings at three high and three moderate and
zero phantom. The maintainer of mcp-audit has pinned that figure in his own
documentation and asked for it to be recomputed.

`RESOLVER-NOTES.md`, in the section dated 2026-10-09, already retracts the
**frozen** figure from that same file and gives three reasons. Each applies to
the deps.dev figure without modification:

1. **It is the superseded measurement.** The comparison was name-keyed on both
   sides. Flattening forces an arbitrary pick among duplicate versions and the
   pick follows traversal order. `nested_gap.pair_walk` was written to replace
   exactly that.
2. **Its arms used pre-correction resolvers.** The file is stamped 2026-09-08.
   The dist-tag preference, the deprecation preference and both time-travel
   fixes landed between 11 and 17 September.
3. **Its inputs were on a temporary path.** The per-tree state and the advisory
   snapshot both lived in `/tmp/mcpres`, which is gone.

The retraction was never extended from the frozen figure to its sibling. This
pre-registration does that and supplies the replacement.

PREREGISTRATION-7 recomputed the **graph** comparison, which is node sets and
version disagreement. It did not touch the verdict. That was a misreading of
which quantity was in dispute, recorded here rather than quietly corrected.

## What will not be attempted

**No bit-reproduction of the 0.8%.** Its advisory basis and both tree states are
overwritten. Only one advisory snapshot exists on disk,
`data/advisories_npm.json`, built 2026-10-13 from an OSV export with mtime
2026-09-09, and the September pre-tree state is gone. A reproduction gate
against the published numbers therefore cannot pass and will not be written. The
published figure is superseded, not reproduced, and the note to the maintainer
must say so in those words.

This is stated before computing so that a close result cannot later be presented
as a reproduction.

## Populations

**Left.** deps.dev's graph for the exact (root name, root version) of each
server, pair-keyed, from `data/depsdev_pairs.json`, fetched 2026-09-07 and
2026-09-08. Not re-fetched. The left side carries whatever deps.dev served then,
including every version of a name it lists more than once.

**Right, primary.** The matched arm,
`data/nested_gap_state_depsdev_matched.json`, whose live resolution runs with
`LIVE_CUTOFF` 2026-09-08T01:00:00Z, inside the deps.dev fetch window.

**Right, secondary.** `data/nested_gap_state.json`, resolved about a month
later, reported alongside and never instead, so that registry drift after the
fetch window is visible rather than assumed away.

**Comparable set.** Servers present in both sides with the same root version,
not cap-truncated, and not skipped for a missing publish time or a fetch
failure. Every exclusion is counted and named in the result.

## Counting unit and decision rules

Fixed to match `code/nested_gap.py` so the two studies are commensurable.

- A **finding** is one `(package name, advisory id)` pair per server. An
  advisory covering two version ranges of the same package counts once. This is
  the unit whose absence inflated a published phantom count from 4,442 to
  6,791.
- **Severity** is taken from the first advisory row for that
  `(package, advisory id)`, built once.
- A version is **inside** an advisory when
  `nodesemver.satisfies(version, range, loose=True, include_prerelease=True)`.
  The prerelease flag is required: `>=0.0.0` does not otherwise match
  `1.4.5-lts.2`.
- **Advisory basis** is `data/advisories_npm.json`, GHSA only. The export's
  221,191 MAL rows are excluded because a malicious-package report is a
  different object from a version-range advisory. Withdrawn advisories are
  excluded.
- **missed** is a finding present on the right and absent on the left: the
  scanner reads deps.dev, says clean, and the installed tree is not.
- **phantom** is a finding present on the left and absent on the right.
- A server's **verdict differs** when its two finding sets are unequal. Set
  inequality, not a count comparison, so an equal-sized swap still counts.
- Both sides are counted the same way. Any exclusion applied to one side is
  applied to the other, and the result records the totals before and after.

## Primary outcome

Servers whose verdict differs, as a count and a percent of the comparable set,
with missed and phantom findings separately, each by severity, and the packages
carrying them.

## Secondary outcomes

1. The same comparison with both sides flattened to one version per name, to
   quantify what the superseded keying would have given on these inputs. This
   makes the keying effect a measured quantity rather than an argument.
2. The same comparison against the secondary right arm.
3. A leave-one-out over the packages carrying the differences, suppressing each
   cause together with anything downstream of it, so a single edge cannot be
   reported as a population property.

## No directional prediction

I do not predict whether the replacement figure is higher or lower than 0.8%.
The pair-keyed left side carries more versions than the flattened one, which
could add findings on either side. Writing a prediction here would invite
reading the result as confirmation.

## Gate

An independent reviewer designs the mutations. The following must hold and are
asserted in code with raises, not `assert`, because `python3 -O` strips
assertions and would leave output byte-indistinguishable from a gated run:

1. **Harness reproduction.** The same advisory join, run through the existing
   code path on `data/nested_gap_state.json`, reproduces the published
   `data/nested_gap.json` figures: 164 phantom trees, 4,442 phantom findings, 15
   missed findings, 249 trees. This gates the join, not the new comparison.
2. **Prerelease probe.** `multer@1.4.5-lts.2` is reported inside at least one
   advisory. A clean verdict for it means the prerelease flag was lost.
3. **Double-count probe.** A package carrying one advisory across two version
   ranges yields one finding, verified on a named case drawn from the snapshot.
4. **Symmetry.** Totals on both sides are computed by the same function. The
   result records both, and a comparison that reduces one side without the other
   raises.
5. **Cutoff.** No version on the right side was published after the matched
   cutoff. A tautological check that only re-reads the root version does not
   count.
6. **Check count and `__debug__`.** The result records how many gate checks ran
   and whether assertions were enabled.

## Stopping rule

The result is reported whatever it is, including a null, including a figure that
makes the published 0.8% look better than it was. If the recomputation cannot be
completed on shipping inputs, that is the finding and it is reported as one.

## Amendments

Appended below, dated, each stating what was withdrawn and why.

### Amendment one, 18 October 2026, before any verdict figure was computed

**Gate check 5 is withdrawn as written and replaced.** The check required that no
version on the right side was published after the matched cutoff. Performing it
needs a publish time for every node, which means the packument cache. That cache
lives at `/tmp/mcpres/cache` and is gone, the same temporary-path defect
`RESOLVER-NOTES.md` already records twice. The check as written cannot be run,
and a version of it that reads only the recorded cutoff string would be the
tautology the original text ruled out.

**Replacement, which is falsifiable from shipping files alone.** The matched arm
and the secondary arm differ only in cutoff. If the cutoff had no effect the two
install sets would be identical, so the gate requires them to differ on at least
one server. A later cutoff admits a superset of candidate versions, so under the
same selection rule a name's version in the October arm should be the same or
newer, never older. The gate counts names where October is newer and names where
October is older, requires the newer count to exceed the older count, and
records both. It does not require the older count to be zero: a dist-tag that
moved backward and the deprecation preference can each legitimately produce one,
and demanding zero would make the gate fail for a correct reason.

This is weaker than the withdrawn check. It is recorded as weaker rather than
presented as equivalent.

### Amendment two, 18 October 2026, after an independent adversarial review and
### before any figure from this study is reported outside the repository

An independent reviewer that did not write the code found six defects that
survive my own checking, and one that does not. Each is recorded, with what is
withdrawn.

**Secondary outcome 1 is withdrawn.** It said the flattened arm "makes the
keying effect a measured quantity rather than an argument". It does not. The
reviewer found that the two sides are flattened by different rules: the
resolution side's node list is sorted, so last-wins is the lexicographic and in
all 819 duplicated groups the semver maximum, while the deps.dev side's pair
list carries whatever order the API returned, unsorted on 176 of 249 servers.
I ran all four tie-break combinations. The flattened comparison gives 0.8%,
2.4%, 4.0% and 5.6% depending on which side keeps which copy, with phantom
findings ranging from zero to eighteen. The flattened comparison is therefore
**not identified**, and no point estimate from it will be quoted. The range is
reported instead, and it is close to the 0.4% to 5.2% range the 8 September
note gave before a point estimate replaced it. That note was right to refuse a
number and I was wrong to supply one.

**Gate check 3 is withdrawn as written.** `vids` returns a frozenset and the
probe counted matching ids in it, so the count was bounded at one for every
possible input and the check could not fail. The case it selected was also
degenerate: `ghost` at `0.0.0`, a version mined out of a `>=0.0.0` lower bound,
and the advisory's two "ranges" are the same string twice. Replaced with a probe
that compares a row-counting join against the deduplicated join on a case with
two **distinct** ranges containing one version, and requires the row count to
exceed the deduplicated count of one. That can fail.

**Gate check 4 is withdrawn as written.** It compared `primary["servers"]`
against `flat["servers"]`, both of which are the length of the same list object,
so it was unconditionally true. Replaced with a live self-test: a deliberately
one-sided suppression must produce a different result from the two-sided one. If
suppression leaks to one side only, that check fires.

**Secondary outcome 3 is withdrawn in part.** The protocol asked to suppress
each cause "together with anything downstream of it". The pair state carries
node sets, not edges, so downstream membership cannot be derived from shipping
files and transitive suppression is not implemented. Single-name suppression is
what is reported, labelled as such. The reviewer is also right that the
all-causes row is arithmetic rather than evidence: when every cause is
suppressed the difference must go to zero by construction. It stays in the
output as a consistency check and is not evidence of anything.

**No claim of the form "no single package carries the result" will be made.**
Suppressing `qs` alone moves the primary from two differing servers to one. One
package carries half of it, and the honest statement is that two servers differ
for two unrelated reasons.

**Two defects accepted and instrumented rather than withdrawn.** `vids`
swallowed every semver parse failure with no counter, so a quietly sparse side
could not be distinguished from a clean one; a per-side counter is added. And
the severity breakdowns were presented as a decomposition without anything
asserting they sum to the reported total; that assertion is added.

**Flag sensitivity is now recorded.** The reviewer found that gate 1 reproduces
its figures byte-identically with `include_prerelease` off and with `loose` off,
so it constrains neither flag. I checked why: `multer@1.4.5-lts.2` sits inside
eleven advisories with the flag on and zero with it off, but it appears at the
same version on both sides of both trees that contain it, so it cancels in every
set difference. The flag moves absolute totals by 22 findings and moves no
difference figure. The prerelease probe is therefore the only check constraining
that flag, which justifies it. Nothing constrains `loose`, and the result now
records the finding counts under each flag so a reader can see the size of both.

**One finding does not survive.** The reviewer reported that the two inputs
producing the primary figure are absent from the shipped data directory and that
nobody could recompute the result. They are present and git-tracked in the
release: `data/depsdev_pairs.json` and
`data/nested_gap_state_depsdev_matched.json`, along with the advisory snapshot
and the October state. The reviewer was reading the four files staged for it,
not the release tree. Its related concern that the cutoff is an unverifiable
string literal is also half answered: `data/depsdev_recompute.json` ships the
cutoff in its provenance bound to a `matched_state_sha256` that matches the
state file byte for byte. What stands is that nothing re-derives the cutoff from
the data, and that the replacement gate constrains direction without magnitude.

**How the gate is to be described.** Not as six checks. One does the work, two
were vacuous and are replaced, one was conceded weaker than what it replaced.

### Amendment three, 18 October 2026: what the gate was measured to catch

The repaired gates were written in response to review, which makes them the
least tested code in the file. Ten defects were planted one at a time and the
suite re-run on each. Recorded because a guard assumed to guard is how the
defect got in.

**Caught by a named gate, five of ten:** the real de-duplication removed from
`vids`; the severity breakdown silently dropping a class; suppression leaking to
one side; the missed and phantom assignments swapped; and the double-count probe
allowing a case whose two ranges are the same string twice.

The last of those needed a second repair. The premise check read the same local
variable the mutation corrupted, so the check meant to catch the defect was
defeated by it. It now re-derives the distinct range set from the advisory
snapshot at assert time. A guard that reads the thing it guards is not a guard.

**Two are equivalent mutants and are dropped, not reported as survivors.**
Converting `vids`'s already-deduplicated set to a list preserves distinctness.
Loosening the cutoff comparison from `>` to `>=` is unreachable at 2,040
forward moves against 3 backward.

**Two are gate-layer mutations that survive alone by construction.** Rewriting a
`require` into a tautology cannot be caught by the thing it replaces. They are
listed so the count is not overstated.

**One composite survives, and this is where self-verification stops for this
file.** Neutering the orientation probe and swapping the missed and phantom
assignments together produces a run that is green, reports plausible figures,
and has the study's central claim inverted: every missed finding relabelled
phantom. The orientation probe is the only check standing between this result
and that inversion. Two further composites, loosening the harness golden paired
with a change to the join key, go red, but by crashing rather than by a gate, so
they are recorded as caught by luck.

**Three consequences for how this is described.** The gate is five effective
checks, not the six the protocol first listed. The claim is a one-directional
missed rate, because the matched walk includes optional edges without evaluating
os/cpu constraints and auto-installs non-optional peers, so the resolution side
is close to a superset of the deps.dev side by construction. And the percent
carries little information: two events over 248 servers gives a Clopper-Pearson
95% interval of 0.10% to 2.88%, and 2/n rounds to 0.8% for every n from 236 to
266, so agreement with the superseded figure "to one decimal" required only that
the count land on two again.

### Amendment four, 18 October 2026: a second independent review, and what it broke

The repairs in Amendment two were written by the author of the defects they
repaired, so a second reviewer attacked them. It found more than the first, and
two of its findings were demonstrated by execution rather than argued.

**The population rule was never evaluated.** The protocol defines the comparable
set as servers present on both sides at the same root version.
`data/depsdev_pairs.json` carries no root-version field: its fetcher stored only
the node pairs. The check therefore tried two spellings, found neither, recorded
all 248 servers as unchecked, and admitted every one, while the result reported
an empty mismatch list from a check that had run zero times. The queried version
is recoverable, because the fetcher read its roots from
`data/resolved_trees_for_depsdev.json`. Recovered and tested: all 248 are
present and **zero disagree**, so the figure does not move. The rule is now read
from that file and enforced with a raise, so the population is checked rather
than assumed.

**Two one-line changes inverted or inflated the headline with every gate green.**
Binding the arms to `compare` in the wrong order at the call site inverted
missed and phantom, because the orientation probe builds its own dicts and
constrains the inside of the function rather than which file is bound to which
argument. Giving one side a different semver configuration inside `compare`
moved missed findings from 15 to 37 on real data. Amendment three had recorded
the first of these as a surviving composite needing two mutations; it was
reachable with one. Both are now caught by a side-binding check that recomputes
each side's total independently from the named arm and requires a match. That is
the check protocol gate 4 asked for, which neither earlier version supplied.

**The orientation probe constrained two scalars out of seven paired fields.**
Swapping the per-server counters, or the by-package accumulators, left both
totals correct and passed, printing output that contradicted itself: eight missed
findings over zero missed servers. It now checks findings, servers, by-package
and the severity sum, in both directions.

**The parse counter instruments the wrong channel.** `nodesemver` in loose mode
does not raise on a malformed range. `satisfies("1.2.3", ">=1.0.0 <<>> 2",
loose=True)` returns True, manufacturing a finding from a garbled string, and
the reviewer demonstrated a snapshot edit that moved missed findings from 17 to
24 while the counter stayed at zero. It raises only on an unparseable version,
and no version in this corpus is unparseable. So the zeros are a property of the
library rather than evidence that everything parsed. A structural range count is
added and labelled a count rather than a gate.

**The counter was also read a line too early.** `unparseable` ran before
`findings`, which is what fills the set lazily, so the first comparison over any
arm reported zero and later ones reported the truth. Reordered.

**The symmetry gate could abort a correct run.** It took the largest cause,
and a cause present on only one side makes a one-sided and a two-sided
suppression coincide on correct code. The shipped run survived because the
largest cause happened to be two-sided. The cause is now selected for being
two-sided, which means present in both finding sets rather than in both
breakdowns, and when none is the gate records that it could not run instead of
reporting a pass.

**A claim in Amendment two is false and is withdrawn.** It said last-wins is the
semver maximum "in all 819 duplicated groups". It is the maximum in 803 and
wrong in 16, every one a two-digit-major case: `eslint` 10.12.0 against 8.57.1,
`minimatch` 10.2.6 against 3.1.5 and 9.0.9, `emoji-regex` 10.6.0 against 8.0.0,
and others. The reviewer also found that 62 of the 819 groups hold three or four
versions, so two endpoint rules cannot reach every copy and four combinations
cannot bracket a statistic that depends on the pick. Running six rules per side
widens the span at both ends. The flattened block is relabelled: it reports four
samples, not a range, and certainly not a bound.

**The check count was inflated and the gate description was stale.** 53 of the
reported checks were two breakdown assertions inside `compare` counted once per
arm and once per leave-one-out row, so the number moved with the data rather
than with coverage. The result now reports calls made and distinct checks
separately. The description claimed the cutoff check constrains direction and
not magnitude, after a forward floor had been added, and credited one check with
all the work after three more had been added. Rewritten to say what each check
carries and what the flattening path does not have, which is any gate at all.

**The harness golden checked four figures and computed nine.** Mis-keying the
severity lookup from `(package, advisory)` to package alone turned every
severity into unknown and passed everything, because the gate threw its own
breakdowns away while the published file it checks carries them. The golden now
covers all nine, including both severity breakdowns, and all nine reproduce.

**One finding does not survive.** The reviewer reported that
`trees_with_live_findings` of 36 in `nested_gap.json` contradicts 37 computed on
the same state and 44 in the primary. The published file says 37, not 36; the
reviewer read a stale staged copy. The October arm here reports 37 over 248
against the file's 37 over 249, which is the same arm with one server excluded,
and 44 is the matched arm, a different right side.

**Where it stands after the repair.** Twelve mutations planted one at a time,
including every one the reviewer demonstrated: eleven go red through a named
gate. The survivor rewrites a `require` into a tautology on a condition that is
empty on this data, which is the gate-layer regress rather than a defect, and it
is recorded as the place self-verification stops.

The primary figure did not move across either review: 2 of 248, eight missed
findings at four high and four moderate, zero phantom.
