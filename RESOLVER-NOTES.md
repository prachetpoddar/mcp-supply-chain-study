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
| fast-uri | 3.1.7 to 3.1.8 | 155 trees |
| ip-address | 10.7.0 to 10.7.2 | 152 trees |

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
