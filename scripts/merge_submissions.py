#!/usr/bin/env python3
"""Merge data/submissions/*.json campaign files into data/results.json.

Each submission is one JSON file in data/submissions/ named after its stable
id chosen by the contributor. Merging a file
with an existing id replaces that row, so a correction is just another PR.
Runs in CI: `--check` validates only (pull_request builds); without it the
script rewrites data/results.json (post-merge builds, which then commit the
result and redeploy the site).

Usage:
    python3 scripts/merge_submissions.py [--check]
"""

import argparse
from datetime import date
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "data" / "results.json"
SUBMISSIONS_DIR = ROOT / "data" / "submissions"
VICTIM_MODELS = {row["dir"]: row["model"] for row in json.loads((ROOT / "data/ranges.json").read_text())["ranges"]}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,100}$")

REQUIRED = {
    "attacker": ["framework", "model"],
    "victim": ["range"],
}
RATE_FIELDS = ["asr", "authenticity", "controlFalsePositive", "noReplyRate"]
REQUIRED_TOP = ["attacker", "victim", "episodes", "asr",
                "controlFalsePositive", "noReplyRate", "submittedBy", "date", "artifacts"]


def fail(sub_id: str, why: str) -> None:
    print(f"  ✗ {sub_id}: {why}")
    raise SystemExit(1)


def validate(sub_id: str, row: dict) -> None:
    if not isinstance(row, dict):
        fail(sub_id, "campaign must be a JSON object")
    if not ID_RE.fullmatch(sub_id):
        fail(sub_id, f"bad filename '{sub_id}.json' — use lowercase letters, digits, hyphens")
    for key in REQUIRED_TOP:
        if row.get(key) in (None, ""):
            fail(sub_id, f"missing required field '{key}'")
    for section, fields in REQUIRED.items():
        for f in fields:
            if not isinstance(row.get(section), dict) or not isinstance(row[section].get(f), str) or not row[section][f].strip():
                fail(sub_id, f"missing '{section}.{f}'")
    model = VICTIM_MODELS.get(row["victim"]["range"])
    if model is None:
        fail(sub_id, "unknown victim range")
    supplied_model = row["victim"].get("model")
    if supplied_model is not None and supplied_model != model:
        fail(sub_id, "victim.model differs from the fixed benchmark baseline")
    row["victim"]["model"] = model
    if isinstance(row["episodes"], bool) or not isinstance(row["episodes"], int) or row["episodes"] < 1:
        fail(sub_id, "'episodes' must be an integer ≥ 1")
    for f in RATE_FIELDS:
        v = row.get(f)
        if v is None:
            if f == "asr":
                fail(sub_id, "'asr' is required")
            continue  # authenticity may be null
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
            fail(sub_id, f"'{f}' must be a number in [0, 1]")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(row["date"])):
        fail(sub_id, "'date' must be YYYY-MM-DD")
    try:
        date.fromisoformat(row["date"])
    except (TypeError, ValueError):
        fail(sub_id, "'date' must be a valid calendar date")
    for strf in ("submittedBy",):
        if not isinstance(row[strf], str) or not row[strf].strip() or len(row[strf]) > 80:
            fail(sub_id, f"'{strf}' must be a short string")
    url = row.get("artifacts")
    if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
        fail(sub_id, "'artifacts' must be an http(s) URL")


def merge() -> dict:
    results_doc = json.loads(RESULTS_PATH.read_text())
    rows = {r["id"]: r for r in results_doc.get("results", []) if "id" in r}
    orphan = [r for r in results_doc.get("results", []) if "id" not in r]
    if orphan:
        print(f"  ✗ data/results.json contains {len(orphan)} row(s) without 'id' — regenerate it")
        raise SystemExit(1)

    for sub_id, stored in rows.items():
        victim = stored.get("victim", {})
        expected = VICTIM_MODELS.get(victim.get("range"))
        if expected is None or victim.get("model") != expected:
            fail(sub_id, "stored result uses a different model baseline; publish a separate leaderboard version")

    subs = sorted(SUBMISSIONS_DIR.glob("*.json"))
    print(f"validating {len(subs)} submission(s)" + ("" if subs else " (none)"))
    for p in subs:
        sub_id = p.stem
        try:
            row = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            fail(sub_id, f"invalid JSON ({e})")
        validate(sub_id, row)
        row["id"] = sub_id
        rows[sub_id] = row
        print(f"  ✓ {sub_id}")

    merged = sorted(rows.values(), key=lambda r: (r.get("date", ""), r["id"]), reverse=True)
    results_doc["results"] = merged
    return results_doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="validate submissions and exit without writing")
    args = ap.parse_args()

    doc = merge()
    if args.check:
        print(f"check ok — {len(doc['results'])} campaign row(s) would result")
        return 0

    RESULTS_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote data/results.json — {len(doc['results'])} campaign row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
