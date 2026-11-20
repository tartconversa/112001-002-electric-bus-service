import unittest
from datetime import date
from pathlib import Path

from transit_analysis.intervals import build_intervals
from transit_analysis.loader import load_dataset

ROOT = Path(__file__).resolve().parents[1]


class IntervalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "data")
        cls.intervals = build_intervals(cls.dataset)

    def test_stable_route_yields_single_full_month_interval(self):
        r1 = [i for i in self.intervals if i.route_id == "R1"]
        self.assertEqual(len(r1), 1)
        self.assertEqual(r1[0].start, date(2026, 4, 1))
        self.assertEqual(r1[0].end, date(2026, 4, 30))
        self.assertFalse(r1[0].route_change_bounded)

    def test_route_adjustment_splits_month(self):
        r2 = [i for i in self.intervals if i.route_id == "R2"]
        self.assertEqual(len(r2), 2)
        first, second = r2
        self.assertEqual((first.start, first.end), (date(2026, 4, 1), date(2026, 4, 14)))
        self.assertEqual((second.start, second.end), (date(2026, 4, 15), date(2026, 4, 30)))
        self.assertTrue(first.route_change_bounded)
        self.assertTrue(second.route_change_bounded)
        self.assertNotEqual(first.route_name, second.route_name)

    def test_empty_dataset_yields_no_intervals(self):
        dataset = load_dataset(ROOT / "data")
        dataset.trips = []
        self.assertEqual(build_intervals(dataset), [])


if __name__ == "__main__":
    unittest.main()
