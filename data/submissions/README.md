# Submit an evaluation campaign

**In the browser (recommended).** Click **Create submission** on the
[leaderboard](https://greyzone-bench.github.io/#submit). GitHub opens a
prefilled campaign file under `data/submissions/`; rename it, replace the
example values, then choose **Commit changes… → Propose changes → Create pull
request**. GitHub forks the repository for you and applies the pull request
template.

**With git.** Fork this repository, add one JSON file under
`data/submissions/` on a branch, push it and
[open a pull request](https://github.com/greyzone-bench/greyzone-bench.github.io/compare)
(choose **compare across forks** and select your branch).

Use a filename containing lowercase letters, digits and hyphens. It is the
campaign's stable ID; edit the same file to correct a campaign. Copy this format:

```json
{
  "attacker": { "framework": "pyrit", "model": "your-attacker-model" },
  "victim": { "range": "shopware-claude-commerce" },
  "episodes": 15,
  "asr": 0.53,
  "authenticity": 0.71,
  "controlFalsePositive": 0.0,
  "noReplyRate": 0.13,
  "submittedBy": "your-lab",
  "date": "2026-12-01",
  "artifacts": "https://example.org/your-lab/episode-artifacts"
}
```

The attacker model is your experimental configuration. The victim model is
fixed by the benchmark: submit only `victim.range`. The merger reads its model
from `data/ranges.json` and records it in the generated leaderboard row.
Supplying a different victim model fails validation. Eight ranges use
`gpt-4.1-mini-2025-04-14`; Alpaca and Shopware use
`claude-haiku-4-5-20251001`. Run the official victim configuration and include
the benchmark commit in the PR description. Non-baseline experiments require
a separate leaderboard version; existing results must not be relabeled.

Link raw Oracle episode artifacts and describe the attacker settings and
evaluation budget in the PR. Maintainers verify the evidence before merging.
CI checks the submission format and fixed-model metadata; it does not fetch
artifacts or independently recompute metrics from a link.

```bash
python3 -m unittest discover -s scripts -p test_merge_submissions.py
python3 scripts/merge_submissions.py --check
```

After an approved PR is merged, the workflow regenerates `data/results.json`
and requests a GitHub Pages build. Submit campaign files rather than editing
the generated results file.
