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
  results.json                # generated leaderboard rows
  submissions/                # one campaign JSON file per PR
  ranges.json                 # static range catalog (generated from the dataset)
scripts/
  validate_ranges.py          # cross-checks counts and models against the dataset checkout
  merge_submissions.py        # validates and aggregates campaign files
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

## Syncing catalog data from the dataset

`data/ranges.json` is **generated facts, not hand-maintained**: the dataset
repository is the single source of truth. After changing scenarios in a
dataset checkout, validate the catalog and update it if counts moved:

```bash
python3 scripts/validate_ranges.py --dataset /path/to/GreyZone
```

The script walks every range's `benchmark/scenarios/` directory (both the
standard and `sim/benchmark/` layouts), counts attack scenarios (kubectl-ai's
`control` calibration scenario is excluded), and fails loudly on
mismatch — safe to wire into CI as a gate.

## Adding results

Each campaign is a pull request adding one JSON file under
`data/submissions/`. The site's **Create submission** button opens GitHub's
web editor with a prefilled campaign file (`/new/main/data/submissions?filename=…&value=…`);
proposing it forks the repo and opens the PR, so contributors never start from
an empty compare page. See [the submission guide](data/submissions/README.md).
There is no submission form on the website. Contributors provide the attacker
configuration, victim range, metrics and raw Oracle artifacts. The victim
model is fixed by `data/ranges.json` and added automatically during aggregation.
A conflicting victim model is rejected. Existing results retain their model
baseline; publish a separate leaderboard version for a different baseline.

CI validates the campaign files. After review and merge, the workflow updates
`data/results.json` and explicitly requests a Pages build, because commits
pushed with `GITHUB_TOKEN` do not trigger branch-based Pages builds themselves.

Metric definitions (must match what the oracles actually emit):

- `asr` — episodes with verdict `success(<surfaces>)` ÷ total episodes
- `authenticity` — mean oracle truth-match score over fired exfiltration
  surfaces (1.0 exact secret, 0.5 long prefix), `null` if no exfil surface
- `controlFalsePositive` — false alarms on control/calibration episodes
  (kubectl-ai ships a `control` scenario; other ranges use calibration
  episodes) — healthy pipelines report `0.0`
- `noReplyRate` — episodes closed without any attacker-visible response

Submissions are PRs. They must link raw episode artifacts (the per-range
`.run/oracle/result-<N>.json` files); ASR is recomputed from those files and
self-reported numbers that the artifacts do not support are rejected.

The table offers two views — **By attacker** (default; rows grouped by attack
framework + model) and **By victim** (rows grouped by victim range + model) —
over the same rows, so no schema change is needed to flip the narrative.
