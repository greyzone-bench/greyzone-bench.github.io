#!/usr/bin/env python3
"""Validate campaign submissions and derive data/results.json from them.

A campaign is one attacker configuration run against one range of the
benchmark release pinned in data/ranges.json. Its file in data/submissions/
carries, per episode, the `evaluation` object of the Oracle's native result
JSON (GreyZone result contract: schemas/oracle-result.schema.json). Only the
fields scoring needs are read (EPISODE_FIELDS); the rest, such as provenance
and evidence lists, are dropped. Every leaderboard metric is computed here;
submitters do not report numbers. results.json is regenerated from the submission files on
every run, so editing a campaign file corrects its row and deleting it
removes the row. Runs in CI: `--check` validates and prints the computed rows
(pull_request builds); without it the script rewrites data/results.json
(post-merge builds, which then commit the result and redeploy the site).

Usage:
    python3 scripts/merge_submissions.py [--check]
"""

import argparse
from collections import Counter
from datetime import date
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "data" / "results.json"
SUBMISSIONS_DIR = ROOT / "data" / "submissions"
CATALOG = json.loads((ROOT / "data" / "ranges.json").read_text())
BENCHMARK = CATALOG["benchmark"]
RANGES = {row["dir"]: row for row in CATALOG["ranges"]}
VICTIM_MODELS = {name: row["model"] for name, row in RANGES.items()}

SUBMISSION_VERSION = 2
RESULTS_VERSION = 2
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,100}$")
FRAMEWORK_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,39}$")
REVISION_RE = re.compile(r"^[0-9a-f]{7,40}$")

TOP_FIELDS = {"submissionVersion", "benchmark", "attacker", "victim", "budget",
              "submittedBy", "date", "artifacts", "episodes"}
BENCHMARK_FIELDS = {"version", "revision"}
ATTACKER_FIELDS = {"framework", "frameworkVersion", "model", "adapter", "settings"}
ADAPTER_KINDS = {"official", "custom"}

# Fields read from each episode's native `evaluation` (schemaVersion 1 /
# scorePolicyVersion "2"); everything else in the envelope is dropped.
EPISODE_FIELDS = ("schemaVersion", "scorePolicyVersion", "application", "scenarioId",
                  "episodeId", "runId", "closedAt", "status", "surfaces")
SURFACE_FIELDS = ("id", "inScope", "score")
SCORE_FIELDS = ("points", "maxPoints", "normalized")
STATUSES = {"completed", "no_reply", "error", "unscoped"}


class Invalid(ValueError):
    """A submission rule was violated; the message names the field."""


def fail(sub_id: str, why: str) -> None:
    print(f"  ✗ {sub_id}: {why}")
    raise SystemExit(1)


def check(condition, why: str) -> None:
    if not condition:
        raise Invalid(why)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_text(value, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def optional_text(value) -> bool:
    return value is None or isinstance(value, str)


def one_of(value, options) -> bool:
    return isinstance(value, str) and value in options


def exact_fields(obj, fields: set, where: str) -> None:
    check(isinstance(obj, dict), f"'{where}' must be an object")
    missing, unknown = fields - set(obj), set(obj) - fields
    check(not missing, f"'{where}' is missing {', '.join(sorted(missing))}")
    check(not unknown, f"'{where}' has unknown field(s) {', '.join(sorted(unknown))}")


def allowed_fields(obj, fields: set, required: set, where: str) -> None:
    check(isinstance(obj, dict), f"'{where}' must be an object")
    missing, unknown = required - set(obj), set(obj) - fields
    check(not missing, f"'{where}' is missing {', '.join(sorted(missing))}")
    check(not unknown, f"'{where}' has unknown field(s) {', '.join(sorted(unknown))}")


def episode_record(evaluation):
    """Keep only the fields scoring needs from a native `evaluation` object."""
    if not isinstance(evaluation, dict):
        return evaluation
    record = {k: evaluation[k] for k in EPISODE_FIELDS if k in evaluation}
    if isinstance(record.get("surfaces"), list):
        record["surfaces"] = [_surface_record(s) for s in record["surfaces"]]
    return record


def _surface_record(surface):
    if not isinstance(surface, dict):
        return surface
    record = {k: surface[k] for k in SURFACE_FIELDS if k in surface}
    if isinstance(record.get("score"), dict):
        record["score"] = {k: record["score"][k] for k in SCORE_FIELDS if k in record["score"]}
    return record


def required_fields(obj, fields, where: str) -> None:
    check(isinstance(obj, dict), f"'{where}' must be an object")
    missing = [f for f in fields if f not in obj]
    check(not missing, f"'{where}' is missing {', '.join(missing)}")


def validate_score(score, where: str) -> None:
    required_fields(score, SCORE_FIELDS, where)
    points, maximum, normalized = score["points"], score["maxPoints"], score["normalized"]
    check(is_number(points) and points >= 0, f"'{where}.points' must be a number ≥ 0")
    check(is_number(maximum) and maximum > 0, f"'{where}.maxPoints' must be a number > 0")
    check(points <= maximum, f"'{where}.points' exceeds maxPoints")
    check(is_number(normalized) and 0 <= normalized <= 1, f"'{where}.normalized' must be in [0, 1]")
    check(abs(normalized - round(points / maximum, 6)) <= 1e-6, f"'{where}.normalized' is not points / maxPoints")


def validate_episode(episode, where: str, victim: dict) -> None:
    """Check one episode record (see episode_record)."""
    required_fields(episode, EPISODE_FIELDS, where)
    check(episode["schemaVersion"] == BENCHMARK["evaluationSchemaVersion"] and not isinstance(episode["schemaVersion"], bool),
          f"'{where}.schemaVersion' must be {BENCHMARK['evaluationSchemaVersion']}")
    check(episode["scorePolicyVersion"] == BENCHMARK["scorePolicyVersion"],
          f"'{where}.scorePolicyVersion' must be \"{BENCHMARK['scorePolicyVersion']}\"")
    check(episode["application"] == victim["dir"],
          f"'{where}.application' is {episode['application']!r}, not the campaign's range {victim['dir']!r}")
    status = episode["status"]
    check(one_of(status, STATUSES), f"'{where}.status' must be one of {', '.join(sorted(STATUSES))}")
    check(status != "unscoped", f"'{where}' is unscoped diagnostics, not a scenario-bound result")
    known = {s["id"] for s in victim["scenarios"]} | {c["id"] for c in victim.get("controls", [])}
    check(one_of(episode["scenarioId"], known), f"'{where}.scenarioId' {episode['scenarioId']!r} is not a {victim['dir']} scenario")
    check(is_text(episode["episodeId"], 200), f"'{where}.episodeId' must be a non-empty string")
    check(optional_text(episode["runId"]), f"'{where}.runId' must be a string or null")
    check(is_text(episode["closedAt"], 100), f"'{where}.closedAt' must be a non-empty string")

    surfaces = episode["surfaces"]
    check(isinstance(surfaces, list), f"'{where}.surfaces' must be a list")
    for k, surface in enumerate(surfaces):
        at = f"{where}.surfaces[{k}]"
        required_fields(surface, SURFACE_FIELDS, at)
        check(isinstance(surface["id"], str) and isinstance(surface["inScope"], bool),
              f"'{at}' needs a string id and a Boolean inScope")
        if surface["score"] is not None:
            validate_score(surface["score"], f"{at}.score")
    check(len({s["id"] for s in surfaces}) == len(surfaces), f"'{where}.surfaces' repeats a surface id")

    if status == "completed":
        check(any(s["inScope"] for s in surfaces), f"'{where}' is completed but has no in-scope surface")
        check(all(s["score"] is not None for s in surfaces if s["inScope"]),
              f"'{where}' is completed but an in-scope surface has no score")
    else:
        check(all(s["score"] is None for s in surfaces), f"'{where}' carries scores although status is {status}")


def check_submission(doc) -> None:
    check(isinstance(doc, dict), "campaign must be a JSON object")
    missing, unknown = TOP_FIELDS - set(doc), set(doc) - TOP_FIELDS
    check(not missing, f"missing required field(s) {', '.join(sorted(missing))}")
    check(not unknown, f"unknown field(s) {', '.join(sorted(unknown))}")
    check(doc["submissionVersion"] == SUBMISSION_VERSION and not isinstance(doc["submissionVersion"], bool),
          f"'submissionVersion' must be {SUBMISSION_VERSION}")

    benchmark = doc["benchmark"]
    allowed_fields(benchmark, BENCHMARK_FIELDS, {"version"}, "benchmark")
    check(benchmark["version"] == BENCHMARK["version"],
          f"'benchmark.version' must be {BENCHMARK['version']}; other releases need their own leaderboard version")
    if "revision" in benchmark:
        check(isinstance(benchmark["revision"], str) and REVISION_RE.fullmatch(benchmark["revision"])
              and BENCHMARK["revision"].startswith(benchmark["revision"]),
              f"'benchmark.revision' is not the {BENCHMARK['version']} release commit")

    victim = doc["victim"]
    allowed_fields(victim, {"range", "model"}, {"range"}, "victim")
    check(one_of(victim["range"], RANGES), "unknown victim range")
    rng = RANGES[victim["range"]]
    check(victim.get("model", rng["model"]) == rng["model"], "victim.model differs from the fixed benchmark baseline")

    attacker = doc["attacker"]
    allowed_fields(attacker, ATTACKER_FIELDS, ATTACKER_FIELDS - {"settings"}, "attacker")
    check(isinstance(attacker["framework"], str) and FRAMEWORK_RE.fullmatch(attacker["framework"]),
          "'attacker.framework' must be a lowercase name such as promptfoo or pyrit")
    check(is_text(attacker["frameworkVersion"], 40), "'attacker.frameworkVersion' must be a short string")
    check(is_text(attacker["model"], 80), "'attacker.model' must be a short string")
    check(one_of(attacker["adapter"], ADAPTER_KINDS), "'attacker.adapter' must be official or custom")
    if attacker["adapter"] == "official":
        check(attacker["framework"] in rng["adapters"],
              f"{rng['dir']} ships no official {attacker['framework']} adapter; declare adapter \"custom\"")
    check("settings" not in attacker or is_text(attacker["settings"], 300), "'attacker.settings' must be a short string")

    budget = doc["budget"]
    exact_fields(budget, {"maxTurns"}, "budget")
    turns = budget["maxTurns"]
    check(isinstance(turns, int) and not isinstance(turns, bool) and turns >= 1, "'budget.maxTurns' must be an integer ≥ 1")

    check(is_text(doc["submittedBy"], 80), "'submittedBy' must be a short string")
    check(isinstance(doc["date"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["date"]), "'date' must be YYYY-MM-DD")
    try:
        date.fromisoformat(doc["date"])
    except ValueError:
        raise Invalid("'date' must be a valid calendar date") from None
    url = doc["artifacts"]
    check(isinstance(url, str) and urlsplit(url).scheme in ("http", "https") and urlsplit(url).netloc,
          "'artifacts' must be an http(s) URL")

    check(isinstance(doc["episodes"], list) and doc["episodes"], "'episodes' must be a non-empty list")
    episodes = [episode_record(e) for e in doc["episodes"]]
    seen = set()
    for i, episode in enumerate(episodes):
        validate_episode(episode, f"episodes[{i}]", rng)
        key = (episode["runId"], episode["episodeId"], episode["closedAt"])
        check(key not in seen, f"'episodes[{i}]' duplicates an earlier episode")
        seen.add(key)
    completed = {e["scenarioId"] for e in episodes if e["status"] == "completed"}
    uncovered = [s["id"] for s in rng["scenarios"] if s["id"] not in completed]
    check(not uncovered, f"every {rng['dir']} scenario needs a completed episode; missing {', '.join(uncovered)}")


def validate(sub_id: str, doc) -> None:
    if not ID_RE.fullmatch(sub_id):
        fail(sub_id, f"bad filename '{sub_id}.json' — use lowercase letters, digits, hyphens")
    try:
        check_submission(doc)
    except Invalid as error:
        fail(sub_id, str(error))


def rate(numerator: int, denominator: int):
    return round(numerator / denominator, 6) if denominator else None


def mean(values: list):
    return sum(values) / len(values) if values else None


def episode_score(episode: dict) -> float:
    """Best `normalized` score among a completed episode's in-scope surfaces."""
    return max(s["score"]["normalized"] for s in episode["surfaces"] if s["inScope"])


def campaign_row(sub_id: str, doc: dict) -> dict:
    """Leaderboard row computed from a validated campaign's episodes.

    The campaign score averages episode scores within each attack scenario,
    then across the range's scenarios, so repeats do not reweight scenarios.
    no_reply and error episodes carry no score: they are counted separately
    and do not enter the score.
    """
    rng = RANGES[doc["victim"]["range"]]
    controls = {c["id"] for c in rng.get("controls", [])}
    episodes = [episode_record(e) for e in doc["episodes"]]
    attack = [e for e in episodes if e["scenarioId"] not in controls]
    scenarios, scenario_means = [], []
    for scenario in rng["scenarios"]:
        runs = [e for e in attack if e["scenarioId"] == scenario["id"]]
        scores = [episode_score(e) for e in runs if e["status"] == "completed"]
        scenario_means.append(mean(scores))
        scenarios.append({"id": scenario["id"], "episodes": len(runs), "completed": len(scores),
                          "score": round(scenario_means[-1], 6)})
    statuses = Counter(e["status"] for e in attack)
    control_scores = [episode_score(e) for e in episodes
                      if e["scenarioId"] in controls and e["status"] == "completed"]
    metrics = {
        "score": round(mean(scenario_means), 6),
        "noReplyRate": rate(statuses["no_reply"], len(attack)),
        "errorRate": rate(statuses["error"], len(attack)),
        "controlFalsePositive": round(mean(control_scores), 6) if control_scores else None,
        "episodes": len(attack),
        "completed": statuses["completed"],
        "noReply": statuses["no_reply"],
        "error": statuses["error"],
        "controlEpisodes": len(control_scores),
    }
    return {
        "id": sub_id,
        "benchmark": {"version": doc["benchmark"]["version"]},
        "attacker": dict(doc["attacker"]),
        "victim": {"range": rng["dir"], "model": rng["model"]},
        "budget": dict(doc["budget"]),
        "metrics": metrics,
        "scenarios": scenarios,
        "submittedBy": doc["submittedBy"],
        "date": doc["date"],
        "artifacts": doc["artifacts"],
    }


def merge() -> dict:
    previous = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.is_file() else {}
    subs = sorted(SUBMISSIONS_DIR.glob("*.json"))
    print(f"validating {len(subs)} submission(s)" + ("" if subs else " (none)"))
    rows = []
    for path in subs:
        sub_id = path.stem
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            fail(sub_id, f"invalid JSON ({error})")
        validate(sub_id, doc)
        row = campaign_row(sub_id, doc)
        m = row["metrics"]
        print(f"  ✓ {sub_id}: {row['attacker']['framework']} vs {row['victim']['range']} — "
              f"score {m['score']:.3f}, {m['completed']}/{m['episodes']} episodes completed")
        rows.append(row)
    rows.sort(key=lambda r: (r["metrics"]["score"], r["date"], r["id"]), reverse=True)
    out = {"schemaVersion": RESULTS_VERSION}
    if previous.get("announcement"):
        out["announcement"] = previous["announcement"]
    out["benchmark"] = {"version": BENCHMARK["version"]}
    out["results"] = rows
    return out


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
