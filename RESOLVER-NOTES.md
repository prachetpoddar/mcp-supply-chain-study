# Resolver: the dist-tag preference, found 2026-09-11

## What was wrong

`mcplib.npm_resolve` selected, in order: an exact dist-tag name, an exact
published version, then `max_satisfying` over non-prerelease versions, then
`latest` as a last resort. npm does something else. Its rule prefers the
default dist-tag whenever that tag satisfies the requested range, and only
sorts when it does not.

The two differ whenever a version above `latest` satisfies the range.

## Confirmed against a real install, not against documentation

npm CLI 10.9.7, a clean `npm install`, reading the resulting `package-lock.json`:

| parent | declares | npm installs | this resolver produced |
|---|---|---|---|
| `array-includes@3.1.9` | `get-intrinsic ^1.3.0` | 1.3.0 | 1.3.1 |
| `koa@3.2.1` | `koa-compose ^4.1.0` | 4.1.0 | 4.2.0 |

`get-intrinsic@1.3.1` was published 2025-09-29 and the `latest` tag was never
moved off 1.3.0. `koa-compose@4.2.0` is higher than `latest` and is deprecated,
while `latest` at 4.1.0 is clean, so the resolver installed a deprecated
version exactly where npm avoids one.

## npm's own documentation is stale

The npm-pick-manifest README describes 8.0.2. The dist-tag fast path gained
`engineOk(...)`, `!mani.deprecated`, `!restricted[...]` and `!staged[...]` in
10.0.0 and the prose never followed. Measured on one synthetic packument with a
deprecated, satisfying `latest` and a clean lower version:

| bundled in | npm-pick-manifest | result |
|---|---|---|
| npm 8 | 7.0.2 | the deprecated latest |
| npm 9 | 8.0.2 | the deprecated latest |
| npm 10 | 10.0.0 | the clean lower version |
| npm 11 | 11.0.3 | the clean lower version |

Every condition npm 10 added moves npm toward the behaviour this resolver
already had, so the gap is narrower against npm 11 than against npm 9.

## The change is larger than a fast path

Skipping the fast path is not enough. When npm skips it, its sort still
prioritises, in order: not deprecated and engines satisfied; engines satisfied;
not deprecated; then higher semver. A plain `max_satisfying` fall-through gives
the wrong answer on two of the thirteen test vectors. The resolver now walks
those tiers by calling `max_satisfying` on progressively relaxed candidate
sets, which reproduces the priority order without a comparator of its own.

## Resolution is host-dependent

`engineOk` takes the running node and npm versions, so the same config, on the
same day, against the same registry, can resolve differently on a different
node. In the corpus, 1,331 of 2,288 packages declare `engines` on `latest` and
832 were resolved at `latest`. The count whose `latest` is excluded by the host
runs 730 at node 16, 391 at node 18, 218 at node 20.9, 113 at node 22 and 44 at
node 24. `NODE_VERSION` is `None` by default, which means the engines condition
is not evaluated and the resolver will disagree with npm wherever engines
decide the answer. That is recorded rather than guessed.

## Corpus footprint

Reconstructed from parent manifests, since a parent version's declared ranges
are immutable and do not need a re-walk:

- `get-intrinsic`: 19 parent edges, ranges `^1.2.4` through `^1.3.0`, present in
  160 tree-instances
- `@types/node`: 15 parent edges with `*`, `>=13.7.0`, `>=8.1.0`, 22 instances
- `koa-compose`: 2 parents, `koa@3.2.1` and `koa-router@14.0.0`
- `accepts` and `fresh` do not diverge; their ranges are major-scoped, so
  `latest` does not satisfy them and both rules agree

About 0.8% of 22,162 resolved nodes.

The deprecation axis is clean: of 2,288 packages, 38 have a deprecated
`latest`, 28 of those have every version deprecated so npm 9 and npm 11 agree
anyway, 10 have a clean alternative, and the resolver resolved to the
deprecated `latest` in none of them.

## CORRECTION to the section above, 2026-09-17

The claim that the corpus walk used the uncorrected resolver is wrong as stated,
and the paper is not in error about it. Section 1 already reports a median of 93
packages and a maximum of 618 "walked with the corrected resolver of Section
2.2", and revision 3.2 already withdraws 97 and 589 as pre-correction figures
that were left in place when Section 2.2 was rewritten.

[2026-10-06] Revision 3.6 restates Section 1 on the released walk, so the paper
now reports 94 and 619 and records where 93 and 618 came from.

The independent re-walk reproduces the paper: median 94 and maximum 619, at the
same root, `@ohos-ports/agentic-flow`, ten days of drift apart.

**The real defect is that the release ships the wrong vintage of the file.**
`release/data/walk250.jsonl` and `data/walk250.jsonl` are both the
pre-correction walk, median 96.5 and maximum 589. The corrected walk that the
paper's figures come from lived in `/tmp/mcpres`, was never copied into the
repository, and no longer exists. A reader reproducing Section 1 from the
released data recovers exactly the two numbers the paper retracted.

So of the two resolvers, `install_gap.resolve_at` is the corrected one and is
what the paper describes and what `validate_installs.py` validates.
`mcplib.npm_resolve` lacks both preferences, and the shipped `walk250.jsonl` is
its output. Both statements stand; what does not stand is the inference that the
published figures came from it.

`data/walk250_corrected_today.jsonl` now recreates the missing artifact.

## What this does and does not invalidate

The published validation figure reproduces exactly: de-duplicating the two
out-of-sample runs gives 75 usable packages with an overlap of 39, 6,144
agreeing of 6,146 npm nodes, and one disagreeing tree, `n8n-nodes-neo4j`. That
figure was true when it ran. It did not exercise this rule.

`PREFER_DIST_TAG` is `False` by default so the published corpus reproduces bit
for bit. Turning it on is a deliberate, separately reported change, and the
re-validation will state which npm major the new figure belongs to.

## Verification

`code/test_resolver_vectors.py` holds thirteen vectors whose expected answers
were produced by running npm-pick-manifest 11.0.3, not by reading it. The suite
requires the resolver to match npm with the preference on, and requires the
off path to still differ, so a flag that silently does nothing fails the test.

## Blast radius of turning the preference on

Computed by re-resolving only the affected edges, since the parent ranges are
immutable and a full re-walk would mix registry drift into the same diff.

- **162 of 250 trees change a version identity.** `get-intrinsic` 1.3.1 to
  1.3.0 in 160 trees, `@types/node` 26.5.1 to 22.20.2 in 22, `koa-compose`
  4.2.0 to 4.1.0 in 2.
- **Net change in distinct nodes across the whole corpus: -1.** The change
  substitutes versions rather than adding or removing packages, so the
  structural figures (median packages per server, maximum depth, the declared
  against materialised ratio) are unaffected.
- **No advisory verdict changes.** None of the three packages has an advisory
  on record in the OSV state file, so the frozen-against-live verdict figures
  and the phantom-against-missed split are untouched.
- **Deprecated resolved instances fall from 102 to 100**, because
  `koa-compose@4.2.0` is deprecated and `4.1.0` is not. The resolver was
  installing a deprecated version in those two trees where npm would not.

Nothing in the paper's headline numbers moves. What moves is node identity in
162 trees and one deprecation count.

## A second divergence, at the root: a bare name is a range, not a tag

`npm-package-arg` resolves `foo` to type `range` with fetchSpec `*`, and
`foo@latest` to type `tag`. The two take different paths through pick-manifest.
A range goes through the dist-tag fast path and is therefore subject to its
deprecation and engines conditions. A tag selector returns the tagged manifest
unconditionally. Measured on npm 11 with one packument:

| selector | deprecated latest | latest whose engines exclude the host |
|---|---|---|
| `latest` (tag) | returns it | returns it |
| `*` (bare `npx -y foo`) | returns the clean lower version | returns the compatible one |

`mcp_resolve` records a bare launch-config entry as `requested: "latest"` and
`npm_walk` resolves it through `s in tags`, which is the tag path. So for a
bare root whose `latest` is deprecated or engine-incompatible, the corpus
resolves a version `npx` would decline to install.

**Effect on the corpus: none at present.** Of the 250 server roots, zero have a
deprecated `latest`, and `NODE_VERSION` is `None` by default so the engines
condition is not evaluated. The issue is latent rather than active, and it is
recorded here rather than fixed in `mcplib`, so that the dist-tag change above
can be verified on its own before a second change lands.

`sbom_delta.py` resolves bare roots as `*`, because matching a real install is
that tool's entire claim.

## How often this matters for MCP server roots

Measured across all 250, fetched fresh:

- `latest` is deprecated: **0 of 250**
- `latest` declares `engines.node`: **172 of 250**
- `latest` excluded by the host, so the fast path is skipped:
  67 at node 18, 31 at node 20, 18 at node 22, 0 at node 24

Skipping the fast path only changes the outcome when some other version
satisfies. Confirmed on npm 11: where no version satisfies the host, npm falls
back to the incompatible `latest` rather than failing. So the count of roots
where `npx` installs something other than `latest` is:

| host node | roots resolving away from `latest` |
|---|---|
| 18.20.4 | 14 of 250 |
| 20.18.0 | 8 of 250 |
| 22.11.0 | 7 of 250 |
| 24.0.0 | 0 of 250 |

## The release has no dependency manifest

Found while trying to re-run the corpus walk. `mcplib` imports `nodesemver`,
which is the module provided by the PyPI package `node-semver`. That package is:

- not vendored anywhere in the repository
- not named in any README, in `INDEX.md`, or in either `CITATION.cff`
- not listed in a `requirements.txt`, `pyproject.toml`, `setup.py` or
  `environment.yml`, because none of those files exist
- not mentioned in the paper

The scripts ran with `sys.path.insert(0, "/tmp/mcpres")`, so the working copy of
`mcplib` and its environment lived in a temporary directory that no longer
exists. The consequence is that the released code, archived under a DOI, cannot
be executed by a reader, and could not be executed on the author's own machine
four days later without working out the dependency from an ImportError.

`node-semver` has fifteen published versions. The study recorded which one it
used nowhere, so a re-run can be made **rule-identical but not byte-identical**
to the original corpus. Any re-walk should state the version it used, which the
re-walk script now records in `data/rewalk_env_*.json`.

This is a larger reproducibility defect than the two-resolver split above,
because it blocks every script rather than changing one rule. A
`requirements.txt` naming `node-semver` with a pinned version, and a line in the
README saying how to run the code, would fix it.

## A defect in the time-travel path, found by the re-walk

`install_gap.resolve_at(name, spec, cutoff)` resolves a dist-tag selector under a
cutoff by taking `max_satisfying(plain, "*")`, where
`plain = [v for v in avail if "-" not in v] or avail`. The `or avail` fallback
intends to use prereleases when a package has nothing else. It cannot: `*` does
not match a prerelease, so for a package whose every version is a prerelease the
call returns `None` and the entire subtree is dropped as unresolved.

Two of the 250 roots are in that state. `@craft-ng/mcp` has exactly one
published version, `0.7.0-beta.11`; `@ohos-ports/agentic-flow` has four, latest
`2.1.2-beta.1`. Both produced empty trees in the dated re-walk, 97 nodes to 0 and
589 to 0.

**This nearly became a published result.** The first comparison reported a net
change of -1,187 nodes and the corpus maximum falling from 589 to 494. Both were
the two dead trees. The rule accounts for -501 nodes, and the maximum is
essentially unchanged at 495 to 494. A resolver correction that shrinks the
corpus by 5% is a more interesting sentence than one that shrinks it by 2%, which
is exactly why it needed checking.

Fixed by retrying with `include_prerelease=True` when the first call returns
None, counted as `tag_edges_prerelease_only`. Only the cutoff branch is touched;
`resolve_at(.., None)` takes the tag directly and never reaches it, so the
validated path is unchanged. The re-walk script no longer treats a zero-node
record as a completed tree.

## Effect of the corrected rule on the published figures

Dated re-walk against the registry as of 2026-09-07T12:24Z, all 250 trees, after
both time-travel defects below were fixed. Python 3.9.12, node-semver 0.9.1.

| | walk250 (no preference) | corrected (npm rule) |
|---|---|---|
| median packages per server | 96.5 | **93.5** |
| mean | 88.65 | 86.62 |
| p90 | 165 | 162 |
| max | 589 | 586 |
| max depth | 11 | 11 |
| total nodes | 22,162 | 21,655 |
| declared direct as a share of installed, median | 2.08% | 2.15% |
| under 10% | 234/250 | 234/250 |
| trees containing a deprecated package | 43 | 42 |

160 of 250 trees change their node set, for a net of -507 nodes.

**The declared-against-materialised headline does not move**, which is the figure
the SBOM-delta work is built on. The median packages-per-server figure moves from
97 to 93 and is the one published number this correction changes.

**The mechanism is a cascade, not a substitution.** `get-intrinsic@1.3.1`
declares three dependencies that `1.3.0` does not (`async-function`,
`generator-function`, `async-generator-function`), so taking the tagged 1.3.0
drops them and their closures. That one package accounts for most of the change:
it appears in 160 trees, and those three follow it in 159 or 160 each.

An earlier edge-level estimate put the effect at -1 node. It substituted versions
in the resolved set without following the changed dependency closures and was
wrong by 500 nodes. That is why the re-walk was run rather than trusted to
arithmetic.

Resolver counters across the full pass: 32,732 range edges, of which 25,359 took
the version tagged `latest`; 258 tag edges, 2 of them prerelease-only; 60 edges
where no non-deprecated version satisfied the range.

## The time-travel path produced two artifacts before it produced a result

The dated re-walk exists to isolate the rule change from registry drift. Twice it
produced a difference that looked like the rule and was not.

**First.** `resolve_at`'s cutoff branch resolved a dist-tag selector with
`max_satisfying(plain, "*")`, and `*` does not match a prerelease, so the two
roots that publish only prereleases resolved to nothing and their whole trees
were dropped. Reported as a net change of -1,187 nodes and a corpus maximum
falling from 589 to 494. The rule accounts for -489.

**Second.** Fixing that with `include_prerelease=True` made the branch take the
highest available prerelease rather than the tagged one.
`@ohos-ports/agentic-flow` moved from the tagged `2.1.2-beta.1` to
`2.1.2-beta.4`, and the corpus maximum rose from 589 to 604. Also not the rule.

The branch now prefers the version today's tag points at whenever that version
was published before the cutoff, falling back to the approximation otherwise.
That has the property the comparison needs: a dated run then differs from an
undated one only through the range rule, which is the thing being measured.
Counted as `tag_edges_tag_predates_cutoff`.

The general lesson is about where the fragility sits. The rule change is simple
and its effect is stable. The mechanism built to isolate it is the part that
generated two false results, both of which were larger and more interesting than
the real one. Any figure from a dated run should be checked against the undated
run before it is believed.

## Ten days of registry drift, with the resolver held fixed

The undated run resolves the same 250 roots with the same corrected rule against
today's registry rather than the registry of 2026-09-07. The difference between
the two is drift alone.

**The decomposition is exact.** Rule -507 nodes, drift +12, combined -495, and
the combined figure measured directly is -495. Nothing unaccounted for sits in
the cutoff.

| | trees changed | net nodes |
|---|---|---|
| rule change, at the original date | 160 of 250 | -507 |
| ten days of drift, resolver fixed | **184 of 250 (73.6%)** | +12 |
| both together | 185 of 250 | -495 |

**73.6% of trees resolve to a different set of packages against a registry ten
days later**, with the earlier state rebuilt from publish timestamps and both runs
made on 2026-09-17, while
the corpus barely changes size: 2,867 distinct name@version pairs become 2,882,
with 171 gone and 186 new. The churn is substitution, not growth. Among affected
trees the median is 10 nodes different, the mean 13.5, the maximum 127.

Five packages account for almost all of it:

| package | moved | in |
|---|---|---|
| zod | 4.5.4 to 4.6.5 | 164 trees |
| hono | 4.13.7 to 4.13.8 | 161 trees |
| proxy-addr | 2.0.7 to 2.0.8 | 158 trees |
| fast-uri | 3.1.7 to 3.1.8 | 156 trees |
| ip-address | 10.7.0 to 10.7.2 | 152 trees |

**Amendment, 2026-10-21.** The fast-uri row read 155 trees. Recomputed from
`walk250_corrected_asof.jsonl` and `walk250_corrected_today.jsonl`, counting trees
where `fast-uri@3.1.7` became `3.1.8`, it is 156. The extra tree is `mcpscope`, which
holds fast-uri at both 3.1.7 and 4.1.4, and both versions move. A count keyed by package
name alone, with the last version winning, gives 155 for fast-uri but 162 for zod, so the
155 did not come from one counting rule. The other four rows are unchanged at 164, 161,
158 and 152 when counted by name and version. The headline of 184 of 250 trees, 73.6%,
reproduces exactly and does not depend on this row.

This quantifies a claim the paper already makes qualitatively, that nothing in a
launch config is pinned so the resolved set can differ between cold starts. Ten
days is the measured figure and the answer is roughly three quarters of servers.

**The count does not rest on the tag-map defect.** The limitation below means the
dated run and the undated run disagree about `@types/node` and `undici-types` for
reasons that are mine rather than the registry's. Removing those two packages from
the comparison leaves 184 of 250. Removing every `@types/*` package, none of which
contains runnable code, also leaves 184, and every changed tree differs in at least
one package that executes. Derived 2026-10-06 from the two released walk files,
after the figure had already been published and cited.

**Two mechanisms make 184 a floor rather than a ceiling.** The rebuilt state cannot
see versions unpublished since 2026-09-07, and it reads current deprecation flags
rather than that date's. Both hide change rather than create it. Neither is
measured.

**One limitation this exposed, the same one a third time.** The tag map cannot be
time-travelled, so the dated run reads today's `latest`. Where today's tagged
version was published after the cutoff, the tag preference cannot apply and the
dated run falls back to the sort. `@types/node` is the visible case: the dated
run resolved 26.4.1 because the tagged 22.20.x postdates the cutoff, and the
undated run resolves 22.20.3 by taking the tag. The -507 rule figure is therefore
a lower bound on what the rule would have done at the original date, understated
wherever a tag has moved since. The direction is known and the affected set is
small, 22 trees for `@types/node` and 20 for `undici-types`.

## Which Section 6 rows the resolver touches

Only one. Of the six rows, `deprecated_in_tree` is the single row derived from
the resolved node set; the others need tarball contents or root metadata that a
walk does not carry. `data/mcp-controls-data.json` records its MCP numerator as
43 of 250, which is the pre-correction walk's figure. The corrected walk gives
42, a coverage-corrected move from 18.0% to about 17.6%, inside the reported
interval, with the verdict ("NOT SIGNIFICANT, MCP better", z -1.57) unchanged.

The control arm's 57 of 250 was walked with the same uncorrected resolver, so
both arms share the defect and the comparison between them is internally
consistent. Correcting the MCP arm alone would make it less so, not more.
Re-walking the control arm is a bounded job, 250 trees, and would be the way to
close this properly if the row ever needs to carry weight.

The file is dated 2026-09-07 03:55, eight hours before `walk250.jsonl` itself,
so the walk it read was an earlier build again. The vintages in this project were
never tracked, which is the root cause of all of this and is fixed by the
`requirements.txt`, the walk naming in the README, and the environment stamp the
re-walk script now writes.

## The frozen-versus-live advisory gap, recomputed 2026-10-09

The figure the lock spec carried, 64.8% of servers changing advisory verdict
between a tree frozen at release and a tree installed today, could not be
reproduced and should not have been quoted. Three reasons, each verified before
this re-run started.

**It was the superseded measurement.** `install_gap.py` keys each tree by package
name at one version each and gave 162 of 250. `nested_gap.py` was written to
replace exactly that, because flattening forces an arbitrary pick among duplicate
versions and the pick follows traversal order; it gave 154 of 250. The spec cited
the flat figure.

**Its two arms used different resolvers.** `final_verified.json` is stamped
2026-09-08. The dist-tag preference, the deprecation preference and both
time-travel fixes landed between 11 and 17 September, so the frozen arm came from
a `resolve_at` with two known defects and the live arm from the pre-correction
walk.

**Its inputs were on a temporary path.** The per-tree state and the advisory
snapshot both lived in `/tmp/mcpres`, which is gone, so no reader could have
checked it. The same defect as the corrected corpus walk, in a second place.

### What the re-run does differently

Both arms resolve through the same corrected resolver in one pass. State lands in
`data/nested_gap_state.json` and ships. The advisory snapshot is rebuilt from the
OSV npm export by `code/build_advisories.py` into `data/advisories_npm.json`,
which also ships, with its hash and the export's date recorded in the result. The
snapshot is GHSA only: the export carries 221,191 MAL rows, one per reported
malicious package, against 9,522 GHSA rows, and a malicious-package report is a
different object from a version-range advisory. Exclusions are counted rather
than dropped quietly.

### Two defects found in the measurement itself

**Findings were double counted.** The severity loop incremented once per matching
advisory row, and OSV emits one row per package-and-range group, so an advisory
covering two version ranges of the same package counted twice. On this snapshot
that inflated the phantom count from 4,442 to 6,791. Every finding count this
file published before today carries the same inflation, including 3,768. The
tree-level rates come from set differences and were never affected.

**Prereleases evaded every range.** `>=0.0.0` does not match `1.4.5-lts.2`, so
`multer@1.4.5-lts.2` was reported clean while sitting inside 11 advisories. The
join now passes `include_prerelease=True`, which moved one tree from frozen-only
to both-arms-flagged.

### The result, 249 trees, one root skipped on a registry 404

| | count | of 249 |
|---|---|---|
| frozen description flags it, clean when installed | **130** | **52.2%** |
| flagged when installed, clean in the frozen description | **0** | 0% |
| both flag it (advisory lists differ in 34, identical in 3) | 37 | 14.9% |
| neither flags it | 82 | 32.9% |
| advisory list differs at all | 164 | 65.9% |

62 of the 249 trees have no dependencies and cannot differ; among trees with any
dependency the list differs for 87.7%.

The zero is the strongest line in the table. Across 249 trees there is no case
where installing finds something the frozen description missed at the tree level,
which is the asymmetry the lock format's `capturedUtc` field exists to expose.

**Counts of individual findings are not a stable quantity and are not quoted in
the spec.** 4,442 phantom findings against 15 missed, but 56 packages carry them
and five hold 82%, with `hono` alone at 2,017 across 130 trees: it has 50
advisories, 40 of the form `>=0.0.0 <X`, so one version move yields up to thirty
findings. In (tree, package) pairs the same data reads 906 against 3. The missed
side is two trees, 13 of its 15 findings from `@xmldom/xmldom` moving from 0.8.13
to 0.9.10, where the newer release line carried more open advisories than the
maintained 0.8.x head, which is the one counter-mechanism observed.

Because the count is concentrated, the obvious question is whether the *rate* is
too. `code/gap_leave_one_out.py` rebuilds the crosstab with packages suppressed
from the advisory join on both arms, and reproduces the unsuppressed crosstab
(130 / 0 / 37 / 82) exactly before changing anything. Suppressing `hono`
entirely moves the frozen-flags-live-clean count from 130 of 249 to 129, a rate
of 51.8% against 52.2%; adding `@hono/node-server` changes nothing further. So
the package that carries 45% of the findings carries one tree of the rate. The
same check over the five packages holding 82% of the findings gives 89 of 249,
35.7%, which is not a robustness result: removing `hono`, `fast-uri`, `qs`,
`axios` and `ip-address` from an npm advisory join removes much of what npm
advisories are about. It is recorded here so the favourable arm is not the only
one on the record. Output in `data/gap_leave_one_out.json`.

### Why the frozen tree over-reports

The frozen-versus-live result says a scanner reading a release-frozen tree
reports advisories the install does not. It does not say why, and the LinkedIn
post of 13 October named that as the open question: is the finding there because
the install moved past a fix, or because the advisory did not exist when the
package shipped? `PREREGISTRATION-6.md` fixes the decision rule,
`code/build_advisories.py` now carries OSV's `published` and `modified` onto
every advisory row, and `code/gap_cause_split.py` decomposes the findings.
`code/test_gap_cause_split.py` is its suite: 31 mutations, every one designed by
an independent reviewer rather than by the author, plus three harness composites
and a meta-test.

**The answer is an age effect, and the bands are not monotone.** Over every
finding the frozen tree reports, the share whose advisory postdates its root runs
90.6% at a root age of 30 days or less (n=318), 98.8% at 31 to 90 (n=666), 98.2%
at 91 to 180 (n=1,934), 99.7% at 181 to 365 (n=1,499) and 100.0% past 365
(n=221). The mechanism is non-decreasing in expectation, because a younger root
has had less time to accrue advisories against a fixed description, but the
realisation is not: the third band sits below the second, the package-cluster
intervals overlap heavily ([94.55, 99.77] against [90.43, 99.72], and the
youngest band's [28.89, 96.64] overlaps all four others), and the inversion is
carried by a handful of roots. The safe statement is the pair of endpoints. The
pooled figure, 98.4% of 4,638 findings, is age-exposure weighted and is not a
rate.

**The bands do not depend on the walk date.** The published live arm was
resolved about a month after the advisory snapshot. Re-running the decomposition
against `data/nested_gap_state_aligned.json`, whose live arm is resolved at the
snapshot instant, reproduces every band count and every band share exactly, and
the pooled 98.4% with them.

**The behavioural question is a null.** Both cells of the crosstab carry a
fix-availability condition, in opposite directions: a frozen-only finding
requires an in-range fix published after the root shipped, and a both-arms
finding requires that no in-range fix exists even today. All 66 pre-ship
findings in the both cell have `frozen_version == live_version`, so that cell
selects dependencies that have not moved at all. The cell free of either
condition, a pre-ship advisory on a pin that later became fixable, holds **10
findings of 4,638, 0.22%, across 7 servers**, of which 4 sit in the indeterminate
band rather than the stable category. Under the time-aligned arm it is 3 of 3,
all indeterminate. A frozen tree over-reports because advisories accrue against
a fixed description, not because these publishers shipped pins they could have
avoided.

**The cell that looked like a publisher result is confounded.** 58 findings
across 24 (root, package) pairs are pre-ship and still flagged today. In 7 of
those pairs, covering 19 findings, the tree installs two versions of the flagged
package, the flagged one and a strictly newer one the advisory does not cover,
so the finding cannot be attributed to a single declared pin. Which copy the
root itself declared is **not in the released data**: the walk state keeps flat
`(name, version)` sets with no edges or depth, and `nested_gap.py` states that
it does not model placement. Under the aligned arm this cell is 64 findings
across 15 servers rather than 58 across 13, so its membership is walk-date
dependent in a way the bands are not. No server is named in any reported
quantity. Output in `data/gap_cause_split.json`.

### The deps.dev bound, recomputed

`code/depsdev_delta.py` measures deps.dev's published dependency graph for each
MCP server root against a resolved tree. Its right-hand side came from
`data/resolved_trees_for_depsdev.json`, a resolution vintage predating the
resolver correction, and the maintainer of mcp-audit labelled the figure in his
own documentation as measured on 2026-09-08 and not recomputed.
`PREREGISTRATION-7.md` and `code/depsdev_recompute.py` recompute it. The left
side is never re-fetched, so every change is attributable to the right side.

**The bound survives.** The live arm was re-resolved with
`LIVE_CUTOFF=2026-09-08T01:00:00Z`, matching the deps.dev fetch window, so the
comparison is not confounded by registry churn. Raw, the corrected resolver is
identical to deps.dev's graph on 30.2% of 248 comparable servers against the
pre-correction resolver's 62.1%, which looks like the published bound
understating the divergence. It is not. One package edge produces the whole
effect, and removing it takes agreement to **79.4%**, which is better than the
pre-correction resolver managed.

**The edge.** The corrected resolver selects `get-intrinsic@1.3.0`, npm's own
`latest` tag; deps.dev and the pre-correction resolver both carry `1.3.1`. From
the packuments: `1.3.1` declares `async-function`, `async-generator-function`
and `generator-function`, and `1.3.0` declares none of them, so that one choice
produces both the version disagreement and the entire `extra_in_depsdev` class
(those three names, on 158 to 159 servers each, out of nine in the class). 128
of the 248 servers disagree on nothing else, and all 290 remaining
disagreements have deps.dev matching the pre-correction pick with none landing
on a third version. deps.dev's answer being one of the two resolvers' picks
every time is evidence it performs npm-like selection rather than reporting a
union over a range.

**One structural difference.** deps.dev's graph is one version per name by
construction, and the corrected resolution carries several versions of 817
names across 170 of the 248 servers. Counted the same way on both sides, every
`(name, version)` pair against every deps.dev node, that is 22,849 against
21,134, a gap of **8.1%**, where the pre-correction arm gives +0.2%. Those
duplicates are what the lock format's trees section can express and a deps.dev
query cannot, and they are the same structure that produced the nested older
copies in the frozen-SBOM decomposition.

**Three readings were withdrawn getting here**, recorded in amendments one to
three of the pre-registration. The first flattened multi-version names with
`setdefault` and manufactured disagreements out of list order. The second
compared across a two-day registry gap and measured churn: 412 of 413
disagreements were the corrected arm moving to a newer release. The third
reported the 30.2% as the bound understating the divergence, on a leave-one-out
that suppressed the three downstream names and left the causing edge in, so the
headline sat still and read as reassurance. The third was caught by an
adversarial review rather than by the author. Also corrected there: the
comparison of the two arms differs in four rules at once (peers, pair-keying,
BFS reuse, selection), not in the resolver alone; the instance delta had been
reported with the left side reduced on one side only; and the root-version
agreement check was tautological, since both arms read `root_version` from the
same file. It is replaced by a check that can fail, that no version selected in
the matched arm was published after the declared cutoff.

Three rounds of adversarial review are recorded in amendments two, three and
four of the pre-registration. Every arithmetic figure survived all three
unchanged. What failed each time was wording: "no fix-timing filter", "the
root's own declaration did not select the flagged version" and "mechanically
increasing in root age" were each withdrawn, the last of them visible as false
in a table this project had already printed.

### What stays open

Age dominates the counts and not the rate: at a root age of 30 days or less, 42
of 75 trees already show phantom findings with a median of 2, rising to 30 of 31
trees and a median of 53 at 181 to 365 days. Whether a phantom finding exists
because the install moved to a fixed version, or because the advisory was
published after the root shipped and no scanner would have reported it either,
cannot be separated here: `build_advisories.py` keeps no advisory publication
date. Recording that date is the one change that would turn the mechanism from an
assertion into a measurement.

Time-aligning the live arm to the export date, in
`data/nested_gap_aligned.json`, gives 123 flagged-and-clean of 249, 49.4%, still
zero the other way, and 163 of 249 differing. So the clock gap between a
2026-09-09 advisory export and a 2026-10-09 registry costs 2.8 points on the
wrong-answer rate and 0.4 on the list-difference rate. It does not control for
root age, which is the gap the age table points at.

The OSV export itself is 214MB and does not ship. `data/advisories_npm_meta.json`
records its date and what was built from it, and the builder regenerates the
snapshot from a fresh export.

## The deps.dev figures, recomputed 2026-10-18

Two figures were published that should not have been, and a third was retracted
without its sibling.

### The agreement pairing compared different left sides

`depsdev_recompute.py` excludes from the deps.dev side every package name the
resolution carries at more than one version, which is right for a single arm:
deps.dev's graph cannot express a name at two versions, so scoring it either way
is a choice rather than a measurement. But each arm used its own exclusion set,
and `tree_from_depsdev_file` hardcodes an empty one because the historical input
is already one version per name. So the historical arm lost nothing from the
deps.dev side while the matched arm lost 763 of 21,134 nodes across 170 of its
248 servers, and removal can only raise agreement.

Revision 3.15 therefore put 79.4% against 62.1% with neither figure scored on
the same node set, and the maintainer of mcp-audit had pinned that pairing in his
own documentation. `compare()` now takes an exclusion override and the result
carries `comparable_pair_one_exclusion_both_arms`, where one exclusion set is
applied to both sides of both arms. The left side as scored is 20,371 for both,
which is the only field in the pair that shows the exclusion was applied: the
agreement count can be identical with and without it, because the names removed
match on both sides of the historical arm.

The corrected pair is **79.4% against 67.7%**, so the direction of 3.15's
reading holds and its margin falls from 17.3 points to 11.7. A blunter symmetric
exclusion, every affected name removed from every server, reverses the ordering
to 94.0% against 84.3%; it is recorded and not used, because it strips names from
servers where they are single-version and removes disagreement the historical arm
genuinely has.

### The verdict figure was the retracted figure's sibling

The section above dated 2026-10-09 retracts the frozen-versus-live figure from
`results/final_verified.json` and gives three reasons. All three apply without
modification to the deps.dev figure in the same file: both sides were keyed on
package name at one version each, the arms predate the resolver corrections of
11 to 17 September, and the inputs lived in `/tmp/mcpres`, which is gone. Nobody
extended the retraction, so a hand-assembled 0.8% stayed in circulation and
ended up in a third party's documentation.

`PREREGISTRATION-8.md` and `code/verdict_recompute.py` supersede it rather than
reproducing it, which is impossible: 2 of 248 servers, 0.8%, eight missed
findings at four high and four moderate, zero phantom. The headline holds and the
finding count does not, moving from six to eight.

Nothing in `code/` wrote `final_verified.json`, and nothing wrote
`data/depsdev_pairs_result.json` either. Both were assembled by hand. Two result
files now have scripts behind them, and the earlier hand-assembled pair is
superseded rather than cited.

### What the two suites pin

Neither script had a test. `code/test_verdict_recompute.py` and
`code/test_depsdev_recompute.py` carry 31 mutations designed by three independent
reviews, 6 harness composites and 5 meta-tests, over hand-derived fixture tables
rather than the corpus, because the corpus is far from every boundary that
matters: no version in it is unparseable, no deps.dev node has an empty version
string, nothing is published at the cutoff instant, no extra class has a tie
straddling the top-three slice, and the two median conventions coincide at the
only node count the gated block uses.

Building them found four further defects in code already published. A malformed
`installed` token with no separator entered the resolution as a package named by
the empty string, inflating node and instance counts. A naive timestamp in a
packument parsed cleanly and then raised `TypeError` on a comparison sitting
outside the `try` that caught `ValueError`. The derived cause was a string
literal under a comment claiming it had been derived, with nothing checking it
still mattered. And the cutoff check returned only its violations, so a run that
compared nothing was indistinguishable from one that compared everything; it now
reports coverage behind a floor and compares 2,951 of 2,953 version timestamps
with none published after the declared cutoff, which confirms the matched arm's
date rather than assuming it.

One further repair came from the suites themselves. A check added to the
comparable pair required the four rows to score equal left sides, which fires on
correct code because suppression legitimately shrinks both sides; it now compares
the two arms at each suppression level. Its first version grouped the rows with
`endswith("suppressed")`, which puts `unsuppressed` in the same group and passed
for the wrong reason.

## The verification script verified the wrong tree, 2026-10-25

Adam Dudley read `code/verify_v316_claims.py` against the v3.16.1 tag and found
two defects. Both confirmed by execution before anything was changed.

**It could not run from a clone.** Line 39 opened
`results/final_verified.json`, an authoring-folder artifact that is
deliberately not released, so a clean checkout of the tag died there before a
single check ran. Seven further inputs were also unreachable from a clone: four
were a path-prefix problem, since the released files sit under `release/` here
and at the top level in a clone, and three read the 8 September note, which is
not released either.

So the script checked the figures in the authoring folder, not in the artifact
anyone else can obtain. "Every claim passing" was a statement about one machine.
That is the provenance problem this release was written to fix, reproduced
inside the fix, and it took a reader running the script to find it.

Repaired three ways. The superseded figure now ships as
`data/superseded_depsdev_verdict.json`, with a note on why
`results/final_verified.json` itself is not released, so a supersession can be
checked against a released file rather than an absent one. Every released read
goes through a release root that resolves to `release/` in the authoring folder
and `.` in a clone. The seven authoring-folder checks are gated and skip with a
printed reason and a count instead of stopping the run. From the authoring
folder the script now passes 115 checks; from the released file set alone it
passes 101 and names the 7 it skipped, exiting zero in both.

**A figure was attributed to the wrong arm.** A note sent outward described
72.2% as the name-keyed deps.dev side against "the corrected walk", which in
context read as the matched-date arm. The file it reads,
`data/nested_gap_state.json`, hashes to `october_state_sha256`, and
`data/verdict_recompute.json` describes that file as resolved about a month
later. It is the October arm.

The matched-arm equivalent is 66.1%. Both are now computed and named separately
in the script, because 66.1% is also what the released pair-keyed matched arm
reports, by coincidence rather than by identity: that arm excludes multi-version
names from both sides while this one keeps one version per name. Two different
reductions landing on the same rounded value is the shape that hides a mistake,
so the coincidence is pinned as its own check.

This is the third outward figure in this correspondence whose population was
not checked before it was reported, after the graph cluster of 8 September and
the 79.4% against 62.1% pairing. The first two were wrong values; this one was
a correct value under a wrong label, which is harder to catch and no better.

**One more defect, found while fixing those.** A check asserted that
`git status --porcelain` is empty. That fails whenever the author has
uncommitted work in progress, which is not the property it was written for. The
property is that no duplicate-name stray is untracked, since that is what a
later `git add -A` would sweep in. Narrowed to the `??` lines.
