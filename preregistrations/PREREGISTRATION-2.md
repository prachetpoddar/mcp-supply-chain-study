# Pre-registration: unmaintained components in resolved dependency trees

Written 9 September 2026, before any of the three rows below were computed. The
first version of this study reported a figure chosen after seeing several
candidates, and the pre-registration for that study exists because of it. This
one fixes the thresholds, the population and the failure conditions in advance.

## The question, in the group's words

The OpenSSF CRA Awareness SIG recorded two related concerns on 8 September 2026.
The first, from Madalin: "the topic of having OSS projects that are not
maintained any more but still ingested". The second, unattributed, from 31
August: "certain components that do not require updates because they are 'done'.
In the CRA it says 'verify that it's be updated' but no CRA path to say
'therefore you can't use it.'"

Those are two questions. How much unmaintained software is actually ingested,
and can abandoned be told apart from finished by anyone outside the project.

## Population

The 250 resolved dependency trees released with the frame study, comprising
22,943 installed (name, version) nodes over 2,955 distinct pairs and 2,373
distinct names. Tree membership is taken as published and is NOT re-resolved,
because re-resolving against a later registry would change the corpus and the
question at the same time.

## Fixed definitions

**Stale** is measured on the age of a package's most recent release of ANY
version, not the version installed. A package whose installed version is old but
which is still publishing is maintained.

Three thresholds are reported TOGETHER in every row, and no single one is the
headline: **180 days, 365 days, 730 days**. Reporting all three is the mechanism
that prevents choosing after seeing the distribution.

**Unfixed advisory** means an OSV advisory affecting the installed version with
no `fixed` event recorded in any affected range. This is the 4.6% category from
the earlier latency work.

**Depth** is the shortest path in edges from the root package of a tree to the
node, computed by breadth-first traversal over the published node set using each
installed version's declared dependencies. Depth is per (tree, node); a node in
several trees has several depths.

**Ingestion count** is the number of the 250 trees containing a package name.

## The three rows

**Row 1, ingestion-weighted staleness.** Of the 22,943 installed nodes, what
share belong to a package that is stale at each threshold, and how many of the
250 trees contain at least one. Reported both ways because they answer different
questions: the node share is exposure, the tree share is prevalence.

**Row 2, abandoned against done.** Among stale packages, the share carrying an
unfixed advisory. A stale package with no advisory against it is consistent with
being finished. A stale package with an unfixed advisory is not.

**Row 3, depth.** Median and distribution of depth for stale nodes against fresh
nodes, at each threshold.

## Direction stated in advance

For row 3 I expect stale nodes to sit deeper than fresh ones, because that result
would join the group's concern to the top-level SBOM finding already published.
That expectation is exactly why row 3 needs the adversarial pass: a result
arriving in the direction its author wants is the condition under which this
project has previously gone wrong.

## What counts as no finding

Row 3 is null if the difference in median depth between stale and fresh nodes is
under 0.5 edges at all three thresholds, or if the direction is inconsistent
across thresholds. A null will be reported in the same words as a positive.

Row 2 is uninformative rather than null if fewer than 30 stale packages carry any
advisory at all, since the share would then rest on too few cases to state.

## Known limits, stated before the result

Release recency is a proxy for maintenance and a poor one for a package that is
genuinely complete. That is the whole difficulty the group named, and row 2 is an
attempt at a discriminator rather than a solution.

The corpus is npm and one keyword frame. It says nothing about ecosystems whose
packaging conventions differ.

Depth is computed from declared dependencies at the installed versions, so a node
reachable only through an optional or platform-specific edge may be assigned a
depth no single machine realises.

Advisory coverage is whatever OSV holds. Absence of an advisory is not evidence
of absence of a vulnerability, and the 4.6% no-fix rate is itself a floor.

---

## Amendment, 9 September 2026, written after rows 1 to 3 were computed

Recorded here rather than folded into the text above, because the distinction
between what was planned and what was added after seeing results is the only
thing that makes a pre-registration worth anything.

**Row 2 as specified failed, and the specification was not applied correctly the
first time.** The definition above says "affecting the installed version". The
first computation matched on package name, which put `colors` in the numerator on
an advisory affecting `>=1.4.1` while 1.0.3 is installed, and `rc` on three
enumerated compromised builds none of which is installed. Corrected to the
definition as written, **two** packages in the corpus carry an advisory affecting
an installed version with no fix recorded: `request` and `xlsx`. Both are stale;
no fresh package qualifies. That is below the bar this document set for calling
the row informative, so row 2 as specified returns nothing usable.

**A discriminator not in the original plan is added.** npm records a `deprecated`
flag per version. A package whose every published version carries it is not a
proxy for abandonment; it is the publisher declaring it. Thirty packages in the
corpus are in that state. This was in the packument cache from the first fetch
and went unread, and it is added now, after rows 1 to 3 were seen. It is reported
as an addition rather than as a plan.

**Row 3's reporting was incomplete.** The specification asks for the median and
the distribution; only the median was reported. The distribution is now given.
The null stands and is strengthened by it: the share of nodes at depth 5 or more
runs 23.4% stale against 10.7% fresh at 180 days and 25.9% against 11.2% at 365,
then **inverts to 14.2% against 20.5% at 730**. That is the second null condition
in this document, direction inconsistent across thresholds, firing on its own.

**A sensitivity that clears the bar is disclosed and not adopted.** Collapsing to
one observation per package name rather than per node instance gives median depth
differences of about +1.1, +1.2 and +0.8, all clearing the 0.5-edge threshold in
the expected direction. This document fixes the unit as the node instance. The
name-level figure is computed by the released code, recorded in the output under
a key that says it was not adopted, and is not the result.

**Row 1's inference is narrowed.** The claim that stale packages are ingested
more often than fresh ones does not hold as stated: the median stale package and
the median fresh package are each in exactly one tree at every threshold, and the
node-share against name-share comparison is arithmetically the same statement as
a higher mean over a distribution with a 170-fold tail. What holds is that the
heavily ingested tail is disproportionately stale, and that a bootstrap over names
puts the gap at +6.0 to +19.3 points at 180 days, +3.4 to +17.1 at 365, and
**spanning zero at 730**. The tree-count half of row 1 is withdrawn: 182 of 250
trees have more than eight dependencies and every one of those contains a stale
node, so the figure restates the tree-size distribution.
