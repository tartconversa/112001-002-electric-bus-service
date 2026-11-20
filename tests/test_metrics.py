import tempfile
import unittest
from pathlib import Path

from transit_analysis.loader import load_dataset
from transit_analysis.metrics import compute_metrics

from helpers import write_dataset

ROOT = Path(__file__).resolve().parents[1]


def only(metrics, route_id):
    rows = [m for m in metrics if m.route_id == route_id]
    assert len(rows) == 1, f"expected single interval for {route_id}"
    return rows[0]


class BaseFixtureMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = compute_metrics(load_dataset(ROOT / "data"))
        cls.r1 = only(cls.metrics, "R1")

    def test_trip_totals_and_reliability(self):
        self.assertEqual(self.r1.scheduled_trips, 44)
        self.assertEqual(self.r1.completed_trips, 41)
        self.assertEqual(self.r1.cancelled_trips, 3)
        self.assertAlmostEqual(self.r1.reliability, 41 / 44)

    def test_maintenance_reduces_available_capacity(self):
        # B02 04-02 维修 95 分钟：78 × (1 - 95/720)
        expected = 80 + 78 * (1 - 95 / 720) + 80 + 80 + 78 + 80
        self.assertAlmostEqual(self.r1.available_capacity, expected, places=6)

    def test_electrification_is_capacity_weighted_not_vehicle_count(self):
        # 台数口径为 2/3，载客能力口径为 320/465.708...
        count_share = 2 / 3
        self.assertAlmostEqual(
            self.r1.electric_capacity_share, 320 / self.r1.available_capacity, places=6
        )
        self.assertGreater(abs(self.r1.electric_capacity_share - count_share), 0.01)

    def test_zero_emission_shares_use_two_denominators(self):
        self.assertAlmostEqual(self.r1.zero_emission_completed_share, 1840 / 3244, places=6)
        self.assertAlmostEqual(self.r1.zero_emission_scheduled_share, 1920 / 3480, places=6)

    def test_emissions_and_intensity_pair(self):
        self.assertAlmostEqual(self.r1.emissions_kg, 188 * 0.55 + 18 * 18.0, places=6)
        self.assertAlmostEqual(self.r1.intensity_per_completed_trip, 427.4 / 41, places=6)
        self.assertAlmostEqual(self.r1.intensity_per_scheduled_trip, 427.4 / 44, places=6)

    def test_missing_operations_marks_interval_provisional(self):
        kinds = [e.kind for e in self.r1.exceptions]
        self.assertIn("MISSING_OPERATIONS", kinds)
        missing = [e for e in self.r1.exceptions if e.kind == "MISSING_OPERATIONS"]
        self.assertEqual(len(missing), 1)
        self.assertIn("B04", missing[0].refs)
        self.assertIn("PROVISIONAL_DATA", self.r1.comparability)

    def test_coverage_shortfall_is_per_day_period_cell(self):
        # R1 PM 04-02 完成 8 < 目标 9 → 1 个缺口单元；其余格达成
        self.assertEqual(self.r1.coverage_required, 40)
        self.assertEqual(self.r1.shortfall_cells, 1)
        self.assertFalse(self.r1.coverage_met)
        shortfalls = [e for e in self.r1.exceptions if e.kind == "SERVICE_SHORTFALL"]
        self.assertEqual(len(shortfalls), 1)
        self.assertIn("2026-04-02", shortfalls[0].refs)

    def test_drill_down_references_present(self):
        self.assertEqual(self.r1.trip_ids, ["T101", "T102", "T103", "T104"])
        self.assertEqual(self.r1.vehicle_ids, ["B01", "B02", "B04"])

    def test_route_change_boundary_and_no_data_flags(self):
        r2 = [m for m in self.metrics if m.route_id == "R2"]
        self.assertEqual(len(r2), 2)
        first, second = r2
        self.assertIn("ROUTE_CHANGE_BOUNDARY", first.comparability)
        self.assertEqual(first.shortfall_cells, 2)  # PM 两日均未达 7 班
        self.assertIn("NO_DATA", second.comparability)
        self.assertIsNone(second.reliability)


class CancellationNotCountedAsImprovementTests(unittest.TestCase):
    """削减柴油班次不得被记作零排放效率提升。"""

    def _metrics(self, completed_diesel):
        service = (
            "trip_id,route_id,service_date,period,scheduled,completed,vehicle_id\n"
            "T1,R,2026-04-02,AM,10,10,E1\n"
            f"T2,R,2026-04-02,PM,10,{completed_diesel},D1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            dataset = load_dataset(write_dataset(Path(tmp), {"service.csv": service}))
            return only(compute_metrics(dataset), "R")

    def test_cancelled_trips_do_not_raise_scheduled_basis_share(self):
        full = self._metrics(10)
        cut = self._metrics(2)
        # 完成口径被粉饰：取消柴油班次后零排放占比上升
        self.assertGreater(cut.zero_emission_completed_share, full.zero_emission_completed_share)
        # 计划口径不变：取消班次不被记作零排放服务
        self.assertAlmostEqual(
            cut.zero_emission_scheduled_share, full.zero_emission_scheduled_share
        )
        self.assertAlmostEqual(full.zero_emission_scheduled_share, 0.5)
        # 服务损失同时可见
        self.assertLess(cut.reliability, full.reliability)
        self.assertEqual(cut.cancelled_trips, 8)

    def test_intensity_pair_exposes_cancellation(self):
        cut = self._metrics(2)
        # 完成口径强度 = (80×0.55 + 2×18) / 12；计划口径分母保持 20
        self.assertAlmostEqual(cut.intensity_per_completed_trip, (44 + 36) / 12, places=6)
        self.assertAlmostEqual(cut.intensity_per_scheduled_trip, (44 + 36) / 20, places=6)


class DowntimeAndReplacementWindowTests(unittest.TestCase):
    def test_inactive_vehicle_not_counted_in_capacity(self):
        vehicles = (
            "vehicle_id,route_id,powertrain,battery_kwh,capacity,active_from,active_to\n"
            "E1,R,battery_electric,300,80,2026-01-01,\n"
            "D1,R,diesel,0,80,2026-01-01,2026-04-01\n"  # 服务日前一天退役
        )
        with tempfile.TemporaryDirectory() as tmp:
            dataset = load_dataset(write_dataset(Path(tmp), {"vehicles.csv": vehicles}))
            m = only(compute_metrics(dataset), "R")
        # 仅 E1 计入可用运力；D1 的班次被标记用车不在役
        self.assertAlmostEqual(m.available_capacity, 80.0)
        kinds = [e.kind for e in m.exceptions]
        self.assertIn("VEHICLE_INACTIVE_FOR_TRIP", kinds)

    def test_full_day_maintenance_zeroes_vehicle_capacity(self):
        operations = (
            "vehicle_id,date,charge_kwh,maintenance_minutes,reason\n"
            "E1,2026-04-02,80,720,depot_repair\n"
            "D1,2026-04-02,0,0,\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            dataset = load_dataset(write_dataset(Path(tmp), {"operations.csv": operations}))
            m = only(compute_metrics(dataset), "R")
        self.assertAlmostEqual(m.available_capacity, 80.0)  # 只剩 D1
        self.assertAlmostEqual(m.electric_capacity_share, 0.0)


if __name__ == "__main__":
    unittest.main()
