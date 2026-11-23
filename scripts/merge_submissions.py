#!/usr/bin/env python3
"""Validate benchmark rounds and derive data/results.json from them.

Each new submission has a slot for every benchmark attack scenario. Score
completed Oracle evaluations and record zero for missing or unscored slots.
The historical per-application submissions retain their original file paths.
Their recorded repeat labels reconstruct the initial benchmark rounds.

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
LEGACY_REPEATS_PATH = ROOT / "data" / "legacy-repeats.json"
CATALOG = json.loads((ROOT / "data" / "ranges.json").read_text())
BENCHMARK = CATALOG["benchmark"]
RANGES = {row["dir"]: row for row in CATALOG["ranges"]}
VICTIM_MODELS = {name: row["model"] for name, row in RANGES.items()}

LEGACY_SUBMISSION_VERSION = 2
SUBMISSION_VERSION = 3
RESULTS_VERSION = 3
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,100}$")
FRAMEWORK_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,39}$")
REVISION_RE = re.compile(r"^[0-9a-f]{7,40}$")

TOP_FIELDS = {"submissionVersion", "benchmark", "attacker", "victim", "budget",
              "submittedBy", "date", "artifacts", "episodes"}
ROUND_FIELDS = (TOP_FIELDS - {"victim", "episodes"}) | {"repeat", "scenarios"}
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


def check_metadata(doc, *, full_round=False) -> None:
    benchmark = doc["benchmark"]
    allowed_fields(benchmark, BENCHMARK_FIELDS, {"version"}, "benchmark")
    check(benchmark["version"] == BENCHMARK["version"],
          f"'benchmark.version' must be {BENCHMARK['version']}; other releases need their own leaderboard version")
    if "revision" in benchmark:
        check(isinstance(benchmark["revision"], str) and REVISION_RE.fullmatch(benchmark["revision"])
              and BENCHMARK["revision"].startswith(benchmark["revision"]),
              f"'benchmark.revision' is not the {BENCHMARK['version']} release commit")

    attacker = doc["attacker"]
    allowed_fields(attacker, ATTACKER_FIELDS | ({"applications"} if full_round else set()),
                   ATTACKER_FIELDS - {"settings"}, "attacker")
    check(isinstance(attacker["framework"], str) and FRAMEWORK_RE.fullmatch(attacker["framework"]),
          "'attacker.framework' must be a lowercase name such as promptfoo or pyrit")
    check(is_text(attacker["frameworkVersion"], 40), "'attacker.frameworkVersion' must be a short string")
    check(is_text(attacker["model"], 80), "'attacker.model' must be a short string")
    check(one_of(attacker["adapter"], ADAPTER_KINDS), "'attacker.adapter' must be official or custom")
    check("settings" not in attacker or is_text(attacker["settings"], 300), "'attacker.settings' must be a short string")

    budget = doc["budget"]
    exact_fields(budget, {"maxTurns"}, "budget")
    turns = budget["maxTurns"]
    if isinstance(turns, dict):
        exact_fields(turns, {"direct", "indirect"}, "budget.maxTurns")
        limits = [(f"budget.maxTurns.{mode}", count) for mode, count in turns.items()]
    else:
        limits = [("budget.maxTurns", turns)]
    for field, count in limits:
        check(isinstance(count, int) and not isinstance(count, bool) and count >= 1,
              f"'{field}' must be an integer ≥ 1")

    check(is_text(doc["submittedBy"], 80), "'submittedBy' must be a short string")
    check(isinstance(doc["date"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["date"]), "'date' must be YYYY-MM-DD")
    try:
        date.fromisoformat(doc["date"])
    except ValueError:
        raise Invalid("'date' must be a valid calendar date") from None
    url = doc["artifacts"]
    check(isinstance(url, str) and urlsplit(url).scheme in ("http", "https") and urlsplit(url).netloc,
          "'artifacts' must be an http(s) URL")


def check_adapter(framework, adapter, rng) -> None:
    if adapter == "official":
        check(framework in rng["adapters"],
              f"{rng['dir']} ships no official {framework} adapter; declare adapter \"custom\"")


def check_submission(doc) -> None:
    check(isinstance(doc, dict), "submission must be a JSON object")
    if doc.get("submissionVersion") == SUBMISSION_VERSION:
        check_round(doc)
        return
    exact_fields(doc, TOP_FIELDS, "campaign")
    check(doc["submissionVersion"] == LEGACY_SUBMISSION_VERSION and not isinstance(doc["submissionVersion"], bool),
          f"'submissionVersion' must be {SUBMISSION_VERSION} or {LEGACY_SUBMISSION_VERSION}")
    check_metadata(doc)
    victim = doc["victim"]
    allowed_fields(victim, {"range", "model"}, {"range"}, "victim")
    check(one_of(victim["range"], RANGES), "unknown victim range")
    rng = RANGES[victim["range"]]
    check(victim.get("model", rng["model"]) == rng["model"], "victim.model differs from the fixed benchmark baseline")
    check_adapter(doc["attacker"]["framework"], doc["attacker"]["adapter"], rng)

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


def check_round(doc) -> None:
    allowed_fields(doc, ROUND_FIELDS | {"controls"}, ROUND_FIELDS, "round")
    check(type(doc["submissionVersion"]) is int, "'submissionVersion' must be an integer")
    check(type(doc["repeat"]) is int and doc["repeat"] >= 1, "'repeat' must be a positive integer")
    check_metadata(doc, full_round=True)
    attacker = doc["attacker"]
    overrides = attacker.get("applications", {})
    allowed_fields(overrides, set(RANGES), set(), "attacker.applications")
    slots = doc["scenarios"]
    exact_fields(slots, set(RANGES), "scenarios")
    controls = doc.get("controls", {})
    allowed_fields(controls, {name for name, rng in RANGES.items() if rng.get("controls")}, set(), "controls")
    seen = set()
    for name, rng in RANGES.items():
        config = overrides.get(name, {})
        allowed_fields(config, {"model", "adapter"}, set(), f"attacker.applications.{name}")
        check("model" not in config or is_text(config["model"], 80), f"'{name}' attacker model must be a short string")
        adapter = config.get("adapter", attacker["adapter"])
        check(one_of(adapter, ADAPTER_KINDS), f"'{name}' adapter must be official or custom")
        exact_fields(slots[name], {s["id"] for s in rng["scenarios"]}, f"scenarios.{name}")
        control_slots = controls.get(name, {})
        allowed_fields(control_slots, {s["id"] for s in rng.get("controls", [])}, set(), f"controls.{name}")
        if any(evaluation is not None for entries in (slots[name], control_slots) for evaluation in entries.values()):
            check_adapter(attacker["framework"], adapter, rng)
        for category, entries in (("scenarios", slots[name]), ("controls", control_slots)):
            for scenario, evaluation in entries.items():
                if evaluation is None:
                    continue
                at = f"{category}.{name}.{scenario}"
                episode = episode_record(evaluation)
                validate_episode(episode, at, rng)
                check(episode["scenarioId"] == scenario, f"'{at}' has a different Oracle scenarioId")
                key = (name, episode["runId"], episode["episodeId"], episode["closedAt"])
                check(key not in seen, f"'{at}' duplicates an earlier episode")
                seen.add(key)


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


def empty_round() -> dict:
    return {name: {scenario["id"]: None for scenario in rng["scenarios"]} for name, rng in RANGES.items()}


def round_slots(episodes) -> tuple[dict, dict]:
    """Place each supplied Oracle evaluation in a benchmark round's slots."""
    slots = empty_round()
    controls = {}
    for episode in episodes:
        name, scenario = episode.get("application"), episode.get("scenarioId")
        check(one_of(name, RANGES), "unknown or missing Oracle application")
        if one_of(scenario, slots[name]):
            target = slots[name]
        else:
            check(one_of(scenario, {s["id"] for s in RANGES[name].get("controls", [])}), f"unknown Oracle scenario in {name}")
            target = controls.setdefault(name, {})
        check(target.get(scenario) is None, f"'{name}/{scenario}' has more than one evaluation for this round")
        target[scenario] = episode
    return slots, controls


def round_row(sub_id: str, doc: dict) -> dict:
    applications = {}
    statuses = Counter()
    for name, scenarios in doc["scenarios"].items():
        scores = []
        for scenario, evaluation in scenarios.items():
            status = evaluation["status"] if evaluation is not None else "missing"
            score = episode_score(episode_record(evaluation)) if status == "completed" else 0
            scores.append({"id": scenario, "score": score, "status": status})
            statuses[status] += 1
        applications[name] = {"scenarios": scores, "score": round(math.fsum(s["score"] for s in scores), 6)}

    submitted = sum(statuses.values()) - statuses["missing"]
    control_scores = [episode_score(episode_record(episode)) for controls in doc.get("controls", {}).values()
                      for episode in controls.values() if episode and episode["status"] == "completed"]
    return {
        "id": sub_id,
        **{field: doc[field] for field in ("attacker", "budget", "date", "submittedBy", "artifacts")},
        "applications": applications,
        "metrics": {
            "score": round(math.fsum(scenario["score"] for app in applications.values()
                                     for scenario in app["scenarios"]), 6),
            "episodes": submitted,
            "completed": statuses["completed"],
            "missing": statuses["missing"],
            "noReplyRate": rate(statuses["no_reply"], submitted),
            "errorRate": rate(statuses["error"], submitted),
            "controlFalsePositive": round(mean(control_scores), 6) if control_scores else None,
        },
        "repeat": doc["repeat"],
    }


def legacy_rounds(campaigns, repeats) -> list:
    groups = {}
    for sub_id, doc in campaigns:
        labels = {tuple(record[:3]): record[3] for record in repeats[sub_id]}
        actual = {(e["runId"], e["episodeId"], e["closedAt"]) for e in doc["episodes"]}
        check(labels.keys() == actual, f"'{sub_id}' episode identities differ from the archived repeat labels")
        for episode in doc["episodes"]:
            repeat = labels[(episode["runId"], episode["episodeId"], episode["closedAt"])]
            key = (doc["submittedBy"], doc["attacker"]["framework"], doc["date"], repeat)
            entries = groups.setdefault(key, {})
            if sub_id not in entries:
                entries[sub_id] = (doc, [])
            entries[sub_id][1].append(episode)

    rows = []
    for (_, framework, _, repeat), entries in sorted(groups.items()):
        docs = [doc for doc, _ in entries.values()]
        slots, controls = round_slots(episode for _, episodes in entries.values() for episode in episodes)
        attacker = dict(docs[0]["attacker"])
        attacker["applications"] = {doc["victim"]["range"]: doc["attacker"] for doc in docs}
        data = {**docs[0], "attacker": attacker, "repeat": repeat, "scenarios": slots, "controls": controls}
        row = round_row(f"initial-{framework}-repeat-{repeat:02}", data)
        del row["artifacts"]  # The original per-application files carry their respective archive links.
        row["sources"] = list(entries)
        rows.append(row)
    return rows


def unique_json_fields(pairs) -> dict:
    obj = {}
    for key, value in pairs:
        check(key not in obj, f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def merge() -> dict:
    previous = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.is_file() else {}
    subs = sorted(SUBMISSIONS_DIR.glob("*.json"))
    print(f"validating {len(subs)} submission(s)" + ("" if subs else " (none)"))
    repeats = json.loads(LEGACY_REPEATS_PATH.read_text()) if LEGACY_REPEATS_PATH.exists() else {}
    legacy, rows, rounds = [], [], []
    for path in subs:
        sub_id = path.stem
        try:
            doc = json.loads(path.read_text(), object_pairs_hook=unique_json_fields)
        except json.JSONDecodeError as error:
            fail(sub_id, f"invalid JSON ({error})")
        except Invalid as error:
            fail(sub_id, str(error))
        validate(sub_id, doc)
        if doc["submissionVersion"] == SUBMISSION_VERSION:
            row = round_row(sub_id, doc)
            rounds.append(row)
            print(f"  ✓ {sub_id}: {row['metrics']['score']:.3f} points, {row['metrics']['missing']} missing")
            continue
        if sub_id not in repeats:
            fail(sub_id, f"new submissions must use full-round submissionVersion {SUBMISSION_VERSION}")
        legacy.append((sub_id, doc))
        row = campaign_row(sub_id, doc)
        m = row["metrics"]
        print(f"  ✓ {sub_id}: {row['attacker']['framework']} vs {row['victim']['range']} — "
              f"score {m['score']:.3f}, {m['completed']}/{m['episodes']} episodes completed")
        rows.append(row)
    rows.sort(key=lambda r: (r["metrics"]["score"], r["date"], r["id"]), reverse=True)
    try:
        rounds.extend(legacy_rounds(legacy, repeats))
    except Invalid as error:
        fail("legacy repeats", str(error))
    if len({row["id"] for row in rounds}) != len(rounds):
        fail("rounds", "round filenames and reconstructed archive IDs must be unique")
    numbered = {}
    for row in rounds:
        submitter = " ".join(row["submittedBy"].casefold().split())
        key = (submitter, row["attacker"]["framework"], row["repeat"])
        if key in numbered:
            fail(row["id"], f"repeat {row['repeat']} is already used by {numbered[key]} for this submitter and tool")
        numbered[key] = row["id"]
    rounds.sort(key=lambda r: (r["metrics"]["score"], r["date"], r["id"]), reverse=True)
    out = {"schemaVersion": RESULTS_VERSION}
    if previous.get("announcement"):
        out["announcement"] = previous["announcement"]
    out["benchmark"] = {"version": BENCHMARK["version"]}
    out["results"] = rows
    out["rounds"] = rounds
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="validate submissions and exit without writing")
    args = ap.parse_args()

    doc = merge()
    if args.check:
        print(f"check ok — {len(doc['rounds'])} benchmark round(s) would result")
        return 0

    RESULTS_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote data/results.json — {len(doc['rounds'])} benchmark round(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
