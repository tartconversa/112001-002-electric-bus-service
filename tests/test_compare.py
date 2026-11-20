import unittest
from pathlib import Path

from transit_analysis.compare import compare_datasets
from transit_analysis.loader import load_dataset

ROOT = Path(__file__).resolve().parents[1]


class CompareVersionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = load_dataset(ROOT / "data")
        cls.revised = load_dataset(ROOT / "data" / "corrections_2026_05")
        cls.comparison = compare_datasets(cls.baseline, cls.revised)

    def test_late_maintenance_record_is_listed(self):
        text = "\n".join(self.comparison.record_diffs)
        self.assertIn("B01", text)
        self.assertIn("维修300分钟", text)
        self.assertIn("B04", text)

    def test_corrected_interval_keeps_both_readings(self):
        row = next(r for r in self.comparison.rows if r.route_id == "R1")
        self.assertEqual(row.status, "CORRECTED")
        changes = {c.field: c for c in row.changes}
        # 原始观测与更正后解释同时保留
        self.assertAlmostEqual(changes["available_capacity"].baseline, 465.708333, places=4)
        self.assertAlmostEqual(changes["available_capacity"].revised, 432.375, places=4)
        self.assertAlmostEqual(changes["emissions_kg"].baseline, 427.4, places=4)
        self.assertAlmostEqual(changes["emissions_kg"].revised, 509.9, places=4)

    def test_provisional_flag_resolved_after_correction(self):
        row = next(r for r in self.comparison.rows if r.route_id == "R1")
        self.assertIn("PROVISIONAL_DATA", row.baseline_flags)
        self.assertNotIn("PROVISIONAL_DATA", row.revised_flags)

    def test_untouched_route_intervals_unchanged(self):
        r2_rows = [r for r in self.comparison.rows if r.route_id == "R2"]
        self.assertTrue(all(r.status == "UNCHANGED" for r in r2_rows))

    def test_self_comparison_has_no_changes(self):
        same = compare_datasets(self.baseline, load_dataset(ROOT / "data"))
        self.assertFalse(same.changed)


if __name__ == "__main__":
    unittest.main()
