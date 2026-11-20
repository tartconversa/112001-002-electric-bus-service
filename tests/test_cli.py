import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from transit_analysis.cli import main

ROOT = Path(__file__).resolve().parents[1]
DATA = str(ROOT / "data")


def run_cli(argv):
    buffer = StringIO()
    with patch("sys.stdout", buffer):
        code = main(argv)
    return code, buffer.getvalue()


class CliTests(unittest.TestCase):
    def test_validate_clean_dataset(self):
        code, out = run_cli(["validate", "--data", DATA])
        self.assertEqual(code, 0)
        self.assertIn("未发现引用问题", out)

    def test_report_json_contains_drill_down(self):
        code, out = run_cli(["report", "--data", DATA, "--route", "R1", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload), 1)
        row = payload[0]
        self.assertEqual(row["route_id"], "R1")
        self.assertEqual(row["trip_ids"], ["T101", "T102", "T103", "T104"])
        kinds = [e["kind"] for e in row["exceptions"]]
        self.assertIn("MISSING_OPERATIONS", kinds)

    def test_compare_lists_record_diffs(self):
        code, out = run_cli(
            ["compare", "--data", DATA, "--other", str(ROOT / "data" / "corrections_2026_05")]
        )
        self.assertEqual(code, 0)
        self.assertIn("维修300分钟", out)
        self.assertIn("已更正", out)

    def test_propose_valid_returns_zero(self):
        code, _ = run_cli(
            ["propose", "--data", DATA, "--proposal", str(ROOT / "examples" / "proposal_replace_b02.json")]
        )
        self.assertEqual(code, 0)

    def test_propose_with_violations_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "proposal_id": "P-BAD",
                        "actions": [
                            {
                                "type": "charging_plan",
                                "depot_id": "D1",
                                "entries": [
                                    {"vehicle_id": "B01", "date": "2026-04-02", "period": "AM", "kwh": 100}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            code, out = run_cli(["propose", "--data", DATA, "--proposal", str(path)])
            self.assertEqual(code, 1)
            self.assertIn("CHARGE_TRIP_CONFLICT", out)

    def test_save_refuses_invalid_proposal_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "proposal_id": "P-BAD",
                        "actions": [
                            {"type": "retire_vehicle", "vehicle_id": "GHOST", "effective_from": "2026-04-02"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = Path(tmp) / "store"
            code, _ = run_cli(
                ["save", "--data", DATA, "--proposal", str(path), "--store", str(store)]
            )
            self.assertEqual(code, 1)
            self.assertEqual(list(store.glob("*.json")), [])
            code, _ = run_cli(
                ["save", "--data", DATA, "--proposal", str(path), "--store", str(store), "--force"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(list(store.glob("*.json"))), 1)

    def test_save_then_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run_cli(
                [
                    "save",
                    "--data",
                    DATA,
                    "--proposal",
                    str(ROOT / "examples" / "proposal_replace_b02.json"),
                    "--store",
                    tmp,
                ]
            )
            self.assertEqual(code, 0)
            code, out = run_cli(["review", "--store", tmp])
            self.assertEqual(code, 0)
            self.assertIn("P-2026-05-01", out)
            self.assertIn("data", out)

    def test_invalid_dataset_returns_two(self):
        code, _ = run_cli(["validate", "--data", "/nonexistent"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
