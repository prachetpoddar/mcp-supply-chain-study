# Pre-registration: can a commit-activity detector warn before a package stops?

Written 9 September 2026. The statistic, the thresholds, the eligibility rule and
the success criterion are fixed below before the collector for this study exists.

## Why this study exists, and what is contaminated

PREREGISTRATION-3 asked whether abandonment is visible in advance in a
repository's issue stream. Its answer is a power-limited negative that is a
property of the population rather than of the budget: of 456 cohort A
repositories, 180 (39%) had no issue created in the whole baseline year, the
median carried 0.083 issues per month, and only 95 met the eligibility floor
against a pre-registered requirement of 150. That study is closed. Its primary
statistic, median hours to first non-author response, was never collected and
remains untested in both directions.

This study asks a narrower and more useful question over a signal that does have
coverage. In a probe of 12 cohort A repositories, including 7 with zero issue
traffic, **every one had commits inside the window**, ranging from 3 to 146.

**Contamination, stated up front.** Before writing this document I saw window
commit totals for 12 named repositories and inter-release gap statistics for 30
named packages. Those repositories are listed at the end of this document and are
**excluded from the confirmatory sample**. No per-bin commit shape was seen for
any repository, and no comparison between arms was computed.

## The question

Not "is there a signal" but "would a detector built on it be usable". A
manufacturer choosing a component needs a rule that fires early enough to matter
and rarely enough to be worth reading. So:

> **Does a commit-rate detector flag packages before their final release, at a
> false-positive rate low enough to be usable on maintained packages?**

A negative answer is as useful as a positive one and is reported the same way.

## Cohorts, anchor and window

Unchanged from PREREGISTRATION-3 and its three amendments, and read from the
same `leadtime_cohorts.json`: cohort A is packages with no release in more than
730 days, anchored at their last release; cohort B is packages with a release
within 180 days, each taking the anchor of the case it was matched to; the unit
is the repository; both arms require the repository to predate its own window;
`DefinitelyTyped/DefinitelyTyped` is excluded by name.

Bins t-24 to t-2. **Bin t-1 is excluded permanently**, for the reason established
in the third amendment to PREREGISTRATION-3: the anchor is the last release, so
t-1 is the release month in cohort A only, and release preparation produces
exactly the activity burst that a naive reading would call a signal. Commits are
if anything more concentrated before a release than issues are.

## Measure

Commits per repository per bin, from the GitHub commits list bounded by both
`since` and `until`, binned on committer date, with:

- **merge commits excluded**, identified by more than one parent, and counted;
- **bot authors excluded**, by account type `Bot` or a login ending `[bot]`, and
  counted;
- distinct non-bot author logins per bin recorded alongside the count.

Both exclusions are counted per arm and written to the output file. The third
amendment to PREREGISTRATION-3 exists partly because a bot-exclusion field was
written, never populated, and read by nothing.

## Eligibility

A repository enters the study only if its **baseline commit rate**, the mean over
bins t-24 to t-13, is at least **1.0 commits per month**. The baseline is drawn
from the first half of the window only, so the threshold cannot be met or missed
by the behaviour the study is looking for. A repository with no baseline has
nothing to decay from and is not evidence either way.

The adequacy floor is **150 eligible repositories per arm**. If either arm falls
below it, no detector performance is reported and the study is written up as a
power-limited negative, as PREREGISTRATION-3 was.

## The detector, fixed in advance

For a repository with baseline rate `b` (mean commits per month over t-24..t-13):

> **The detector fires at bin m if the trailing three-bin mean over bins m, m+1,
> m+2 is at most 0.5 x b.**

Evaluated over m from t-12 to t-2. The **lead time** for a repository is the
largest m at which the detector fires, expressed in months before the anchor, or
zero if it never fires.

## Primary statistic

**Sensitivity at three months of lead**: the share of eligible cohort A
repositories whose detector lead time is at least 3.

Reported against **the false-positive rate**: the share of eligible cohort B
repositories for which the detector fires anywhere in t-12 to t-2. Cohort B
packages released within 180 days of the run date and are by construction
maintained, so any firing there is a false alarm.

**The detector is declared usable if and only if sensitivity is at least 0.50
while the false-positive rate is at most 0.20.** Both numbers carry a
repository-level bootstrap interval, and the finding requires the interval on
sensitivity minus false-positive rate to exclude zero.

Secondary, reported but never used to establish the finding: median lead time
among cohort A repositories that fire, the full sensitivity and false-positive
pair at thresholds 0.25 and 0.75 of baseline as a sensitivity analysis, and the
distinct-author series.

## Null conditions, fixed now

The study is **negative** if sensitivity is below 0.50, or the false-positive
rate is above 0.20, or the bootstrap interval on their difference includes zero.
A negative result is reported as the answer, not as a failed run.

The study is **withheld** if either arm has fewer than 150 eligible
repositories. In that case no sensitivity figure is published at all.

## What this cannot answer, stated before collection

**Finished is not abandoned.** A complete package that ships nothing because
nothing is wrong with it will fire this detector. `object-assign`,
`assert-plus` and `is-weakmap` are in cohort A and are finished rather than
abandoned. This study measures whether a decay is detectable, not whether the
decay means the component is unsafe to adopt. Separating those two is a distinct
question and is not addressed here.

**Commits are the maintainer's own activity.** A decline in commits before a
final release is closer to the event than a decline in community response would
be. The lead time this study measures is therefore an upper bound on how early
the maintainer's own behaviour reveals the outcome, not evidence that an outside
observer could have acted on it earlier.

**Squashed and rebased history.** Committer dates are rewritten by rebases and
by squash merges, so a repository that rewrote history will be binned on the
rewrite date. This cannot be detected from the commits list and is not corrected.

**Repository is not package.** Unchanged from PREREGISTRATION-3: a monorepo's
commits speak for everything in it.

**Survivorship.** Repositories deleted, renamed without a redirect, or too large
to page through within the cap are excluded and counted by arm, not silently
dropped.

## Excluded from the confirmatory sample, by name

Seen before this document was written, and therefore pilot data.

**Commit totals seen (12 repositories):** jonschlinkert/extend-shallow,
stephenplusplus/stream-events, gtanner/qrcode-terminal, knownasilya/cli-width,
inspect-js/is-weakmap, es-shims/String.prototype.trimStart, ljharb/object-keys,
nodejs/string_decoder, bendrucker/postgres-date, evanshortiss/env-var,
graphology/graphology, joyent/node-verror.

**Release-gap statistics seen (30 packages), recorded for a possible later
cadence study and not used here:** @phc/format, assert-plus, cli-width,
domexception, expand-template, extend-shallow, frac, is-weakmap, object-assign,
object-keys, proxy-addr, qrcode-terminal, requizzle, ssf, stream-events,
string.prototype.trimstart, stubs, triple-beam, @protobufjs/aspromise, anymatch,
asn1, bindings, env-var, es6-error, graphology-indices, koa-compose, pluralize,
postgres-date, string_decoder, verror.

---

## First amendment, 9 September 2026, before any commit data is collected

No commit data exists. The collector has been written but never run. This changes
the instrument and the primary statistic before collection, which is the only
point at which that can honestly be done.

### The detector as specified above measures commit volume, not decay

An independent review of the collector raised the possibility, and a null-world
simulation confirmed it. Under a stationary process with **no decay anywhere**,
the rule "trailing three-bin mean at most 0.5 x baseline" fires at a rate that
depends steeply on the baseline rate itself, because count noise scales as the
inverse square root of the mean:

| baseline commits/month | share eligible | P(fires) Poisson | P(fires) overdispersed |
|---|---|---|---|
| 1 | 53.5% | 0.820 | 0.944 |
| 2 | 99.8% | 0.554 | 0.766 |
| 5 | 100% | 0.163 | 0.427 |
| 8 | 100% | 0.045 | 0.225 |
| 15 | 100% | 0.002 | 0.044 |
| 30 | 100% | 0.000 | 0.002 |

Cohort A is abandoned single-package repositories and cohort B is maintained
repositories, many of them monorepos. The issue-based study measured that gap at
roughly 25x at the analysed unit. Simulating a study in which **neither arm
decays at all** and the arms differ only in volume:

| simulated world | sensitivity | false positives | verdict the code would print |
|---|---|---|---|
| A 0.5-2/mo, B 8-30/mo | 0.800 | 0.073 | **DECLARED USABLE** |
| A 1-3/mo, B 5-15/mo | 0.723 | 0.197 | **DECLARED USABLE** |
| both arms 2-8/mo | 0.407 | 0.440 | not usable |

The third row is the control: when the arms share a volume distribution the
statistic correctly returns nothing. The first two rows are pure artifact. As
originally specified this study would have published a large, clean, confident
false positive. The within-repository ratio normalises the threshold but not the
noise, so baseline size passes straight through it.

### Three further defects in the original specification, each confirmed by fixture

**The baseline and detection windows overlap.** The baseline is t-24 to t-13 and
the detector at m reads bins m, m+1, m+2, so m=12 reads t-13 and t-14 and m=11
reads t-13. A repository that is flat at 10 commits across the entire detection
window, with a two-month lull at t-13 and t-14, is assigned the maximum lead of
12. The claim above that the baseline "cannot be met or missed by the behaviour
the study is looking for" was false at the two largest m.

**The lead time is overstated by one month.** Bin t-m spans
`[anchor-30m, anchor-30(m-1))`, so its count is not known until
`anchor-30(m-1)`. A firing at m gives m-1 months of actionable warning, not m.

**The arms were scored on different events.** Sensitivity used lead >= 3 and the
false-positive rate used lead > 0, a strict superset, so the control arm was
judged more harshly than the case arm by 1 to 3 percentage points, biasing the
difference against the detector.

### Revised design

**Detection range.** m runs over t-10 to t-2 only, so that no detection window
reads a bin used by the baseline. Maximum reportable lead falls from 12 to 10.

**Lead is reported in actionable months**, defined as m-1. The three-month
sensitivity criterion therefore requires a firing at m >= 4.

**Both arms are scored on the identical event**, actionable lead >= 3.

**Eligibility gains a second condition.** In addition to a baseline of at least
1.0 commits per month, at least **4 of the 12 baseline bins must be non-zero**. A
repository with a single burst in one bin and silence for the following 23 months
passes the rate floor exactly and is then scored as a maximum-lead detection,
which is a repository that was already dead before the window opened.

**Strata, fixed now.** Repositories are stratified by baseline commit rate into
[1,2), [2,4), [4,8), [8,16), [16,inf).

**Common support is required.** A stratum enters the study only if it holds at
least 20 cohort A and 20 cohort B repositories. Cohort A repositories in
unsupported strata are excluded and counted. If fewer than 150 cohort A
repositories survive inside supported strata, the study is withheld exactly as
before. If the arms do not overlap in baseline volume at all, that is reported as
the result: the two populations are not comparable on this signal.

**The threshold is calibrated within stratum, not fixed at 0.5.** Within each
supported stratum the detector fraction is chosen from the fixed grid 0.05 to
0.95 in steps of 0.05 as the **largest** value at which the cohort B firing rate
is at most 0.10. If no grid value achieves that, the stratum is dropped and
counted. This makes the false-positive rate approximately 0.10 by construction in
every stratum, so volume can no longer produce sensitivity.

### Revised primary statistic

**Pooled sensitivity at a 10% false-positive rate**, the share of eligible cohort
A repositories in supported strata with actionable lead >= 3 at their stratum's
calibrated threshold, weighted by cohort A stratum size.

**The detector is declared usable if and only if pooled sensitivity is at least
0.50** and the bootstrap interval on sensitivity minus the realised cohort B
firing rate excludes zero. The bootstrap resamples repositories within stratum
and within arm and **re-runs the calibration on every draw**, since the threshold
is estimated from the data and a bootstrap that held it fixed would understate
the uncertainty.

**Mandatory diagnostic, published whatever the result:** the cohort B firing rate
by stratum at the calibrated threshold and at the original fixed 0.5, so a reader
can see the artifact this amendment exists to remove.

### Further limits, disclosed now

**Release automation is counted as maintainer activity.** The bot filter matches
account type `Bot` or a login ending `[bot]`. `semantic-release-bot`,
`renovate-bot`, `greenkeeper` and `travis-ci` are ordinary User accounts. A
package on semantic-release emits one commit per release, and in cohort A that
series terminates at the anchor by construction, so a thinning release cadence
produces thinning commits with no change in development. The filter is extended
to a fixed list of these logins, named in the code, and the excluded count is
reported per arm. It cannot be complete.

**Counted commits depend on merge policy.** A squash-merged pull request is a
single commit with one parent and is counted once; the same work merged
conventionally contributes every commit. Merge policy correlates with arm, and a
policy change mid-window produces a step with no change in real activity. The
share of commits whose committer is GitHub's web-flow account is reported per arm
as a proxy.

**Only today's default branch is read.** A repository that moved development to a
branch later made default is measured against a history that may not contain its
pre-anchor work.

**The bootstrap does not use the matched pairing**, because the collapse to
repositories does not preserve it, as the third amendment to PREREGISTRATION-3
established. Resampling is within stratum and within arm.

---

## Second amendment, 9 September 2026, still before any commit data is collected

The retraction recorded in the fifth amendment to PREREGISTRATION-3 identified a
mechanism that the first amendment's null-world simulation did not exercise, so
it was re-run properly against this design.

**The mechanism.** Selecting on an observed baseline pulls upper-tail draws out of
a low-median population and lower-tail draws out of a high-median one. Within the
same observed-baseline stratum, cohort A repositories therefore sit above their
true rate and cohort B repositories below theirs, so cohort A drifts down and
cohort B up for free. **Stratifying on the observed baseline does not remove
this**, because the regression depends on the population a repository was drawn
from, not only on what was observed. The first amendment's simulation drew each
arm from a handful of fixed rates rather than from populations, so it could not
have shown this.

**Re-run under a stationary null with no decay, both arms drawn from lognormal
populations:**

| simulated world | pooled sensitivity | realised control rate | difference | supported strata |
|---|---|---|---|---|
| A population median 0.3, B 3.0 | 0.147 | 0.096 | +0.051 | 1 |
| A population median 0.5, B 2.5 | 0.190 | 0.095 | +0.095 | 2 |
| both populations 1.5 | 0.100 | 0.087 | +0.013 | 3 |

The calibration holds the control rate at its 0.10 target in every case, and null
sensitivity stays between 0.10 and 0.19, far below the 0.50 criterion. The design
will not declare a detector usable from this artifact.

**But the difference statistic carries a null offset of up to +0.10** under
realistic population asymmetry, and at these sample sizes its interval would
exclude zero on the artifact alone. So:

**The binding criterion is sensitivity at or above 0.50.** The requirement that
the difference interval exclude zero is retained as a necessary condition but is
explicitly **not sufficient**, and a difference of the order of +0.10 is reported
as consistent with the null rather than as evidence. The null offset measured
above is published alongside any result.

**A diagnostic is added.** The observed-baseline distribution of each arm is
written to the output file, so a reader can see how far apart the populations are
and judge the residual regression bias for themselves.

---

## Result, 9 September 2026

**Collection.** 727 of 728 cohort repositories collected, no errors, one page-cap
exclusion. 15,118 merge commits and 16,910 bot-authored commits excluded during
counting; 4,768 commits kept whose author matched no GitHub account. Web-flow
committer share, the squash and rebase merge-policy proxy, is 0.124 in cohort A
against 0.297 in cohort B, confirming that merge policy differs by arm as the
first amendment warned.

**Eligibility.** Cohort A 67 of 456, cohort B 188 of 272. **80.7% of cohort A
repositories have a baseline below 1 commit per month**, against 26.2% of cohort
B. The coverage problem that closed PREREGISTRATION-3 is smaller here but not
gone: commits reach further into the abandoned population than issues did, and
still not far enough.

**Verdict: negative, and separately underpowered.**

Only one stratum, [1.0, 2.0) commits per month, reached the 20-per-arm minimum
in both arms, with 27 cohort A and 36 cohort B repositories. **Calibration failed
there.** The lowest control firing rate reachable anywhere on the threshold grid,
at the most conservative fraction of 0.05, is **0.556**. More than half of
maintained repositories in that stratum halve their own commit rate for three
consecutive months somewhere in t-10 to t-2. No threshold makes the rule specific
at any sensitivity. The remaining four strata were dropped for having 19, 12, 6
and 3 cohort A repositories.

The pre-registered null conditions are met twice over: the false-positive rate
cannot be brought to 0.20, let alone the calibrated 0.10, and cohort A has 67
eligible repositories against a floor of 150.

**The descriptive operating curve is reported and is not evidence of a signal.**
Pooled over all eligible repositories, ignoring strata, the best separation on
the grid is sensitivity 0.776 against a false-positive rate of 0.335 at fraction
0.10. That looks like discrimination and is not usable as such, for two reasons.
A stationary null with no decay anywhere, with population medians tuned to
reproduce the observed eligible distributions, returns separations of 0.183 to
0.275 across the same range, which is most of the observed gap. And that null is
**under-dispersed relative to the real data**: it predicts a control firing rate
of 0.295 in the [1.0, 2.0) stratum where 0.556 is observed. A null that
understates real burstiness by that much cannot be used to attribute the
residual. The honest statement is that no part of the observed separation is
established as signal.

**A reporting defect found and corrected while reading this run.** The first
version of the withheld path printed "no stratum has common support: the arms do
not overlap in baseline commit volume" whenever no stratum was usable. That was
false here: the arms overlap in [1.0, 2.0) with 27 and 36 repositories, and the
stratum was dropped because calibration failed, which is a different and more
interesting finding. Insufficient repositories in an arm and an uncalibratable
control arm are now reported as distinct outcomes with the minimum reachable
control rate printed per stratum. A second defect was corrected earlier the same
day: running `report` before `fetch` printed a full strata table and the same
common-support conclusion from a state file holding one repository, so an
incomplete collection is now a hard stop.

**What this says to the CRA question.** Commit activity is not a leading
indicator of abandonment at population scale, and the reason is not that the
signal is weak. It is that maintained open-source development is bursty enough
that a three-month halving relative to a repository's own baseline is ordinary.
Over half of maintained low-volume repositories do it. Any due-diligence rule
built on activity decay will either miss most abandonment or flag most healthy
components, and no threshold sits between those two failures.
