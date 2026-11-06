#!/usr/bin/env python3
"""Validate data/ranges.json goal counts and fixed victim models against the dataset checkout.

The dataset repository is the single source of truth. This script walks each
range's benchmark/scenarios/ directory (both layouts: <range>/benchmark/ and
<range>/sim/benchmark/) and checks the goal count recorded in
data/ranges.json. Run it before publishing site changes; it exits non-zero on
any mismatch so it can gate CI.

Usage:
    python3 scripts/validate_ranges.py [--dataset /path/to/GreyZone]
"""

import argparse
import json
import re
import sys
from pathlib import Path

GOAL_DIR_CANDIDATES = ("benchmark/scenarios", "sim/benchmark/scenarios")


def count_goals(range_dir: Path) -> int:
    """Count attack goals for one range.

    Two layouts exist in the dataset:
      - <range>/benchmark/scenarios/<id>/scenario.json  (dir-per-scenario)
      - <range>/benchmark/scenarios/<id>.json           (flat, kubectl-ai)

    Calibration entries named `control` (kubectl-ai's false-positive check) are
    not attack goals and are excluded, matching the paper's 46-scenario count.
    """
    for rel in GOAL_DIR_CANDIDATES:
        scen = range_dir / rel
        if not scen.is_dir():
            continue
        n = 0
        for entry in sorted(scen.iterdir()):
            if entry.stem == "control":
                continue
            if entry.is_dir():
                if (entry / "scenario.json").is_file():
                    n += 1
            elif entry.suffix == ".json":
                n += 1
        return n
    return -1  # scenarios directory not found


MODEL_CONFIGS = {
    "Clawith": (".env.example", "OPENAI_MODEL"),
    "Inbox_Zero_Mail_Agent": ("apps/web/.env.example", "OPENAI_MODEL"),
    "Letta_Issue_Agent": (".env.example", "OPENAI_MODEL"),
    "ZerePy": (".env.example", "OPENAI_MODEL"),
    "agent-openai-java-banking-assistant": ("app/.env.example", "OPENAI_MODEL"),
    "commonly": ("docker/stack/.env.example", "OPENAI_MODEL"),
    "kubectl-ai": (".env.example", "OPENAI_MODEL"),
    "smart-home": ("sim/secrets.env.example", "OPENAI_MODEL"),
    "alpaca-mcp-server": ("sim/.env.example", "ANTHROPIC_MODEL"),
    "shopware-claude-commerce": (".env.example", "ANTHROPIC_MODEL"),
}


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        type=Path,
        default=here.parent.parent / "GreyZone",
        help="path to the dataset checkout (default: sibling of this repo)",
    )
    args = ap.parse_args()

    ranges_path = here.parent / "data" / "ranges.json"
    ranges = json.loads(ranges_path.read_text())["ranges"]

    failures = 0
    print(f"{'range':40} {'recorded':>8} {'found':>6}  status")
    for r in ranges:
        range_dir = args.dataset / r["dir"]
        if not range_dir.is_dir():
            print(f"{r['dir']:40} {r['goals']:>8} {'?':>6}  MISSING RANGE DIR")
            failures += 1
            continue
        relative, key = MODEL_CONFIGS[r["dir"]]
        config = range_dir / relative
        configured = re.search(rf"(?m)^{key}=([^\r\n]+)$", config.read_text()) if config.is_file() else None
        if not configured or configured[1].strip() != r.get("model"):
            print(f"{r['dir']:40} MODEL MISMATCH — compare data/ranges.json with {relative}")
            failures += 1
        found = count_goals(range_dir)
        ok = found == r["goals"]
        if not ok:
            failures += 1
        print(f"{r['dir']:40} {r['goals']:>8} {found:>6}  {'ok' if ok else 'MISMATCH'}")

    if failures:
        print(f"\n{failures} range(s) failed validation — regenerate data/ranges.json")
        return 1
    print(f"\nall {len(ranges)} ranges validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
