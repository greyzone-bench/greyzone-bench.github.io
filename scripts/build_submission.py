#!/usr/bin/env python3
"""Build a campaign submission from a range's Oracle result files.

Reads every result file under the given paths (files, or directories searched
recursively for result*.json), takes its native `evaluation` object and keeps
only the fields scoring needs (provenance, evidence lists and the like are
dropped). Files that are not benchmark results (no envelope, or unscoped
diagnostics) and repeated copies of one episode are skipped. Pass
`--omit-errors` to leave out episodes with status `error`. The campaign is
then validated exactly as CI does, its leaderboard row printed and the
campaign file written.
Result locations per range are listed in data/ranges.json (`resultPath`).

Example, after running every Clawith scenario with the Promptfoo adapter:
    python3 scripts/build_submission.py --range Clawith \\
        --results ../GreyZone/Clawith/.run/oracle \\
        --framework promptfoo --framework-version 0.122.2 --adapter official \\
        --attacker-model glm-4.7 --max-turns-direct 5 --max-turns-indirect 10 \\
        --settings "crescendo, policy plugin" \\
        --submitted-by your-lab --artifacts https://example.org/your-lab/clawith \\
        --out data/submissions/your-lab-promptfoo-clawith-2026-12-01.json
"""

import argparse
from datetime import date
import json
import sys
from pathlib import Path

import merge_submissions as board


def envelopes(paths, *, omit_errors=False):
    files = []
    for path in map(Path, paths):
        files += sorted(path.rglob("result*.json")) if path.is_dir() else [path]
    found, seen = [], set()
    for path in files:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"{path}: cannot read JSON ({error})")
        episode = data.get("evaluation") if isinstance(data, dict) else None
        if not isinstance(episode, dict):
            print(f"  skip {path}: no evaluation envelope (pre-contract result)")
            continue
        status = episode.get("status")
        if status == "unscoped":
            print(f"  skip {path}: unscoped diagnostics")
            continue
        if omit_errors and status == "error":
            print(f"  skip {path}: error episode omitted by --omit-errors")
            continue
        key = (episode.get("runId"), episode.get("episodeId"), episode.get("closedAt"))
        if key in seen:
            print(f"  skip {path}: repeats an episode already collected")
            continue
        seen.add(key)
        found.append(board.episode_record(episode))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--range", required=True, choices=sorted(board.RANGES), help="victim range directory")
    ap.add_argument("--results", required=True, nargs="+", help="result files or directories")
    ap.add_argument("--omit-errors", action="store_true", help="omit episodes with status error")
    ap.add_argument("--framework", required=True, help="red-teaming service, e.g. promptfoo, pyrit, deepteam, dreadnode")
    ap.add_argument("--framework-version", required=True)
    ap.add_argument("--adapter", required=True, choices=sorted(board.ADAPTER_KINDS),
                    help="official: the adapter shipped under <range>/redteam/<framework>; custom: your own MCP integration")
    ap.add_argument("--attacker-model", required=True)
    ap.add_argument("--settings", help="short description of strategy, plugins and other attacker settings")
    ap.add_argument("--max-turns-direct", type=int, help="attack-message budget per direct-injection episode")
    ap.add_argument("--max-turns-indirect", type=int, help="attack-message budget per indirect-injection episode")
    ap.add_argument("--max-turns", type=int, help="shared budget for both injection types")
    ap.add_argument("--submitted-by", required=True)
    ap.add_argument("--artifacts", required=True, help="public URL of the raw result files and evidence")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out", required=True, type=Path, help="data/submissions/<campaign-id>.json")
    args = ap.parse_args()

    direct, indirect = args.max_turns_direct, args.max_turns_indirect
    if args.max_turns is not None:
        if direct is not None or indirect is not None:
            ap.error("--max-turns cannot be combined with the direct or indirect budget flags")
        direct = indirect = args.max_turns
    elif direct is None or indirect is None:
        ap.error("provide both --max-turns-direct and --max-turns-indirect, or a shared --max-turns")

    attacker = {"framework": args.framework, "frameworkVersion": args.framework_version,
                "model": args.attacker_model, "adapter": args.adapter}
    if args.settings:
        attacker["settings"] = args.settings
    doc = {
        "submissionVersion": board.SUBMISSION_VERSION,
        "benchmark": {"version": board.BENCHMARK["version"]},
        "attacker": attacker,
        "victim": {"range": args.range},
        "budget": {"maxTurns": {"direct": direct, "indirect": indirect}},
        "submittedBy": args.submitted_by,
        "date": args.date,
        "artifacts": args.artifacts,
        "episodes": envelopes(args.results, omit_errors=args.omit_errors),
    }
    sub_id = args.out.stem
    board.validate(sub_id, doc)
    row = board.campaign_row(sub_id, doc)
    print(json.dumps(row["metrics"], indent=2))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out} — {len(doc['episodes'])} episode(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
