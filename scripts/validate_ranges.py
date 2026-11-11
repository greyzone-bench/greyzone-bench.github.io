#!/usr/bin/env python3
"""Validate data/ranges.json against a checkout of the benchmark release.

The dataset repository is the single source of truth. This script runs the
dataset's own static scenario audit (scripts/check_scenarios.py) and checks,
per range, that data/ranges.json records exactly the same attack scenarios,
their Oracle success surfaces, the benign controls, the shipped red-teaming
service adapters and the fixed victim model. Run it against a checkout of the
release named in data/ranges.json before publishing catalog changes; it exits
non-zero on any mismatch so it can gate CI.

Usage:
    python3 scripts/validate_ranges.py [--dataset /path/to/GreyZone]
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

SERVICE_ADAPTERS = {"deepteam", "dreadnode", "lakera", "promptfoo", "pyrit"}
CONTROL_IDS = {"control"}  # benign calibration scenarios, not attack scenarios

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


def dataset_audit(dataset: Path) -> dict:
    """Run the release's scenario audit; returns {range: {scenario: [surfaces]}}."""
    spec = importlib.util.spec_from_file_location("check_scenarios", dataset / "scripts" / "check_scenarios.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit(root=dataset)
    if report["status"] != "PASS":
        bad = [f"{r['project']}/{r.get('scenario', '-')}: {r.get('detail')}" for r in report["results"] if r["status"] != "PASS"]
        raise SystemExit("dataset scenario audit failed:\n  " + "\n  ".join(bad))
    found = {}
    for row in report["results"]:
        found.setdefault(row["project"], {})[row["scenario"]] = row["success_surfaces"]
    return found


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=here.parent.parent / "GreyZone",
                    help="path to the dataset checkout (default: sibling of this repo)")
    args = ap.parse_args()

    catalog = json.loads((here.parent / "data" / "ranges.json").read_text())
    benchmark = catalog["benchmark"]
    found = dataset_audit(args.dataset)

    failures = []
    print(f"{'range':38} {'scenarios':>9} {'controls':>8} {'adapters':>8}  status")
    for r in catalog["ranges"]:
        name, problems = r["dir"], []
        actual = found.get(name, {})
        attack = {k: v for k, v in actual.items() if k not in CONTROL_IDS}
        controls = {k: v for k, v in actual.items() if k in CONTROL_IDS}
        recorded = {s["id"]: s["surfaces"] for s in r["scenarios"]}
        if recorded != attack:
            problems.append(f"scenarios/surfaces differ (dataset: {sorted(attack)})")
        if {c["id"]: c["surfaces"] for c in r.get("controls", [])} != controls:
            problems.append("controls differ")
        if r["surfaces"] != sorted({s for v in attack.values() for s in v}):
            problems.append("surfaces is not the union of the scenarios' success surfaces")
        redteam = args.dataset / name / "redteam"
        shipped = sorted(p.name for p in redteam.iterdir() if p.is_dir() and p.name in SERVICE_ADAPTERS) if redteam.is_dir() else []
        if r["adapters"] != shipped:
            problems.append(f"adapters differ (dataset: {shipped or 'none'})")
        relative, key = MODEL_CONFIGS[name]
        config = args.dataset / name / relative
        configured = re.search(rf"(?m)^{key}=([^\r\n]+)$", config.read_text()) if config.is_file() else None
        if not configured or configured[1].strip() != r["model"]:
            problems.append(f"victim model differs from {relative}")
        print(f"{name:38} {len(r['scenarios']):>9} {len(r.get('controls', [])):>8} {len(r['adapters']):>8}  "
              + ("ok" if not problems else "MISMATCH: " + "; ".join(problems)))
        failures += problems

    head = subprocess.run(["git", "-C", str(args.dataset), "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode == 0 and head.stdout.strip() != benchmark["revision"]:
        print(f"\nnote: the checkout is at {head.stdout.strip()[:12]}, not the {benchmark['version']} "
              f"release commit {benchmark['revision'][:12]}")
    if failures:
        print(f"\n{len(failures)} problem(s) — regenerate data/ranges.json from the {benchmark['version']} release")
        return 1
    total = sum(len(r["scenarios"]) for r in catalog["ranges"])
    print(f"\nall {len(catalog['ranges'])} ranges and {total} attack scenarios match the dataset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
