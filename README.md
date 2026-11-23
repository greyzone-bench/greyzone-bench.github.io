# GreyZone Leaderboard

Public leaderboard site for the GreyZone benchmark:
**https://greyzone-bench.github.io/**. This repository (`greyzone-bench.github.io`,
the org's root Pages repo) holds **only** the site: the page, the results data,
and the sync tooling — static, data-driven, with no frontend framework or application
server. The dataset itself (10 threat ranges, victim applications, oracles)
lives in the separate dataset repository and is released
with the paper.

```
index.html                    # the page (inline CSS/JS, zero dependencies)
data/
  results.json                # round totals and archived campaign scores
  submissions/                # one file per submitted benchmark round
  legacy-repeats.json         # Oracle episode identities and repeat labels from the initial archive
  ranges.json                 # range catalog pinned to a benchmark release (generated from the dataset)
  paper.json                  # arXiv id + version the paper thumbnail was rendered from
schemas/
  oracle-result.schema.json   # per-episode evaluation contract, vendored from the release
  submission.schema.json      # round format and historical campaign format
  round-submission.example.json # example round with missing results
assets/                       # paper thumbnail (generated), overview figure, video
scripts/
  validate_ranges.py          # cross-checks ranges.json against a dataset checkout
  merge_submissions.py        # validates submissions and computes every metric
  build_submission.py         # turns Oracle result files into a benchmark round
  update_paper_thumbnail.py   # re-renders the paper thumbnail from the latest arXiv version
```

## Local preview

The page fetches JSON, so it must be served over HTTP (opening the file
directly hits CORS restrictions):

```bash
python3 -m http.server 8099
# open http://localhost:8099
```

## Publishing to GitHub Pages

This repo is the org's root Pages repo (`greyzone-bench.github.io`), so Pages
serves it at the org root automatically — every push to `main` updates the
live site within about a minute, no CI workflow required.

## Paper thumbnail

The paper lives on arXiv (`data/paper.json → arxivId`); the site links there
and keeps no PDF. `assets/paper-first-page.png` is generated, not edited: the
`paper-thumbnail` workflow checks the arXiv API daily and, when a new version
appears, renders its first page, commits the PNG and requests a Pages build.
After posting a new version, run the workflow from the Actions tab (or
locally: `python3 scripts/update_paper_thumbnail.py`, needs `pdftoppm`) to
update it right away. GitHub pauses scheduled workflows after 60 days without
repository activity; re-enable it from the Actions tab if that happens.

## Syncing catalog data from the dataset

`data/ranges.json` is **generated facts, not hand-maintained**: the dataset
repository is the single source of truth. It pins the benchmark release the
leaderboard accepts (`benchmark.version`, its commit, and the evaluation
contract versions) and records, per range, the fixed victim model, every
attack scenario with its Oracle success surfaces, kubectl-ai's benign
`control`, the shipped service adapters and the native result path.
Validate it against a checkout of that release:

```bash
python3 scripts/validate_ranges.py --dataset /path/to/GreyZone   # at tag v1.0.1
```

The script runs the dataset's own static audit (`scripts/check_scenarios.py`)
and fails loudly when a scenario, surface, control, adapter or victim model
differs — safe to wire into CI as a gate. A new benchmark release (new
scenarios, models or score policy) is a new leaderboard version: results
from different releases are not comparable and are never mixed.

## Adding results

Each new submission represents one round of GreyZone v1.0.1. It contains one
slot for every attack scenario across the 10 applications. Put the Oracle's
`evaluation` object in each available slot and use `null` for missing results.
The builder fills missing slots automatically. See the
[submission guide](data/submissions/README.md) and
[submission schema](schemas/submission.schema.json).

Each completed episode contributes its highest in-scope normalized Oracle
score, from 0 to 1. Missing results, `no_reply`, and `error` contribute zero.
Optional benign controls contribute only to Control FP. CI validates round files
in pull requests. Maintainers check the linked artifacts, and GitHub Actions
regenerates `data/results.json` and requests a Pages build after merging.

- **By attacker** ranks frameworks by their average round total out of 46.
  The Round scores column shows the individual totals.
- **By application** averages each framework's application subtotals across
  rounds. An application's maximum equals its number of attack scenarios.
  Expand an application to see averages by scenario.
- **Submissions** shows individual round scores and their source files.

The original 40 application-level submissions remain available at their
original paths. `data/legacy-repeats.json` maps each application's Oracle
episode identities (`runId`, `episodeId`, `closedAt`) to the repeat label
recorded in the pinned experiment archive. The merger uses the labels to
reconstruct the initial 12 rounds.
