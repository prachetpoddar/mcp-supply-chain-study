# Pre-registration: is abandonment visible before it happens?

Written 9 September 2026, before any data was collected. Nothing in this design
has been run. The two earlier pre-registrations in this project exist because
figures were chosen after seeing candidates; this one fixes the anchor, the
cohorts, the single primary statistic and the null conditions in advance.

## The question

The OpenSSF CRA Awareness SIG's recorded concern is components "not maintained
any more but still ingested", and the unresolved half of it is that a manufacturer
has no way to tell a finished component from an abandoned one at the moment of
choosing it. A lagging flag does not help: by the time npm carries a deprecation
notice, the component is already in the tree.

So: **is there an observable signal that leads abandonment, and by how many
months?** A negative answer is as useful as a positive one, because it would mean
due diligence has only lagging indicators available to it.

## Why the anchor is the last release and not the deprecation

npm records no deprecation date. The `deprecated` field is a message string on
each version with no timestamp, and maintainers typically apply it retroactively
across the whole version history in a single command. There is nothing to count
backwards from.

The anchor is therefore **the date of the package's most recent release of any
version**, which is in the registry `time` map for every package and is the
observable moment maintenance stopped rather than the moment it was announced.

## Cohorts

**Cohort A, abandoned.** Packages in the study corpus with no release in more
than 730 days as of the run date, whose declared repository resolves to a public
GitHub repository. Expected size before repository resolution: 654.

**Cohort B, maintained.** Packages with a release within 180 days, matched to
cohort A one-to-one on decile of ingestion count, so that popularity is not doing
the work.

**Anchor for cohort B.** Each control takes the calendar anchor date of the
cohort A package it is matched to. Using "today" for controls would compare two
different periods of GitHub's own history, and activity levels on the platform
have not been constant.

## Observation window and bins

Twenty-four calendar months before the anchor, in monthly bins, indexed t-24
through t-1. Nothing after the anchor is collected, so no measurement can see
across the event.

## Measures, per package per bin

1. Issues opened.
2. Issues closed.
3. Net backlog change, opened minus closed.
4. **Median hours to first response from someone other than the issue author**,
   excluding accounts whose type is Bot or whose login ends in `[bot]`.
5. Pull requests opened.
6. Pull requests merged.

## The primary statistic, fixed in advance

Searching bins forward from t-24: **the first month k at which cohort A's median
time to first response exceeds cohort B's by a factor of two or more, and does so
for three consecutive bins.** The reported result is k, the lead time in months.

One statistic, defined before collection, so that twenty-four bins cannot be
searched after the fact for the most favourable one.

## Direction stated in advance

I expect k to exist and to fall between 6 and 12 months. That expectation is why
the primary statistic is fixed here rather than chosen later, and why this study
gets an adversarial review before any figure is reported.

## What counts as no finding

**Null** if no k satisfies the condition anywhere in the window, or if the
factor-of-two gap appears and does not persist for three bins. A null will be
reported in the same words as a positive result.

**Underpowered rather than null** if fewer than 150 cohort A packages resolve to
a repository carrying at least one issue in the window. In that case no k is
reported at all.

## Secondary measures, reported but not used to establish the finding

Backlog growth and the ratio of pull requests merged to opened, both as monthly
series with the same cohorts and bins. These are descriptive. If the primary
statistic is null, a secondary one showing separation does not rescue it, and
will be reported as a secondary observation only.

## Confounds and limits, stated before collection

**Survivorship.** Packages whose repository was deleted, made private or renamed
without a redirect drop out. Those are plausibly the most abandoned cases, so
every figure here is biased toward packages that abandoned tidily.

**Monorepos.** Issues belong to a repository, not a package. A package published
from a monorepo inherits the activity of everything else in it, which will
understate abandonment. The share of each cohort published from a repository
serving more than one corpus package is reported alongside the result.

**Bots.** A bot comment is not a maintainer response. Bot accounts are excluded
from measure 4, and the count excluded is reported.

**Transferred repositories.** GitHub redirects renamed repositories, so a package
may be measured against a repository that changed owner mid-window.

**Ingestion is not popularity.** Matching is on ingestion count within this
corpus, which is not the same as download share or general use.

**This is npm and one keyword frame**, as with everything else in this project.

---

## Amendment, 9 September 2026, after cohort construction and before any collection

No issue data has been collected. This changes the instrument, not the analysis
of a result already seen.

**The unit becomes the repository, not the package.** Cohort construction found
that cohort A's 634 packages come from 580 distinct repositories while cohort B's
615 come from only 323. The asymmetry is structural: maintained projects publish
many packages from one monorepo and abandoned ones rarely do. `opentelemetry-js`
supplies 30 control packages, `esbuild` 26, `babel` 18. Since every measure here
is an issue-stream property, counting per package would treat one repository's
activity as thirty independent observations, in the arm where it is most common.
Both arms are therefore collapsed to distinct repositories. A repository's anchor
is the latest anchor among its packages, since a repository stopped when its last
package stopped, and its ingestion count is the sum across its packages.

**One repository is excluded by name.** `DefinitelyTyped/DefinitelyTyped`
publishes tens of thousands of type stubs through a single shared issue tracker,
so its activity cannot speak for any one package in it. It contributed 19 cohort
A packages. The exclusion is by name rather than by a size threshold, because
there is exactly one repository of this scale in the corpus and a threshold would
be a knob available for tuning.

**Expected sizes after the change:** cohort A about 570 repositories, cohort B
about 320. Both remain above the 150 floor this document sets for adequacy.

**Matching quality at the package level, recorded before the collapse:** 615 of
634 cases matched, 92% of pairs with identical ingestion counts, mean absolute
difference 0.45. Ingestion distributions for the two arms agree at the median,
75th and 90th percentiles.

**A truncation counter is added.** The issue collector stops at ten pages, or a
thousand issues. Repositories that hit the cap are now flagged in the output
rather than silently returning a partial series, since the busiest repositories
are exactly the ones the cap would bite on and they sit disproportionately in the
control arm.

---

## Second amendment, 9 September 2026, after a first collection and before any analysis

Issue data has now been collected once, but no comparison has been computed and
no figure has been looked at. This corrects the instrument.

**Controls were being measured over windows in which they did not exist.** Each
control takes its case's anchor so that both arms span the same calendar period.
Cases are abandoned packages with anchors from 2011 to 2024; controls are
currently maintained packages, which are much younger. Copying a 2015 anchor onto
a repository created in 2020 asks for two years of activity from a repository
that did not exist. The first collection shows the consequence plainly: **51.4%
of control repositories had zero issues created inside their window**, median
zero, against 11.1% and median seven in the case arm. The same fault explains the
truncation asymmetry, 61 of 315 controls hitting the thousand-issue cap against 7
of 570 cases, since those are busy modern repositories whose entire history
postdates a window that closed years earlier.

**Both arms now require the repository to predate its own window.** Repository
creation dates are fetched from GitHub and a control is eligible only if its
repository existed at least 24 months before the anchor. Cases whose own
repository is younger than their window are dropped, and so are cases for which
no eligible control exists. Both counts are recorded in the cohort file by name,
not merely as totals.

**This will shrink the study, and the loss falls on old abandonment.** Anchors
before roughly 2018 are unlikely to find a currently-maintained control that
already existed 24 months earlier. 155 of 634 cases have anchors before 2018.
Reporting will state the surviving anchor range rather than presenting the result
as covering the original cohort.

**The reporting step now reads the cohort file rather than the collection cache.**
The cache accumulates across cohort revisions, so a control dropped by this
amendment would otherwise keep contributing to the series indefinitely. Reporting
from a cache rather than from the current sample is how a superseded cohort
survives into a result, and it would have happened here.

**Truncation and empty windows are now reported for each arm at analysis time**,
because the first run's most informative number was one nobody had asked for.

---

## Third amendment, 9 September 2026, after a series was printed and read

**This amendment is not like the two above it.** Those changed the instrument
before anything had been looked at. This one is written after a 24-bin series was
printed, read, and put through the project's adversarial gate. Everything below
is therefore a post-hoc revision and is labelled as such. No figure produced
before this amendment may be reported as a result of this pre-registration.

### What the printed series was, and what it was not

The primary statistic of this document is measure 4, median hours to first
response from a non-author non-bot account, and the rule fixed above finds the
first bin where cohort A's median exceeds cohort B's by a factor of two for three
consecutive bins. **Measure 4 was never collected.** The collector requested
`/repos/{owner}/{repo}/issues` and nothing else, so no comment or timeline data
exists. The primary statistic is untested, not null. The null condition written
above requires the condition to be evaluated across the window, and it was not.

The printed series was measures 1 to 3, which this document already designates
secondary and already forbids from establishing a finding. Measure 5 was computed
per bin and never reported; measure 6 was never computed.

### Three defects found by the gate, each of which alone invalidates the series

**1. The anchor is endogenous, and bin t-1 is the release month.** The anchor is
the date of the package's most recent release. Bin t-1 is therefore the thirty
days immediately before a release, for cohort A only, since cohort B's anchor is
borrowed and unrelated to anything in B's own history. Release preparation
produces exactly what was observed: against cohort A's own 23-bin baseline,
pull requests opened rose 3.4x at t-1, issues opened rose 1.8x, and items closed
rose 4.0x. Closing rising faster than opening is a maintainer clearing a tracker
to ship. The effect survives dropping the ten largest contributing repositories
(2.63 against a 0.91 baseline) and 22 repositories supply half of the excess, so
it is not one repository's sweep. **Bin t-1 is unusable in any anchored analysis
here and is removed permanently.** Bin t-2 is retained but treated as suspect.

**2. Pull requests were counted as issues.** The GitHub issues endpoint returns
pull requests. The collector detected them, stored the count, and never subtracted
it. Pull requests were 55.0% of cohort A's reported "opened" and 56.1% of cohort
B's. Closures were never decomposed at all. Bot actors were never excluded from
any measure, despite the commitment above; the `bots_excluded` field was written
as zero for every repository and read by nothing.

**3. The fetch window is unbounded above, and the cap bites one arm.** The
collector passed `since` = window start to the issues endpoint, which filters on
`updated_at` with no upper bound, then sorted ascending by creation date and
stopped at 1,000 items. For an abandoned repository the result set is roughly the
window itself; for a maintained one it includes every issue touched in the years
after the anchor. Truncation was 46 of 141 control repositories (32.6%) against
3 of 215 cases (1.4%), and the ascending sort means truncation deletes the latest
bins first. The control arm's apparent decline toward the anchor is mostly this:
-23.0% across all controls, **-7.0% among untruncated controls only**.

### A fourth defect: the matching does not survive the collapse

The first amendment collapsed both arms to repositories and summed ingestion
across each repository's packages. Matching had been done package to package on
ingestion decile. Summed ingestion after the collapse is not balanced: cases have
median 5, mean 23.1, p90 70; controls have median 8, mean 37.1, p90 168. The
92%-identical pairing recorded in the first amendment is a package-level property
that is arithmetically not inherited by the analysed unit. **No cross-arm
comparison of levels is interpretable**, and the reported control mean of about
seven opened per month is a mixture of 95 repositories at 2.4 and 46 at 20.9.

The adequacy guard also failed to operate. It printed a warning and continued
rather than withholding the series, it counted repositories without a collection
error rather than repositories carrying at least one issue in the window, and it
was never applied to cohort B, which stood at 141 repositories, below the 150
floor this document sets.

### The limit that no rebuild removes

**Only 42 of 215 case repositories carry as much as 0.5 issues per month over
t-24 to t-13.** For the remaining 173 there is no traffic in which a decay could
be observed. Abandoned npm packages are predominantly small packages whose
repositories never accumulated a user community, so an issue-stream instrument
has almost no resolution on the population this study is about. This is a
property of the population, not of the collector.

### What the study now claims, and the restricted population

The claim is narrowed, before any further collection, from "abandonment is
visible in advance" to:

> **Among packages whose repository carried a measurable issue stream, is
> abandonment visible in that stream before the last release?**

Eligibility is added to both arms: a repository enters the study only if it
recorded a mean of at least 0.5 issues opened per month, pull requests excluded,
across bins t-24 to t-13. The threshold is set on the baseline half of the window
only, so it cannot be met or missed by the behaviour the study is looking for.
The value 0.5 is chosen because it is the smallest rate at which a halving is
distinguishable from zero over a five-bin comparison window, and it is fixed here
rather than tuned later.

The adequacy floor is restated in these terms: **if either arm has fewer than 150
eligible repositories, no k is reported and the study is written up as a
power-limited negative.** On the present data the case arm has 42, so the study is
expected to fail this test, and the write-up should be prepared on that basis.

### Instrument changes, all before the next collection

1. Issues are fetched by creation date over a bounded interval rather than by
   `since`, so the result set cannot contain post-anchor activity and the cap
   cannot preferentially delete late bins. Any repository that still truncates is
   excluded rather than reported partially.
2. Pull requests are excluded from every measure, identified by the
   `pull_request` key already present in each row.
3. Bot actors are excluded and the excluded count is reported per arm, as this
   document has said since it was written.
4. Bin t-1 is dropped from every analysis.
5. Comment timelines are collected so that measure 4 exists. Until they do, no
   statement about the primary statistic is made in either direction.
6. Every reported figure carries a repository-level bootstrap interval, and any
   bin carrying a result carries a leave-one-repository-out check.
7. The surviving anchor year range is written into the output file, as the second
   amendment promised and the reporting step did not do.

### One exploratory quantity, recorded so that it cannot be presented later as planned

A within-repository ratio, each repository's mean issues over t-6 to t-2 divided
by its own mean over t-24 to t-13, was computed after the gate to test whether
anything survives the level imbalance. Cases 0.75 (n=40 untruncated), controls
0.96 (n=54); difference in medians -0.209, bootstrap interval [-0.449, -0.029]
on untruncated repositories but [-0.369, +0.061] and crossing zero on the full
set. **This statistic was invented after seeing the data, it flips on a
subsetting choice, and this document already forbids a secondary from rescuing an
untested primary. It is recorded here as exploratory and is not a finding.**

### One trade the rebuild makes, stated rather than hidden

The v1 collector hit its item cap and returned a partial series with a flag
nobody read. The v2 collector walks the issue list by `updated_at` descending
and stops at the window edge, so its result set is complete by construction, but
a repository whose history does not reach the window start within 60 pages is
**excluded entirely** rather than reported partially. That substitutes an
exclusion bias for a truncation bias. The exclusion falls on the busiest
repositories, which sit disproportionately in the control arm, exactly as the
truncation did. The difference is that every exclusion is counted by arm and
written into the output file, so the bias can be sized. A silent partial series
cannot be.

---

## Fourth amendment, 9 September 2026: this study is closed

The v2 collector completed cohort A: 456 repositories, all collected without
error or page-cap exclusion, verified against GitHub's own search counts on eight
spot checks (seven exact, the two small differences being bot-authored issues the
collector excludes by design, one rate-limited).

**95 of 456 cohort A repositories meet the eligibility floor, against a
pre-registered requirement of 150.** Per the third amendment, no k is reported
and the study is written up as a power-limited negative.

The threshold is not doing the work. Eligible counts by threshold: 276 at any
issue at all, 149 at 0.25 per month, 95 at the pre-registered 0.5, 52 at 1.0.
The floor is met only at "filed at least one issue in twelve months", where the
median qualifying repository files one issue per year and no monthly series can
be read. 180 of 456 repositories (39%) had no issue created in the entire
baseline year; the median baseline rate is 0.083 issues per month.

**The negative is a property of the population.** Abandoned npm packages are
predominantly small packages whose repositories never carried a user community,
so issue telemetry has close to no resolution on them. Controls collected to this
point sit at a median of 2.08 issues per month, roughly 25 times the case median.

The primary statistic, measure 4, was never collected and is untested in both
directions. It is not reported as null.

Work continues under PREREGISTRATION-4, which asks a narrower question over
commit activity, a signal with measured coverage on the repositories this study
could not see. That is a new pre-registration rather than a fifth amendment
here, because it fixes a new primary statistic and this document's primary
remains untested.

---

## Fifth amendment, 9 September 2026: the exploratory statistic is retracted

The third amendment recorded a within-repository ratio, each repository's mean
issues over t-6..t-2 divided by its own mean over t-24..t-13, as exploratory and
not a finding. On the completed collection it reads: cohort A median 0.771 with
95% CI [0.700, 0.857] (n=95), cohort B median 0.912 with CI [0.836, 0.973]
(n=161), difference -0.141 with CI [-0.253, -0.017], excluding zero, and a
leave-one-repository-out range of [-0.141, -0.138].

**It is an artifact of the eligibility rule and is withdrawn.**

Eligibility requires a mean of at least 0.5 issues per month over t-24..t-13,
which is the ratio's own denominator. Cohort A's population median is 0.083
issues per month, so its eligible repositories are an extreme upper-tail
selection; cohort B's is 2.08, so the same threshold barely selects at all.
Regression to the mean therefore pushes cohort A's later window down relative to
its selected baseline much harder than cohort B's.

Simulated under a stationary null with **no decay in either arm**, drawing each
arm from a population with the observed median and applying the same eligibility:

| simulated world | A | B | difference | interval |
|---|---|---|---|---|
| A population 0.083, B population 2.08 (the real ones) | 0.867 | 0.997 | -0.130 | [-0.222, -0.007] excludes zero |
| both populations 2.08 | 1.013 | 0.971 | +0.043 | crosses zero |
| both populations 0.083 | 0.880 | 0.867 | +0.013 | crosses zero |

The null reproduces the observed difference of -0.141 and its exclusion of zero.
When the two populations match, the effect disappears in both directions. Nothing
in the observed data is distinguishable from this mechanism, so the statistic is
retracted rather than reported as exploratory. Any downstream use of it falls
with it.

**The closed-issue column is also not a mean of anything.** Cohort A's closures
are dominated by single mass-close events: t-15 has a mean of 6.72 of which
`request/request` supplies 436 in one month, t-7 has 7.36 with `SheetJS/sheetjs`
at 386, and t-2 has 4.51 with `Hopding/pdf-lib` at 225. Removing the top three
contributors takes each of those bins to roughly 1.5. The series is printed as
description of a withheld study and no bin should be read as a level.

**The study's conclusion is unchanged and is the power-limited negative recorded
in the fourth amendment:** 95 eligible cohort A repositories against a floor of
150. Cohort B reached 161. The final collection completed 713 of 728
repositories with no errors and 15 page-cap exclusions, all in the control arm,
against v1's 32.6% silent truncation; 202,398 pull requests and 1,240
bot-authored items were excluded during counting.
