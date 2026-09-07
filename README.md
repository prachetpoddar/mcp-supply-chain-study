# Measuring the MCP Supply Chain

Data and code for *No Elevated Risk on the Dimensions a Registry Exposes, and
a Population That Is Not the Population*, a measurement study of supply-chain risk in Model Context Protocol
servers. Measurements run 6 to 7 September 2026.

**Version 1.0.2** enumerates 95.1% of the npm population instead of the 63.8%
a search frame reaches, which turns four identification bounds into findings and
shows that one previously reported null was an artifact of the frame. Sections
11 and 12 of the paper list every change since 1.0.0. Read those first if you
saw an earlier version.

Paper: [`paper/mcp-supply-chain-nulls.md`](paper/mcp-supply-chain-nulls.md), also as `.docx` and `.pdf` in the same folder.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22641813.svg)](https://doi.org/10.5281/zenodo.22641813)

## What it found

Eight dimensions tested against coverage-matched, size-adjusted and
age-adjusted controls, across 250 npm-distributed servers, 2,868 transitive
dependencies, 400 published packages, 247 PyPI-distributed servers and the
328-entry Docker MCP catalog.

**No dimension shows elevated risk.** At 95.1% enumeration of the npm
population, MCP servers ship license files more reliably than either control
(23.5% absent against 36.4% and 50.0%), carry deprecated dependencies no more
often, and are a strict null on install-script execution. Identification bounds
on the unreached 4.9% do not reach the control values, so these hold whatever
that remainder contains.

**Enumeration changed one result.** Single-version publication, called a null in
earlier versions, is 45.2% against langchain's 21.2%. Nearly half the published
population published exactly once. The frame bias is metric-specific: publishing
behaviour moved by up to 20 points, dependency-tree properties by less than one.

**The eighth survived every control and then dissolved.** PyPI-distributed
servers carry no license metadata at 32.8% against an age-matched PyPI baseline
of 18.0%, a risk ratio of 1.8 with a Mantel-Haenszel odds ratio of 2.45,
z = +3.78.
Weighted by actual downloads that rate is 1.9%, a sixteen-fold collapse.

**The result that governs the rest is concentration.** PyPI downloads have a
Gini coefficient of 0.9611 and one package takes 63.6% of installs. The
published population and the installed population are almost disjoint, so
per-package rates describe software that is measured but not run. Docker's
curated catalog, measured the same way, has a Gini of 0.7094 and a top item at
11.4%, which suggests the tail is a property of open publication rather than of
MCP.

## Layout

```
paper/   the writeup
data/    every measurement, as JSON, including the runs that turned out invalid
code/    the scripts that produced it
```

## Reproducing

Python 3.11 or later. The only third-party dependency is `nodesemver`, used to
apply npm range semantics rather than taking `latest`.

```
pip install nodesemver
cd code
python3 mcp_study_v2_runners.py     # the main round
python3 mcp_controls.py             # control arms
python3 mcp_confound_tests.py       # coverage-matched frames, age stratification
python3 RUN_A_pypi_weighting.py     # download weighting
python3 docker_pulls.py ../data/docker_mcp_names.json
```

Everything hits public registry APIs only. No credentials are needed. The
resolver rate-limits itself and caches to disk, so a rerun is cheap.

## Three mistakes documented here on purpose

**The npm search frame trap.** npm's search API orders by score and stops
paginating near 5,000 results. Any frame built from it is a top-slice.
Comparing top-slices drawn from populations of different sizes produced z =
7.32 for an effect that does not exist: `keywords:cli` has 104,818 packages and
we sampled the top 2.4% of it, against 64% coverage of an 8,227-package MCP
population. Four results were invalidated before this was caught. Match
coverage fractions, or use a source that enumerates completely.

**Silently ignored query parameters.** Docker Hub accepts
`ordering=-pull_count` and ignores it, returning an arbitrary 100 of 245
repositories. The output looked plausible until three things gave it away: the
top five differed from each other by 1.7%, the Gini was 0.16 where a power law
was expected, and `fetch` at 1.7M pulls was absent entirely. Verify that an
ordering parameter took effect before building anything on it.

**Fixing a sampling error in one place and not the others.** Version 1.0.0 of
this paper identified the search-frame trap, rebuilt three rows of its main
table on coverage-matched frames, and left four rows on the invalid one while
describing the whole table as matched. Re-running those four changed two, and
one changed sign. Identifying a sampling error is not the same as removing it.

**Skipping on rate limits.** The corrected script skipped any name that
returned HTTP 429. Docker Hub began throttling partway through and 55 of 328
entries were lost, running alphabetically from `scorecard` to `zscaler`. That
block contained six of the ten largest repositories, so it was not random with
respect to the quantity being measured. Retry with backoff and save state after
every response.

Both invalid outputs are kept in `data/` rather than deleted.

## What this does not cover

License and maintenance metadata only. Not malware, not typosquatting outcomes,
not prompt injection, not tool poisoning, not runtime capability scope, which is
where most published MCP security work sits. The nulls here say nothing about
any of those.

## Licence

Code under `code/` is Apache-2.0, see [`LICENSE`](LICENSE). Data under `data/`
is CC-BY-4.0, see [`LICENSE-DATA.md`](LICENSE-DATA.md). No third-party package
source is redistributed.

## Citing

See [`CITATION.cff`](CITATION.cff).

    Poddar, P. (2026). Measuring the MCP Supply Chain: No Elevated Risk on the
    Dimensions a Registry Exposes, and a Population That Is Not the Population.
    Version 1.0.1. Zenodo.
    https://doi.org/10.5281/zenodo.22641813
