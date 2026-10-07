# Pre-registration: what predicts a late advisory?

Written 9 September 2026, before the collector for this study exists. The
population, the outcome, the attribute list, the expected directions, the
multiplicity correction and the adequacy floor are all fixed below.

## Why

Descriptive work on the 2,373-package MCP corpus established the anatomy and is
recorded at the end of this document. It cannot answer which systems are prone to
late announcement, because the delayed class holds 55 cases and the candidate
attributes number about ten. This study widens the population until that class is
large enough to carry a test.

## Population, and why it changes

**All npm advisories in the OSV database**, taken from the bulk export at
`osv-vulnerabilities.storage.googleapis.com/npm/all.zip`, rather than advisories
affecting one keyword-selected corpus. The corpus restriction was a selection on
packages that appear in MCP server dependency trees, which correlates with
package age, popularity and maintenance style, all of which are candidate
predictors here. Removing it removes that confound and multiplies the sample.

**Excluded, each counted and reported:** advisories with `withdrawn` set;
malicious-package entries (`MAL-` identifiers and any advisory whose only
classification is malware), which describe a package that should not exist rather
than a defect that was fixed and so have no fix event; advisories with no `fixed`
event in any range; advisories whose fixed version carries no publish timestamp
in the registry.

**Follow-up requirement.** An advisory enters the analysis only if its fix version
was published at least 90 days before the run date. Without this, recent fixes
cannot exhibit the outcome and the recent cohorts are censored toward promptness.
Analyses at a 365-day horizon are computed only over fixes with 365 days of
follow-up.

## Outcome, three-way and fixed now

For each (advisory, fix version) pair, lag = advisory `published` minus registry
publish time of the fixed version.

- **advisory_first**: lag < 0. The vulnerability was public before any fix
  shipped. This is a different event and is **excluded from the predictor test**,
  reported separately as an exposure-window description.
- **prompt**: 0 <= lag <= 30 days.
- **delayed**: lag > 30 days.

**The primary test is delayed against prompt.** The 30-day boundary is taken from
the observed distribution shape in the prior work, where announcement is a cliff
rather than a slope, and is fixed here rather than chosen later.

## Attributes, and the direction expected for each

Fixed now, ten attributes, each a binary contrast. Stating the expected direction
in advance is what stops a surprising sign being narrated as a discovery.

| attribute | contrast | expected |
|---|---|---|
| severity | HIGH or CRITICAL vs lower | less delay |
| CWE class | resource-consumption (CWE-400, CWE-770, CWE-1333) vs other | more delay |
| advisory breadth | covers more than one package vs one | more delay |
| fix ambiguity | more than one candidate fix version vs one | more delay |
| popularity | weekly downloads below the population median vs above | more delay |
| namespace | scoped `@org/name` vs unscoped | less delay |
| CVE alias | absent vs present | more delay |
| curation | not `github_reviewed` vs reviewed | more delay |
| prior advisories | none before this one for that package vs some | more delay |
| package age at fix | older than five years vs newer | no direction stated |

## Estimator, and the two mistakes it is built to avoid

**Every contrast is stratified by fix year and pooled with a Mantel-Haenszel odds
ratio.** Earlier today a twentyfold apparent effect in this same data turned out
to be fix-year composition: the attribute was almost absent before 2021 and
almost universal after, and the years differ enormously in lag. No unstratified
contrast is reported as a result.

**Intervals come from a bootstrap clustered on the package**, not the advisory. A
single package can contribute many advisories, and treating them as independent
observations is the pseudo-replication that has already cost this project one
result.

**Multiplicity.** Ten contrasts, Holm correction across the family. A contrast is
reported as supported only if it survives Holm and its Mantel-Haenszel interval
excludes 1.

**Null calibration, published alongside.** The delayed label is permuted within
fix-year strata 2,000 times and the whole procedure re-run, so the reader sees
what this pipeline returns when no association exists. Any observed effect
smaller than the permutation null's spread is reported as consistent with no
association, regardless of its interval.

## Adequacy floor

**At least 300 delayed cases and at least 300 prompt cases**, and at least 30
delayed cases in each fix-year stratum used. If the delayed class falls short,
no odds ratio is published and the study is reported as descriptive only. If a
stratum falls short it is dropped and counted, not merged.

## Null conditions

The study is **negative** if no contrast survives Holm with an interval excluding
1. A negative is the answer: it would mean late announcement is not predictable
from advisory metadata, and that a service built on flagging prone components
cannot be targeted from the advisory record alone.

## Limits, stated before collection

**No advisory links to its own fix.** Across 703 advisories examined in the prior
work, not one carried a `FIX`-typed reference, although the OSV schema defines
one. Reference types were WEB 3,112, ADVISORY 689, PACKAGE 588, ARTICLE 2. Every
lag here is therefore reconstructed by matching the advisory's `fixed` version
string against the registry `time` map. Where an advisory names a fix version
that was later unpublished, or names a range rather than a version, the pair
drops out and is counted.

**The registry clock is the publish clock.** npm `time` entries can be rewritten
by unpublish and republish. There is no way to detect this from the registry.

**Announcement is not remediation.** This study measures when a defect was
announced relative to when its fix became installable. It says nothing about when
downstream consumers upgraded.

**Conditional on an advisory existing.** Every pair here has an advisory by
construction. Fixes that shipped and were never announced at all are invisible to
this design, and they are the population a detector would most want. That is a
separate study and is not attempted here.

---

## Prior descriptive work, recorded so it cannot be re-presented as planned

Computed on the 2,373-package MCP corpus, 703 pairs, before this document existed.
Descriptive, and superseded by whatever this study returns.

Pipeline segments: fix to NVD published, median 3.0 days; NVD to GHSA published,
median 0.1 days; GitHub review to publication, median 0.0 days. No step is slow.

Modern cohort, fixes from 2021 with 90 or more days of follow-up, n=438:
advisory_first 12.1% (median 6 days, p90 96 days of public exposure with no
remedy), prompt 75.3%, delayed 12.6% (median 77 days, p90 304, max 783).

Shape of the wait in that cohort: 32.2% on or before the fix day, 34.0% within a
week, 21.2% within a month, 6.8% at 31 to 90 days, 5.5% at 91 to 365, 0.2% beyond
a year.

Announced within 365 days by fix-year cohort, computed only where a full year of
follow-up exists: 0.000 for 2013 to 2015, 0.588 in 2017, 0.615 in 2018, 0.571 in
2019, 0.588 in 2020, 0.837 in 2021, 0.839 in 2022, 0.808 in 2023, 0.816 in 2024.

**A retracted reading, recorded as a warning.** Advisories lacking an
`nvd_published_at` timestamp showed a median lag of 85.9 days against 4.4 days
for those carrying one. This was read as evidence that the CVE pipeline is what
makes announcement fast. It is composition: the field is present on 17 to 30% of
pre-2021 advisories and 83 to 98% of later ones, and the years differ in lag by
two orders of magnitude. Within 2022, 2025 and 2026, where both cells are
populated, the contrast is approximately zero. This is why every contrast in the
present study is stratified by fix year.

## Amendment one, 2026-10-07: measurement corrections found by review before any result was written

The collection had run and `data/cra_advisory_delay.json` existed. Before the
result section was written, the estimator went through an independent adversarial
review. The Mantel-Haenszel pooling, the Holm step-down and the outcome
classification were checked against their definitions and are correct, and I
verified that myself rather than taking it on report. Ten other defects came
back. Every change below is a correction to measurement or to what gets recorded.
No hypothesis, no expected direction and no threshold changes, and the
verdict rule is untouched.

1. **Unit.** This protocol fixes (advisory, fix version) pairs. The code built one
row per (advisory, package) and collapsed the candidate versions with `min()`,
which takes the earliest publish time and therefore maximises the lag. Rebuilt to
one row per (advisory, fix version), as written here.

2. **`multi_package` measured the wrong thing.** It read the length of OSV's
`affected` array, which carries one entry per package-and-range group and spans
every ecosystem, not only npm. 1,050 advisories of 5,500 were coded as covering
more than one package while covering exactly one npm package. The contrast is now
`len(fixes) > 1`. The old quantity stays in the record as a diagnostic and is not
a contrast.

3. **`multi_fix` shared an input with the outcome.** Exposure was
`len(versions) > 1` while the outcome came from `min()` over those same versions,
so more candidates meant an earlier fix time, a longer lag and a higher chance of
the delayed arm. The per-version unit removes the shared input. Exposure is now
whether that (advisory, package) names more than one fix version carrying a
publish timestamp, counted on resolvable timestamps rather than on names.

4. **Missing exposure is no longer the reference level.** `low_downloads` and
`old_package` coded unknown as unexposed. Rows whose exposure is unknown are now
excluded from that contrast and counted.

5. **The popularity contrast cannot be completed in either sandbox.**
`api.npmjs.org` is unreachable from both the cloud container and the desktop
workspace, while `registry.npmjs.org` is reachable from both, so 2,520 of 5,999
advisory-package pairs carry no download figure. The contrast is reported with
its coverage stated and is estimable in full only after `resolve` runs somewhere
that endpoint answers. No substitute popularity measure is swapped in.

6. **The analysis date is fixed and recorded.** The follow-up cutoff read the wall
clock, so the analysed set grew between runs of the same code: 460
insufficient-follow-up drops on 17 September became 214 on 6 October, admitting
exactly 246 pairs, all with fix dates in June and July 2026, none able to show a
delay beyond about 117 days, and all inside the 2026 stratum. That is the
censoring confound this design stratifies to avoid, reappearing inside a stratum.
`ASOF` is now a constant and is recorded in the output.

7. **The 365-day horizon analysis this protocol requires was absent from the
code.** It is added as a secondary family over fixes carrying a full year of
follow-up at `ASOF`.

8. **Everything the run prints is now recorded.** The dropped fix-year strata and
the pairs they take, the advisory-first exposure window this protocol asks for
separately, per-contrast exposure and missing counts, the per-stratum tables, the
number of estimable bootstrap resamples per contrast, the seed, the bootstrap
count, the analysis date and a hash of the code.

9. **The bootstrap shares one set of resampled package draws across contrasts**,
so the family's Monte Carlo error is common rather than independent, and the
count is raised. The two-sided bootstrap p-value uses (k+1)/(B+1) and counts a
tie once.

10. **The permutation null stays row-level, as preregistered, and is now reported
as what it is.** Shuffling labels at the row level destroys the within-package
correlation that the clustered bootstrap exists to respect, so its threshold is
narrower than the intervals printed beside it. Decisions stay on Holm over the
clustered bootstrap. This protocol's own downgrade rule is now applied, and a
disposition is recorded for every contrast, including any that exceeds the
threshold.

11. **The analysis has a test file**, `code/test_advisory_delay.py`, including the
boundary cases the `classify` docstring claims as its reason for existing.

The Holm divisor stays the number of contrasts actually estimated, and the
adjusted values at the preregistered ten are recorded alongside so a reader can
see the deviation costs nothing.

## Result, 2026-10-07

Run at `ASOF` 2026-10-07 over the OSV npm export, one row per (advisory, fix
version). 7,084 rows: 2,143 delayed, 4,629 prompt, 312 advisory-first. Dropped:
303 groups whose fix versions carry no registry publish time, 356 rows without 90
days of follow-up, and separately 31 groups that lost some but not all versions,
costing 37 versions and moving 8 groups from multiple to single. 6,750 rows enter
the main family, of which 6,470 sit in strata that inform the estimator. The
adequacy floor of 300 delayed and 300 prompt is cleared more than six times over.
Everything below comes from `data/cra_advisory_delay.json`, code SHA-256
`70ccba0bd4b5…`, seed 20260909, 100,000 bootstrap draws, 2,000 permutations.

**The pre-registered estimator does not apply to this data, and that is the
result.** Mantel-Haenszel pooling summarises a set of strata only if they share
an odds ratio. Breslow-Day rejects that for all nine estimable contrasts:
p = 2.1e-17 for advisory breadth, 1.4e-11 for the CVE alias, 4.4e-16 for
popularity, 2.9e-9 for package age, 6.8e-8 for fix ambiguity, 2.8e-4 for
namespace, 3.3e-3 for prior advisories, 5.9e-3 for severity, 2.9e-2 for the CWE
class. Not one pooled odds ratio in this family is interpretable as a single
effect. The design chose fix-year strata to remove a composition artifact that
had produced a twentyfold effect; doing that reveals that announcement behaviour
differs by fix year so much that no contrast holds a constant association across
them.

**One contrast clears the decision rule under pooling, and it is reported stratum
by stratum rather than as an effect.** An advisory naming more than one candidate
fix version: pooled 0.48, 95% CI [0.27, 0.81], bootstrap p 0.0044, Holm 0.0391 at
the nine estimated and 0.0435 at the pre-registered ten. The direction is the
opposite of the one fixed in advance. By fix year, informative strata only:

| 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| 0.51 | **1.55** | 0.55 | 0.30 | **1.18** | 0.38 | 0.12 | 0.48 | 0.49 |

Seven of nine point one way and two the other, across a thirteenfold range.
2014 to 2017 contribute no weight at all, their prompt-and-exposed cell being
empty. The right statement is that in most fix years since 2018 an advisory
naming several fix versions was announced late less often, that 2019 and 2022 run
the other way, and that no single number describes the set. Exposure defined on
named rather than resolvable versions gives 0.486 against 0.484, so the
resolvability filter does not carry it. At the 365-day horizon the same contrast
reads 0.48 [0.29, 0.74], Holm 0.0051, and the same two strata oppose it; that
family is a subset of the main one re-tested, not independent corroboration.

**Nothing else reaches the rule.** Popularity moved from 1.10 to 1.79 [1.15,
2.70], Holm 0.0663, when the split was corrected from the row median to the
package median, which is in the predicted direction and is why it gets more
scrutiny and not less: it fails homogeneity at 4.4e-16, it rests on the 62% of
rows whose package carries a download figure, and no claim is made from it. The
curation contrast is not estimable: 4 exposed rows, none of them delayed.

**The pre-registered exposure-window description.** 312 advisory-first rows,
median 11.7 days of exposure before the fix appeared, 90th percentile 326 days.

**Limits.** The exposure may mark a coordinated multi-branch release rather than
fix ambiguity, and a release patched across several lines is the kind whose
advisory is written at release time, which is close to what prompt means; the
group-level permutation that put the observed value outside a null band of
[0.81, 1.22] addresses chance, not that reading. The permutation null shuffles
labels at the row level as pre-registered, which ignores package clustering and
so runs narrower than the intervals beside it. `api.npmjs.org` is unreachable
from either sandbox, so the popularity contrast cannot be completed here. The row
builder and the reporting function are not under test, which is where a mutation
would still pass. And the fix-year strata are a year wide, so censoring inside the
most recent stratum is frozen rather than removed.

**Disposition.** Negative on the pre-registered question, with a caveat that
matters more than the answer: the family cannot be summarised the way it was
designed to be. Anyone predicting announcement delay from advisory metadata
should expect the relationship to move with the year, and should not pool.
