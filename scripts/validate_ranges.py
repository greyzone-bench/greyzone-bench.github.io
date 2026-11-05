#!/usr/bin/env python3
"""Validate data/ranges.json scenario counts against the dataset checkout.

The dataset repository is the single source of truth. This script walks each
range's benchmark/scenarios/ directory (both layouts: <range>/benchmark/ and
<range>/sim/benchmark/) and checks the scenario count recorded in
data/ranges.json. Run it before publishing site changes; it exits non-zero on
any mismatch so it can gate CI.

Usage:
    python3 scripts/validate_ranges.py [--dataset /path/to/AgentThreatDataset]
"""

import argparse
import json
import sys
from pathlib import Path

SCENARIO_DIR_CANDIDATES = ("benchmark/scenarios", "sim/benchmark/scenarios")


def count_scenarios(range_dir: Path) -> int:
    """Count scenarios for one range.

    Two layouts exist in the dataset:
      - <range>/benchmark/scenarios/<id>/scenario.json  (dir-per-scenario)
      - <range>/benchmark/scenarios/<id>.json           (flat, kubectl-ai)
    """
    for rel in SCENARIO_DIR_CANDIDATES:
        scen = range_dir / rel
        if not scen.is_dir():
            continue
        n = 0
        for entry in sorted(scen.iterdir()):
            if entry.is_dir():
                if (entry / "scenario.json").is_file():
                    n += 1
            elif entry.suffix == ".json":
                n += 1
        return n
    return -1  # scenarios directory not found


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        type=Path,
        default=here.parent.parent / "AgentThreatDataset",
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
            print(f"{r['dir']:40} {r['scenarios']:>8} {'?':>6}  MISSING RANGE DIR")
            failures += 1
            continue
        found = count_scenarios(range_dir)
        ok = found == r["scenarios"]
        if not ok:
            failures += 1
        print(f"{r['dir']:40} {r['scenarios']:>8} {found:>6}  {'ok' if ok else 'MISMATCH'}")

    if failures:
        print(f"\n{failures} range(s) failed validation — regenerate data/ranges.json")
        return 1
    print(f"\nall {len(ranges)} ranges validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
