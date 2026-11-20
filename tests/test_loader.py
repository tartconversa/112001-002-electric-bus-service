import tempfile
import unittest
from pathlib import Path

from transit_analysis.loader import DatasetError, load_dataset

from helpers import MINIMAL_FILES, write_dataset

ROOT = Path(__file__).resolve().parents[1]


class LoadDatasetTests(unittest.TestCase):
    def test_load_base_fixture_dataset(self):
        dataset = load_dataset(ROOT / "data")
        self.assertEqual(dataset.version, "data")
        self.assertEqual(len(dataset.vehicles), 5)
        self.assertEqual(len(dataset.routes), 3)
        self.assertEqual(len(dataset.trips), 7)
        self.assertEqual(len(dataset.operations), 6)
        self.assertEqual(len(dataset.depots), 4)
        self.assertEqual(len(dataset.targets), 4)
        self.assertEqual(dataset.issues, [])

    def test_missing_file_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in MINIMAL_FILES.items():
                if name != "routes.csv":
                    (root / name).write_text(content, encoding="utf-8")
            with self.assertRaises(DatasetError) as ctx:
                load_dataset(root)
            self.assertTrue(any("routes.csv" in issue for issue in ctx.exception.issues))

    def test_invalid_value_reports_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_dataset(
                Path(tmp),
                {
                    "vehicles.csv": (
                        "vehicle_id,route_id,powertrain,battery_kwh,capacity,active_from,active_to\n"
                        "E1,R,battery_electric,300,abc,2026-01-01,\n"
                    )
                },
            )
            with self.assertRaises(DatasetError) as ctx:
                load_dataset(root)
            self.assertTrue(any("capacity" in issue or "abc" in issue for issue in ctx.exception.issues))

    def test_completed_greater_than_scheduled_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_dataset(
                Path(tmp),
                {
                    "service.csv": (
                        "trip_id,route_id,service_date,period,scheduled,completed,vehicle_id\n"
                        "T1,R,2026-04-02,AM,5,9,E1\n"
                    )
                },
            )
            with self.assertRaises(DatasetError):
                load_dataset(root)

    def test_unknown_vehicle_reference_is_non_fatal_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_dataset(
                Path(tmp),
                {
                    "service.csv": (
                        "trip_id,route_id,service_date,period,scheduled,completed,vehicle_id\n"
                        "T1,R,2026-04-02,AM,10,10,GHOST\n"
                    )
                },
            )
            dataset = load_dataset(root)
            kinds = [issue.kind for issue in dataset.issues]
            self.assertIn("UNKNOWN_VEHICLE", kinds)

    def test_duplicate_vehicle_id_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_dataset(
                Path(tmp),
                {
                    "vehicles.csv": (
                        "vehicle_id,route_id,powertrain,battery_kwh,capacity,active_from,active_to\n"
                        "E1,R,battery_electric,300,80,2026-01-01,\n"
                        "E1,R,diesel,0,80,2026-01-01,\n"
                    )
                },
            )
            with self.assertRaises(DatasetError):
                load_dataset(root)

    def test_multiple_operation_records_same_day_are_kept(self):
        dataset = load_dataset(ROOT / "data" / "corrections_2026_05")
        import datetime

        records = dataset.operations_for("B01", datetime.date(2026, 4, 2))
        self.assertEqual(len(records), 2)
        self.assertEqual(dataset.maintenance_minutes("B01", datetime.date(2026, 4, 2)), 300)


if __name__ == "__main__":
    unittest.main()
