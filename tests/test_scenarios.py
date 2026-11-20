import json
import tempfile
import unittest
from pathlib import Path

from transit_analysis.loader import load_dataset
from transit_analysis.scenarios import (
    ProposalError,
    apply_proposal,
    evaluate_proposal,
    load_proposal,
    validate_proposal,
)
from transit_analysis.scenarios import Proposal

from helpers import write_dataset

ROOT = Path(__file__).resolve().parents[1]


def make_proposal(actions, proposal_id="P-TEST"):
    return Proposal.from_dict({"proposal_id": proposal_id, "title": "测试", "actions": actions})


class ProposalFileTests(unittest.TestCase):
    def test_load_example_proposals(self):
        for name in ("proposal_replace_b02", "proposal_retire_b02", "proposal_charge_plan"):
            proposal = load_proposal(ROOT / "examples" / f"{name}.json")
            self.assertTrue(proposal.proposal_id)
            self.assertTrue(proposal.actions)

    def test_missing_actions_rejected(self):
        with self.assertRaises(ProposalError):
            Proposal.from_dict({"proposal_id": "X", "actions": []})

    def test_unknown_action_type_rejected(self):
        with self.assertRaises(ProposalError):
            Proposal.from_dict(
                {"proposal_id": "X", "actions": [{"type": "teleport_vehicle"}]}
            )

    def test_bad_charge_entry_rejected(self):
        with self.assertRaises(ProposalError):
            make_proposal(
                [
                    {
                        "type": "charging_plan",
                        "depot_id": "D1",
                        "entries": [{"vehicle_id": "B01", "date": "2026-04-02", "period": "AM", "kwh": -5}],
                    }
                ]
            )


class ReplaceAndRetireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "data")

    def test_replace_reassigns_trips_and_windows(self):
        proposal = make_proposal(
            [
                {
                    "type": "replace_vehicle",
                    "vehicle_id": "B02",
                    "effective_from": "2026-04-01",
                    "with": {
                        "vehicle_id": "B06",
                        "powertrain": "battery_electric",
                        "battery_kwh": 320,
                        "capacity": 78,
                    },
                }
            ]
        )
        scenario = apply_proposal(self.dataset, proposal)
        import datetime

        self.assertEqual(scenario.vehicle("B02").active_to, datetime.date(2026, 3, 31))
        self.assertEqual(scenario.vehicle("B06").route_id, "R1")
        reassigned = {t.trip_id: t.vehicle_id for t in scenario.trips}
        self.assertEqual(reassigned["T102"], "B06")
        self.assertEqual(reassigned["T104"], "B06")
        self.assertEqual(reassigned["T101"], "B01")
        # 原始数据集不被修改
        self.assertIsNone(self.dataset.vehicle("B02").active_to)

    def test_replace_impact_electrifies_without_coverage_harm(self):
        proposal = load_proposal(ROOT / "examples" / "proposal_replace_b02.json")
        report = evaluate_proposal(self.dataset, proposal)
        self.assertEqual(report.violations, [])
        self.assertFalse(report.coverage_harmed)
        r1 = next(r for r in report.route_impacts if r.route_id == "R1")
        self.assertEqual(r1.electric_capacity_share_after, 1.0)
        self.assertEqual(r1.at_risk_trips, [])
        self.assertLess(r1.emissions_projected_after, r1.emissions_projected_before)

    def test_retire_without_replacement_harms_coverage(self):
        proposal = load_proposal(ROOT / "examples" / "proposal_retire_b02.json")
        report = evaluate_proposal(self.dataset, proposal)
        self.assertTrue(report.coverage_harmed)
        r1 = next(r for r in report.route_impacts if r.route_id == "R1")
        self.assertEqual(r1.at_risk_trips, ["T102", "T104"])
        self.assertEqual(r1.peak_at_risk_scheduled, 20)
        self.assertEqual(len(r1.coverage_cells_newly_short), 2)

    def test_unknown_vehicle_reference_is_violation(self):
        proposal = make_proposal(
            [{"type": "retire_vehicle", "vehicle_id": "GHOST", "effective_from": "2026-04-02"}]
        )
        kinds = [v.kind for v in validate_proposal(self.dataset, proposal)]
        self.assertIn("UNKNOWN_VEHICLE", kinds)


class ChargingPlanConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "data")

    def violations_for(self, entries, depot="D1"):
        proposal = make_proposal(
            [{"type": "charging_plan", "depot_id": depot, "entries": entries}]
        )
        return validate_proposal(self.dataset, proposal)

    def test_valid_plan_has_no_violations(self):
        proposal = load_proposal(ROOT / "examples" / "proposal_charge_plan.json")
        self.assertEqual(validate_proposal(self.dataset, proposal), [])

    def test_ports_exceeded(self):
        # 三辆电动车同挤一个 2 接口时段
        vehicles = (
            "vehicle_id,route_id,powertrain,battery_kwh,capacity,active_from,active_to\n"
            "E1,R,battery_electric,300,80,2026-01-01,\n"
            "E2,R,battery_electric,300,80,2026-01-01,\n"
            "E3,R,battery_electric,300,80,2026-01-01,\n"
        )
        depots = (
            "depot_id,route_id,period,charger_ports,available_kwh,assigned_vehicle_ids\n"
            "DP,R,AM,2,5000,E1|E2|E3\n"
        )
        service = (
            "trip_id,route_id,service_date,period,scheduled,completed,vehicle_id\n"
            "T1,R,2026-04-02,AM,10,10,E1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            dataset = load_dataset(
                write_dataset(
                    Path(tmp),
                    {"vehicles.csv": vehicles, "depot_constraints.csv": depots, "service.csv": service},
                )
            )
            proposal = make_proposal(
                [
                    {
                        "type": "charging_plan",
                        "depot_id": "DP",
                        "entries": [
                            {"vehicle_id": v, "date": "2026-04-03", "period": "AM", "kwh": 50}
                            for v in ("E1", "E2", "E3")
                        ],
                    }
                ]
            )
            kinds = [v.kind for v in validate_proposal(dataset, proposal)]
        self.assertIn("DEPOT_PORTS_EXCEEDED", kinds)

    def test_duplicate_charge_entry_same_slot(self):
        entries = [
            {"vehicle_id": "B01", "date": "2026-04-03", "period": "PM", "kwh": 100},
            {"vehicle_id": "B01", "date": "2026-04-03", "period": "PM", "kwh": 80},
        ]
        kinds = [v.kind for v in self.violations_for(entries)]
        self.assertIn("DUPLICATE_CHARGE_ENTRY", kinds)

    def test_energy_budget_exceeded(self):
        entries = [{"vehicle_id": "B01", "date": "2026-04-03", "period": "PM", "kwh": 600}]
        kinds = [v.kind for v in self.violations_for(entries)]
        self.assertIn("DEPOT_ENERGY_EXCEEDED", kinds)

    def test_charge_conflicts_with_trip_same_slot(self):
        entries = [{"vehicle_id": "B01", "date": "2026-04-02", "period": "AM", "kwh": 100}]
        violations = self.violations_for(entries)
        kinds = [v.kind for v in violations]
        self.assertIn("CHARGE_TRIP_CONFLICT", kinds)

    def test_non_electric_vehicle_rejected(self):
        entries = [{"vehicle_id": "B02", "date": "2026-04-03", "period": "PM", "kwh": 100}]
        kinds = [v.kind for v in self.violations_for(entries)]
        self.assertIn("NON_ELECTRIC_VEHICLE", kinds)

    def test_vehicle_not_registered_at_depot_slot(self):
        # B05 属于 R2，未登记在 D1(R1) AM
        entries = [{"vehicle_id": "B05", "date": "2026-04-02", "period": "AM", "kwh": 100}]
        kinds = [v.kind for v in self.violations_for(entries)]
        self.assertIn("VEHICLE_NOT_ASSIGNED_TO_DEPOT", kinds)


class DoubleBookingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "data")

    def test_same_vehicle_same_slot_two_trips_rejected(self):
        # B03 在 2026-04-02 AM 已有 T201，再把 T101 改派给 B03 → 同时段重复
        proposal = make_proposal(
            [{"type": "assign_trip", "trip_id": "T101", "vehicle_id": "B03"}]
        )
        violations = validate_proposal(self.dataset, proposal)
        kinds = [v.kind for v in violations]
        self.assertIn("DOUBLE_BOOKING", kinds)

    def test_assign_to_inactive_vehicle_rejected(self):
        proposal = make_proposal(
            [
                {"type": "retire_vehicle", "vehicle_id": "B04", "effective_from": "2026-04-01"},
                {"type": "assign_trip", "trip_id": "T101", "vehicle_id": "B04"},
            ]
        )
        kinds = [v.kind for v in validate_proposal(self.dataset, proposal)]
        self.assertIn("ASSIGN_INACTIVE_VEHICLE", kinds)

    def test_reassign_within_same_slot_allowed(self):
        # T101 改派给 B04：B04 在 2026-04-02 AM 无班次
        proposal = make_proposal(
            [{"type": "assign_trip", "trip_id": "T101", "vehicle_id": "B04"}]
        )
        self.assertEqual(validate_proposal(self.dataset, proposal), [])


if __name__ == "__main__":
    unittest.main()
