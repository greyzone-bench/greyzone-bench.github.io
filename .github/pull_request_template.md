## Benchmark round

- Round file: `data/submissions/<round-id>.json`
- Round number for this submitter and tool (`repeat`):
- Benchmark release: `v1.0.1` (commit, if not the release commit):
- Scenarios reported out of 46:
- Attacker service, version, model and adapter:
- Attack settings (strategy, plugins) and turn limits in `budget.maxTurns.direct` and `budget.maxTurns.indirect`
- Raw Oracle result files and evidence:
- All `completed` and `no_reply` attack episodes are included: yes / no

Build the file with `scripts/build_submission.py`. Include every scenario slot.
Use the fixed victim models and leave missing results as `null`.
See [the submission guide](https://github.com/greyzone-bench/greyzone-bench.github.io/blob/main/data/submissions/README.md).
