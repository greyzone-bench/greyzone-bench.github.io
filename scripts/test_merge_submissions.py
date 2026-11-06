"""Offline submission checks for the fixed-model benchmark leaderboard."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import merge_submissions as submissions


def campaign(victim_range='shopware-claude-commerce'):
    return {
        'attacker': {'framework': 'pyrit', 'model': 'fixture-attacker'},
        'victim': {'range': victim_range},
        'episodes': 10,
        'asr': 0.5,
        'authenticity': None,
        'controlFalsePositive': 0.0,
        'noReplyRate': 0.0,
        'submittedBy': 'fixture-lab',
        'date': '2026-12-01',
        'artifacts': 'https://example.org/fixture-logs',
    }


class SubmissionTests(unittest.TestCase):
    def assert_rejected(self, row):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            submissions.validate('fixture-campaign', row)

    def test_every_range_supplies_its_fixed_victim_model(self):
        for name, model in submissions.VICTIM_MODELS.items():
            with self.subTest(victim_range=name):
                row = campaign(name)
                submissions.validate('fixture-campaign', row)
                self.assertEqual(row['victim']['model'], model)

    def test_explicit_matching_model_is_accepted(self):
        row = campaign()
        row['victim']['model'] = 'claude-haiku-4-5-20251001'
        submissions.validate('fixture-campaign', row)

    def test_conflicting_model_and_unknown_range_are_rejected(self):
        row = campaign()
        row['victim']['model'] = 'another-model'
        self.assert_rejected(row)
        self.assert_rejected(campaign('unknown-range'))

    def test_artifacts_and_real_calendar_dates_are_required(self):
        for key, value in [('artifacts', ''), ('artifacts', 'https:///logs'), ('date', '2026-02-31')]:
            with self.subTest(key=key, value=value):
                row = campaign()
                row[key] = value
                self.assert_rejected(row)

    def test_boolean_metrics_and_non_object_submissions_are_rejected(self):
        self.assert_rejected([])
        for key in ['episodes', 'asr', 'controlFalsePositive']:
            row = campaign()
            row[key] = True
            self.assert_rejected(row)

    def test_merge_records_the_model_without_modifying_the_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / 'results.json'
            results.write_text(json.dumps({'schemaVersion': 1, 'results': []}))
            folder = root / 'submissions'
            folder.mkdir()
            source = folder / 'fixture-campaign.json'
            original = campaign()
            source.write_text(json.dumps(original))
            with patch.object(submissions, 'RESULTS_PATH', results), \
                 patch.object(submissions, 'SUBMISSIONS_DIR', folder), redirect_stdout(io.StringIO()):
                doc = submissions.merge()
            self.assertEqual(doc['results'][0]['victim']['model'], 'claude-haiku-4-5-20251001')
            self.assertEqual(json.loads((folder / 'fixture-campaign.json').read_text()), original)

    def test_existing_results_are_not_relabelled_when_a_baseline_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = campaign()
            row['id'] = 'fixture-campaign'
            row['victim']['model'] = 'historical-model'
            results = root / 'results.json'
            results.write_text(json.dumps({'results': [row]}))
            with patch.object(submissions, 'RESULTS_PATH', results), \
                 patch.object(submissions, 'SUBMISSIONS_DIR', root), \
                 redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                submissions.merge()


if __name__ == '__main__':
    unittest.main()
