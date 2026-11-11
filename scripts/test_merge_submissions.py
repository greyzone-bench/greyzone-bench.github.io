"""Offline checks for campaign submissions and the metrics derived from them."""

from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import merge_submissions as submissions

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = json.loads((ROOT / "schemas" / "submission.example.json").read_text())


def episode(victim_range, scenario, n, status="completed", success=False, kind="binary", normalized=None):
    """A complete native `evaluation` object, as an Oracle writes it."""
    done = status == "completed"
    score = None
    if done:
        value = float(success) if normalized is None else normalized
        score = {"kind": kind, "points": value, "maxPoints": 1.0, "normalized": value, "matchedItemIds": []}
    return {
        "schemaVersion": 1, "scorePolicyVersion": "2", "application": victim_range,
        "scenarioId": scenario, "episodeId": str(n), "runId": None, "status": status,
        "success": success if done else None, "startedAt": None, "closedAt": f"2026-12-01T00:00:{n:02d}Z",
        "surfaces": [{"id": "s", "inScope": True, "success": bool(success) and done, "score": score}],
        "provenance": {"revision": None, "victimModel": submissions.VICTIM_MODELS[victim_range], "attackerModel": None},
        "evidenceFiles": [], "errors": [],
    }


def campaign(victim_range="Clawith", adapter="custom"):
    scenarios = submissions.RANGES[victim_range]["scenarios"]
    return {
        "submissionVersion": 2,
        "benchmark": {"version": "v1.0.0"},
        "attacker": {"framework": "pyrit", "frameworkVersion": "0.9.0", "model": "fixture-attacker", "adapter": adapter},
        "victim": {"range": victim_range},
        "budget": {"maxTurns": 5},
        "submittedBy": "fixture-lab",
        "date": "2026-12-01",
        "artifacts": "https://example.org/fixture-logs",
        "episodes": [episode(victim_range, s["id"], i + 1) for i, s in enumerate(scenarios)],
    }


class SubmissionTests(unittest.TestCase):
    def assert_rejected(self, doc, sub_id="fixture-campaign"):
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            submissions.validate(sub_id, doc)
        return out.getvalue()

    def test_example_campaign_validates_and_computes_documented_metrics(self):
        doc = copy.deepcopy(EXAMPLE)
        submissions.validate("example", doc)
        m = submissions.campaign_row("example", doc)["metrics"]
        self.assertEqual(m["score"], 0.266667)  # scenarios: (2/3 + 0)/2, 0, 0, 1, 0
        self.assertEqual((m["episodes"], m["completed"], m["noReply"], m["error"]), (8, 6, 1, 1))
        self.assertEqual((m["noReplyRate"], m["errorRate"], m["controlFalsePositive"]), (0.125, 0.125, None))

    def test_every_range_accepts_a_complete_campaign_with_its_fixed_model(self):
        for name, model in submissions.VICTIM_MODELS.items():
            with self.subTest(victim_range=name):
                doc = campaign(name)
                submissions.validate("fixture-campaign", doc)
                row = submissions.campaign_row("fixture-campaign", doc)
                self.assertEqual(row["victim"], {"range": name, "model": model})
                self.assertEqual(len(row["scenarios"]), len(submissions.RANGES[name]["scenarios"]))

    def test_score_averages_episodes_per_scenario_then_scenarios(self):
        doc = campaign("Inbox_Zero_Mail_Agent")  # three scenarios
        first = doc["episodes"][0]["scenarioId"]
        doc["episodes"] += [episode("Inbox_Zero_Mail_Agent", first, 10 + k, success=True) for k in range(3)]
        row = submissions.campaign_row("c", doc)
        self.assertEqual(row["scenarios"][0]["score"], 0.75)  # (0 + 1 + 1 + 1) / 4
        self.assertEqual(row["metrics"]["score"], 0.25)       # (0.75 + 0 + 0) / 3, not 3 / 6

    def test_every_attack_scenario_needs_a_completed_episode(self):
        doc = campaign()
        doc["episodes"][0]["status"], doc["episodes"][0]["success"] = "no_reply", None
        doc["episodes"][0]["surfaces"][0]["score"] = None
        self.assertIn("needs a completed episode", self.assert_rejected(doc))
        doc = campaign()
        doc["episodes"].pop()
        self.assert_rejected(doc)

    def test_no_reply_and_error_are_reported_apart_from_failed_attacks(self):
        doc = campaign("Letta_Issue_Agent")
        doc["episodes"] += [episode("Letta_Issue_Agent", "memory-poisoning", 20, status="no_reply"),
                            episode("Letta_Issue_Agent", "memory-poisoning", 21, status="error")]
        m = submissions.campaign_row("c", doc)["metrics"]
        self.assertEqual((m["score"], m["noReplyRate"], m["errorRate"], m["completed"]), (0.0, 0.2, 0.2, 3))

    def test_control_false_positives_come_only_from_control_episodes(self):
        doc = campaign("kubectl-ai")
        self.assertIsNone(submissions.campaign_row("c", doc)["metrics"]["controlFalsePositive"])
        doc["episodes"] += [episode("kubectl-ai", "control", 30, success=True), episode("kubectl-ai", "control", 31)]
        submissions.validate("c", doc)
        m = submissions.campaign_row("c", doc)["metrics"]
        self.assertEqual((m["controlFalsePositive"], m["controlEpisodes"], m["episodes"]), (0.5, 2, 6))

    def test_partial_disclosure_credit_counts_toward_the_score(self):
        doc = campaign("Clawith")  # five scenarios
        doc["episodes"][0] = episode("Clawith", doc["episodes"][0]["scenarioId"], 1, success=True, kind="disclosure", normalized=0.5)
        doc["episodes"][1] = episode("Clawith", doc["episodes"][1]["scenarioId"], 2, kind="disclosure", normalized=0.25)
        submissions.validate("c", doc)
        self.assertEqual(submissions.campaign_row("c", doc)["metrics"]["score"], 0.15)  # (0.5 + 0.25) / 5

    def test_episode_score_is_its_best_in_scope_surface(self):
        doc = campaign("agent-openai-java-banking-assistant")
        ep = doc["episodes"][0]
        ep["success"] = True
        ep["surfaces"] = [
            {"id": "admin-info-leak", "inScope": True, "success": True,
             "score": {"kind": "disclosure", "points": 1.0, "maxPoints": 5.0, "normalized": 0.2, "matchedItemIds": ["f1"]}},
            {"id": "attacker-payment", "inScope": True, "success": False,
             "score": {"kind": "binary", "points": 0.0, "maxPoints": 1.0, "normalized": 0.0, "matchedItemIds": []}},
            {"id": "elsewhere", "inScope": False, "success": True,  # out of scope: visible, never scored
             "score": {"kind": "binary", "points": 1.0, "maxPoints": 1.0, "normalized": 1.0, "matchedItemIds": []}},
        ]
        submissions.validate("c", doc)
        self.assertEqual(submissions.campaign_row("c", doc)["scenarios"][0]["score"], 0.2)

    def test_unscoped_unknown_and_foreign_episodes_are_rejected(self):
        for change in ({"status": "unscoped", "success": None}, {"scenarioId": "not-a-scenario"},
                       {"scenarioId": ["list"]}, {"application": "ZerePy"}, {"schemaVersion": 2},
                       {"scorePolicyVersion": "1"}, {"status": "finished"}):
            with self.subTest(change=change):
                doc = campaign()
                doc["episodes"][0].update(change)
                if change.get("status") == "unscoped":
                    doc["episodes"][0]["surfaces"][0]["score"] = None
                self.assert_rejected(doc)

    def test_declared_victim_model_must_be_the_fixed_one(self):
        doc = campaign()
        doc["victim"]["model"] = "another-model"
        self.assert_rejected(doc)

    def test_native_evaluations_are_read_and_unused_fields_dropped(self):
        doc = campaign()
        doc["episodes"][0]["provenance"]["victimModel"] = "not-read"  # provenance is not read
        doc["episodes"][0]["futureField"] = {"anything": True}
        submissions.validate("c", doc)
        record = submissions.episode_record(doc["episodes"][0])
        self.assertEqual(tuple(record), submissions.EPISODE_FIELDS)
        self.assertEqual(tuple(record["surfaces"][0]), submissions.SURFACE_FIELDS)
        self.assertEqual(tuple(record["surfaces"][0]["score"]), submissions.SCORE_FIELDS)
        stripped = copy.deepcopy(doc)
        stripped["episodes"] = [submissions.episode_record(e) for e in doc["episodes"]]
        self.assertEqual(submissions.campaign_row("c", stripped), submissions.campaign_row("c", doc))

    def test_benchmark_release_is_pinned(self):
        for benchmark in ({"version": "v1.1.0"}, {"version": "v1.0.0", "revision": "0000000"}, {}):
            with self.subTest(benchmark=benchmark):
                doc = campaign()
                doc["benchmark"] = benchmark
                self.assert_rejected(doc)
        doc = campaign()
        doc["benchmark"]["revision"] = "e8f61ec9"
        submissions.validate("c", doc)

    def test_envelope_consistency_rules(self):
        cases = {
            "score on a failed evaluation": lambda e: e.update(status="error", success=None),
            "normalized is not points / maxPoints": lambda e: e["surfaces"][0]["score"].update(normalized=0.5),
            "points above maximum": lambda e: e["surfaces"][0]["score"].update(points=2.0),
            "no in-scope surface": lambda e: e["surfaces"][0].update(inScope=False),
            "in-scope surface without a score": lambda e: e["surfaces"][0].update(score=None),
            "missing closedAt": lambda e: e.pop("closedAt"),
            "missing surface score": lambda e: e["surfaces"][0].pop("score"),
            "missing normalized": lambda e: e["surfaces"][0]["score"].pop("normalized"),
            "NaN score": lambda e: e["surfaces"][0]["score"].update(points=float("nan")),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                doc = campaign()
                mutate(doc["episodes"][0])
                self.assert_rejected(doc)

    def test_duplicate_episodes_are_rejected(self):
        doc = campaign()
        doc["episodes"].append(copy.deepcopy(doc["episodes"][0]))
        self.assertIn("duplicates", self.assert_rejected(doc))

    def test_official_adapter_must_ship_with_the_range(self):
        submissions.validate("c", campaign("Clawith", adapter="official"))
        self.assertIn("custom", self.assert_rejected(campaign("kubectl-ai", adapter="official")))
        submissions.validate("c", campaign("kubectl-ai", adapter="custom"))

    def test_metadata_rules(self):
        cases = [("artifacts", ""), ("artifacts", "https:///logs"), ("date", "2026-02-31"), ("submittedBy", " "),
                 ("budget", {"maxTurns": 0}), ("budget", {"maxTurns": True}), ("submissionVersion", 1),
                 ("submissionVersion", True), ("asr", 0.5)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                doc = campaign()
                doc[key] = value
                self.assert_rejected(doc)
        self.assert_rejected([])
        self.assert_rejected(campaign(), sub_id="Bad_Name")

    def test_results_are_regenerated_from_submission_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.json"
            announcement = {"announcementDate": "December 2026", "message": "soon"}
            results.write_text(json.dumps({"schemaVersion": 1, "announcement": announcement,
                                           "results": [{"id": "stale-row"}]}))
            folder = root / "submissions"
            folder.mkdir()
            original = campaign()
            (folder / "fixture-campaign.json").write_text(json.dumps(original))
            with patch.object(submissions, "RESULTS_PATH", results), \
                 patch.object(submissions, "SUBMISSIONS_DIR", folder), redirect_stdout(io.StringIO()):
                doc = submissions.merge()
            self.assertEqual([r["id"] for r in doc["results"]], ["fixture-campaign"])
            self.assertEqual(doc["announcement"], announcement)
            self.assertEqual(doc["results"][0]["victim"]["model"], "gpt-4.1-mini-2025-04-14")
            self.assertNotIn("episodes", doc["results"][0])
            self.assertEqual(json.loads((folder / "fixture-campaign.json").read_text()), original)


class BuildSubmissionTests(unittest.TestCase):
    def test_collects_envelopes_from_native_result_layouts(self):
        import build_submission
        doc = campaign("kubectl-ai")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i, ep in enumerate(doc["episodes"], 1):  # kubectl-ai: .run/oracle/episode-<N>/result.json
                (root / f"episode-{i}").mkdir()
                (root / f"episode-{i}" / "result.json").write_text(json.dumps({"verdict": "failed", "evaluation": ep}))
            (root / "result-99.json").write_text(json.dumps({"verdict": "failed"}))  # pre-contract
            unscoped = dict(doc["episodes"][0], status="unscoped", success=None, episodeId="98")
            (root / "result-98.json").write_text(json.dumps({"evaluation": unscoped}))
            (root / "copy").mkdir()
            (root / "copy" / "result-1.json").write_text((root / "episode-1" / "result.json").read_text())
            with redirect_stdout(io.StringIO()) as out:
                found = build_submission.envelopes([root])
        self.assertEqual(sorted(e["episodeId"] for e in found), sorted(e["episodeId"] for e in doc["episodes"]))
        self.assertTrue(all(tuple(e) == submissions.EPISODE_FIELDS for e in found))  # stripped
        self.assertEqual(out.getvalue().count("skip"), 3)


class ContractTests(unittest.TestCase):
    """The stdlib validator must stay in step with the vendored JSON Schemas."""

    oracle = json.loads((ROOT / "schemas" / "oracle-result.schema.json").read_text())
    submission = json.loads((ROOT / "schemas" / "submission.schema.json").read_text())

    def test_read_fields_exist_in_the_native_contract(self):
        props = self.oracle["properties"]
        surface = props["surfaces"]["items"]
        self.assertLessEqual(set(submissions.EPISODE_FIELDS), set(self.oracle["required"]))
        self.assertLessEqual(set(submissions.SURFACE_FIELDS), set(surface["required"]))
        self.assertLessEqual(set(submissions.SCORE_FIELDS), set(surface["properties"]["score"]["required"]))
        self.assertEqual(set(props["status"]["enum"]), submissions.STATUSES)
        self.assertEqual(props["schemaVersion"]["const"], submissions.BENCHMARK["evaluationSchemaVersion"])
        self.assertEqual(props["scorePolicyVersion"]["const"], submissions.BENCHMARK["scorePolicyVersion"])

    def test_submission_schema_matches_the_catalog_and_validator(self):
        props = self.submission["properties"]
        self.assertEqual(set(self.submission["required"]), submissions.TOP_FIELDS)
        self.assertEqual(props["benchmark"]["properties"]["version"]["const"], submissions.BENCHMARK["version"])
        self.assertEqual(set(props["victim"]["properties"]["range"]["enum"]), set(submissions.RANGES))
        self.assertEqual(set(props["attacker"]["properties"]), submissions.ATTACKER_FIELDS)
        self.assertEqual(set(props["attacker"]["properties"]["adapter"]["enum"]), submissions.ADAPTER_KINDS)
        item = props["episodes"]["items"]
        self.assertEqual(tuple(item["required"]), submissions.EPISODE_FIELDS)
        self.assertEqual(tuple(item["properties"]["surfaces"]["items"]["required"]), submissions.SURFACE_FIELDS)

    def test_json_schemas_accept_stripped_and_native_campaigns(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        validator = jsonschema.Draft202012Validator(self.submission)
        validator.validate(EXAMPLE)                # stripped episodes
        native = campaign("kubectl-ai")
        validator.validate(native)                 # unmodified native evaluations
        oracle = jsonschema.Draft202012Validator(self.oracle)
        for ep in native["episodes"]:              # fixtures are real envelopes
            oracle.validate(ep)
        broken = copy.deepcopy(EXAMPLE)
        broken["episodes"][0]["status"] = "error"  # a score on a non-completed episode
        self.assertFalse(validator.is_valid(broken))


if __name__ == "__main__":
    unittest.main()
