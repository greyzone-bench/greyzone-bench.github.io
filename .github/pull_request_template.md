## Evaluation campaign

- Campaign file: `data/submissions/<campaign-id>.json`
- Benchmark release: `v1.0.1` (commit, if not the release commit):
- Range and attack scenarios run: all of `<range>` (repeats per scenario:)
- Attacker service, version, model and adapter:
- Attack settings (strategy, plugins) and turn limits in `budget.maxTurns.direct` and `budget.maxTurns.indirect`
- Raw Oracle result files and evidence:
- All `completed` and `no_reply` attack episodes are included: yes / no

Build the file with `scripts/build_submission.py`; the leaderboard computes
every metric from the episode envelopes. Use the range's fixed victim model.
See [the submission guide](https://github.com/greyzone-bench/greyzone-bench.github.io/blob/main/data/submissions/README.md).
