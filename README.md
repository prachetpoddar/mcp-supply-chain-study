# Keyword Frames Are Cluster Samples

Data and code for *Keyword Frames Are Cluster Samples: How a Third of an npm
Ecosystem Stayed Invisible*, a measurement study of Model Context Protocol
servers on npm. Measurements run 6 to 8 September 2026.

**Version 3.4.** The study began as a supply-chain risk comparison and became a
paper about why that comparison kept failing. Two causes: a keyword-built frame
that sampled publishers rather than packages, and a dependency resolver that was
never validated against the tool it modelled. Section 12 of the paper lists every
change across all versions. Read it first if you saw an earlier one, because
several headline figures have been withdrawn.

Paper: [`paper/mcp-frame-paper-v3.md`](paper/mcp-frame-paper-v3.md), also as
`.docx` and `.pdf`. Superseded versions ship alongside it.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22641812.svg)](https://doi.org/10.5281/zenodo.22641812)

Cite `10.5281/zenodo.22641812`. That is the concept DOI and it resolves to the
most recent archived version. The version DOIs are `22641813` for v1.0.0 and
`22664719`, which is labelled v3.3 but archives the v3.1 tree because the tag was
placed on the wrong commit.

## What it found

**A keyword frame is a cluster sample of publishers.** npm's search API orders by
score and stops near 5,000 results, so a keyword frame is a top-slice, and which
packages land in it is decided largely by who published them. Across eleven npm
keyword ecosystems, publishers are entirely in or entirely out of a co-occurring
keyword far more often than independent tagging would produce.

**The population has no single size.** `keywords:mcp-server` returns 8,249
packages and `mcp` returns 70,922, a factor of 8.6. Which one is the population
is a choice, and every rate in the study is conditional on it.

**A third of the enumerated population is machine-generated** by four scopes.
Enumeration to 95.1% does not fix the frame problem; it changes the composition
of what you are measuring, and the deeper you enumerate the more of the
population is generated.

**Nothing shows elevated supply-chain risk.** Two results are firm: MCP servers
ship license files more reliably than either control, on both the corrected and
the uncorrected rate. Single-version publication is higher than langchain's on a
coverage-matched comparison, and that one rests on the coverage correction rather
than surviving without it. The remaining rows are unresolved or favour MCP.

**The measuring instrument was wrong.** The dependency resolver had four silent
defects, each of which changed a published number, and all four fell out of the
first comparison against a real `npm install`. The corrected resolver agrees with
real installs on 99.97% of nodes, and on 100% over the 45 packages it was never
debugged against.

## Reproducing the validation figure

`data/raw_validate_oos.json`, `raw_validate_oos3.json` and
`raw_validate_installs.json` are the per-package records. The union of the first
two, de-duplicated by package, gives 75 packages and 6,144 of 6,146 nodes.
Removing the 30 packages that also appear in the third gives 45 packages and
3,790 of 3,790. Summing the arm-level totals instead double-counts the 39
packages the two runs share, which is the error revision 3.1 corrects.

## Withdrawn figures

Several numbers in earlier versions had no artifact behind them and are withdrawn
rather than restated: the pre-correction resolver agreement rate, the per-scope
name-duplication column, and the original Docker catalog statistics. Where a
measurement could be redone it was, and the replacement ships with it
(`bulk_name_collisions.json`, `bulk_burst_recovered.json`,
`docker_pulls_recovered.json`). Section 12 records each one.

## Layout

- `paper/` the current paper and its superseded versions
- `data/` every result file, including both invalidated runs
- `code/` the measurement scripts and the release assembler
- `MANIFEST.md` SHA-256 of every released file
