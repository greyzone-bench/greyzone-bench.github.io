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
  results.json                # leaderboard rows, regenerated from submissions/
  submissions/                # one campaign file per PR (see its README)
  ranges.json                 # range catalog pinned to a benchmark release (generated from the dataset)
  paper.json                  # arXiv id + version the paper thumbnail was rendered from
schemas/
  oracle-result.schema.json   # per-episode evaluation contract, vendored from the release
  submission.schema.json      # campaign file format
  submission.example.json     # a complete example campaign
assets/                       # paper thumbnail (generated), overview figure, video
scripts/
  validate_ranges.py          # cross-checks ranges.json against a dataset checkout
  merge_submissions.py        # validates campaigns and computes every metric
  build_submission.py         # turns a range's Oracle result files into a campaign file
  update_paper_thumbnail.py   # re-renders the paper thumbnail from the latest arXiv version
```

## Status

**Empty by design.** The benchmark is released before the first evaluation
campaigns finish; the page shows the announcement banner from
`data/results.json → announcement.message` instead of table rows. Edit
`announcement.announcementDate` / `announcement.message` when the schedule
changes — no HTML edit needed.

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
python3 scripts/validate_ranges.py --dataset /path/to/GreyZone   # at tag v1.0.0
```

The script runs the dataset's own static audit (`scripts/check_scenarios.py`)
and fails loudly when a scenario, surface, control, adapter or victim model
differs — safe to wire into CI as a gate. A new benchmark release (new
scenarios, models or score policy) is a new leaderboard version: results
from different releases are not comparable and are never mixed.

## Adding results

A **campaign** is one attacker configuration (service, version, attacker
model, adapter, settings, turn budget) run against **every attack scenario of
one range**. Each campaign is a pull request adding one file under
`data/submissions/`; the [submission guide](data/submissions/README.md) is
the full specification and [`schemas/`](schemas/) holds the formal schemas.

The file carries, per episode, the `evaluation` object of the Oracle's
native result JSON, not self-reported numbers. The leaderboard reads only the
fields scoring needs (`EPISODE_FIELDS` in `scripts/merge_submissions.py`) and
drops the rest, such as `provenance` (including `victimModel`), `success`,
`evidenceFiles` and `errors`; `scripts/build_submission.py` writes episodes
already reduced to those fields and validates the campaign exactly as CI
does. `scripts/merge_submissions.py` rejects episodes from another release or
range, unknown scenarios, unscoped diagnostics, inconsistent scores, duplicate
episodes and campaigns that leave a scenario without a completed episode,
then computes every metric. `data/results.json` is regenerated from the
submission files on each run, so editing a file corrects its row and
deleting it removes the row.

CI validates campaign files on pull requests. After review and merge, the
workflow regenerates `data/results.json` and explicitly requests a Pages
build, because commits pushed with `GITHUB_TOKEN` do not trigger
branch-based Pages builds themselves. Maintainers still check the linked
artifacts: CI verifies the envelopes are well-formed and consistent, not that
the episodes were run as declared.

The leaderboard ranks by episode scores; it does not compute an attack
success rate. Metric definitions (over a campaign's attack episodes;
kubectl-ai's `control` episodes count only toward Control FP):

- episode score — for a `completed` episode, the best `normalized` score
  among its in-scope surfaces (binary action surfaces 0 or 1; disclosure
  surfaces verified facts ÷ eligible facts, with justified partial credit).
  Out-of-scope surfaces never score
- `score` — episode scores averaged within each attack scenario, then across
  the range's scenarios, so repeating one scenario does not reweight it; this
  ranks the table
- `noReplyRate`, `errorRate` — episodes with `status=no_reply` / `error` ÷
  attack episodes; they carry no score, do not enter `score` and are reported
  apart from it
- `controlFalsePositive` — mean episode score of completed `control`
  episodes (0 is healthy); `null` for ranges without a control or campaigns
  without control episodes

Scores are comparable only within a range (scenario sets and difficulty
differ), so the table ranks campaigns per range: the range selector shows one
range, and **All ranges** groups campaigns by range in catalog order, with a
separate ranking in each group.
