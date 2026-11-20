import tempfile
import unittest
from pathlib import Path

from transit_analysis.loader import load_dataset
from transit_analysis.scenarios import evaluate_proposal, load_proposal
from transit_analysis.store import list_proposals, load_saved_proposal, save_proposal

ROOT = Path(__file__).resolve().parents[1]


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "data")
        cls.proposal = load_proposal(ROOT / "examples" / "proposal_replace_b02.json")
        cls.report = evaluate_proposal(cls.dataset, cls.proposal)

    def test_save_list_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_proposal(tmp, self.proposal, self.dataset.version, self.report)
            self.assertTrue(path.is_file())

            rows = list_proposals(tmp)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["proposal_id"], "P-2026-05-01")
            self.assertEqual(row["dataset_version"], "data")
            self.assertEqual(row["violations"], 0)
            self.assertFalse(row["coverage_harmed"])

            saved = load_saved_proposal(tmp, "P-2026-05-01")
            self.assertEqual(saved["dataset_version"], "data")
            self.assertEqual(saved["actions"], self.proposal.actions)
            self.assertIn("saved_at", saved)
            self.assertIn("evaluation", saved)

    def test_review_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_proposals(tmp), [])
            self.assertEqual(list_proposals(Path(tmp) / "nonexistent"), [])

    def test_missing_saved_proposal_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_saved_proposal(tmp, "NOPE")


if __name__ == "__main__":
    unittest.main()
