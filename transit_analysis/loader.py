"""数据集载入：一个目录即一个资料版本。

数据集由六个 CSV 文件组成（见 data/README.md）。结构或取值非法时抛出
DatasetError（汇总全部问题）；引用完整性问题（如班次指向未知车辆）不
阻断载入，而是记录在 Dataset.issues 中，随报表一同呈现，以便区分
“数据缺失”与“真实为零”。
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import (
    CoverageTarget,
    Dataset,
    DepotConstraint,
    Issue,
    OperationRecord,
    RouteVersion,
    TripRecord,
    Vehicle,
)

REQUIRED_FILES = (
    "vehicles.csv",
    "routes.csv",
    "service.csv",
    "operations.csv",
    "depot_constraints.csv",
    "coverage_targets.csv",
)

POWERTRAINS = {"battery_electric", "diesel", "hybrid"}


class DatasetError(Exception):
    """数据集结构或取值非法；issues 为全部问题的列表。"""

    def __init__(self, issues):
        self.issues = [str(issue) for issue in issues]
        super().__init__("; ".join(self.issues))


def _fail(ctx, errors, message):
    errors.append(f"{ctx}: {message}")


def _req(row, key, ctx, errors):
    value = (row.get(key) or "").strip()
    if not value:
        _fail(ctx, errors, f"缺少必填字段 {key}")
    return value


def _opt(row, key):
    return (row.get(key) or "").strip()


def _as_date(value, ctx, errors):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(ctx, errors, f"日期格式非法 {value!r}")
        return None


def _as_int(value, ctx, errors, minimum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        _fail(ctx, errors, f"整数格式非法 {value!r}")
        return 0
    if minimum is not None and number < minimum:
        _fail(ctx, errors, f"数值 {number} 小于下限 {minimum}")
    return number


def _as_float(value, ctx, errors, minimum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(ctx, errors, f"数值格式非法 {value!r}")
        return 0.0
    if minimum is not None and number < minimum:
        _fail(ctx, errors, f"数值 {number} 小于下限 {minimum}")
    return number


def _as_bool(value, ctx, errors):
    text = value.strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", ""}:
        return False
    _fail(ctx, errors, f"布尔格式非法 {value!r}")
    return False


def _rows(path, expected_headers, errors):
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            missing = [h for h in expected_headers if h not in headers]
            if missing:
                _fail(path.name, errors, f"缺少列 {', '.join(missing)}")
                return []
            return list(reader)
    except OSError as exc:
        _fail(path.name, errors, f"无法读取 {exc}")
        return []


def load_dataset(source, version=None) -> Dataset:
    root = Path(source)
    errors = []
    if not root.is_dir():
        raise DatasetError([f"数据目录不存在: {root}"])
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            _fail(name, errors, "缺少数据文件")
    if errors:
        raise DatasetError(errors)

    vehicles = []
    for i, row in enumerate(
        _rows(
            root / "vehicles.csv",
            ["vehicle_id", "route_id", "powertrain", "battery_kwh", "capacity", "active_from", "active_to"],
            errors,
        ),
        start=2,
    ):
        ctx = f"vehicles.csv 第{i}行"
        powertrain = _req(row, "powertrain", ctx, errors)
        if powertrain and powertrain not in POWERTRAINS:
            _fail(ctx, errors, f"未知动力类型 {powertrain!r}")
        capacity = _as_float(_req(row, "capacity", ctx, errors), ctx, errors, minimum=0)
        if capacity <= 0:
            _fail(ctx, errors, "capacity 必须为正数")
        active_from = _as_date(_req(row, "active_from", ctx, errors), ctx, errors)
        active_to = _as_date(_opt(row, "active_to"), ctx, errors)
        if active_from and active_to and active_to < active_from:
            _fail(ctx, errors, "active_to 早于 active_from")
        vehicles.append(
            Vehicle(
                vehicle_id=_req(row, "vehicle_id", ctx, errors),
                route_id=_req(row, "route_id", ctx, errors),
                powertrain=powertrain,
                battery_kwh=_as_float(_req(row, "battery_kwh", ctx, errors), ctx, errors, minimum=0),
                capacity=capacity,
                active_from=active_from or date.min,
                active_to=active_to,
            )
        )

    routes = []
    for i, row in enumerate(
        _rows(root / "routes.csv", ["route_id", "route_name", "effective_from", "effective_to"], errors),
        start=2,
    ):
        ctx = f"routes.csv 第{i}行"
        eff_from = _as_date(_req(row, "effective_from", ctx, errors), ctx, errors)
        eff_to = _as_date(_opt(row, "effective_to"), ctx, errors)
        if eff_from and eff_to and eff_to < eff_from:
            _fail(ctx, errors, "effective_to 早于 effective_from")
        routes.append(
            RouteVersion(
                route_id=_req(row, "route_id", ctx, errors),
                route_name=_req(row, "route_name", ctx, errors),
                effective_from=eff_from or date.min,
                effective_to=eff_to,
            )
        )

    trips = []
    for i, row in enumerate(
        _rows(
            root / "service.csv",
            ["trip_id", "route_id", "service_date", "period", "scheduled", "completed", "vehicle_id"],
            errors,
        ),
        start=2,
    ):
        ctx = f"service.csv 第{i}行"
        scheduled = _as_int(_req(row, "scheduled", ctx, errors), ctx, errors, minimum=0)
        completed = _as_int(_req(row, "completed", ctx, errors), ctx, errors, minimum=0)
        if completed > scheduled:
            _fail(ctx, errors, f"completed({completed}) 大于 scheduled({scheduled})")
        trips.append(
            TripRecord(
                trip_id=_req(row, "trip_id", ctx, errors),
                route_id=_req(row, "route_id", ctx, errors),
                service_date=_as_date(_req(row, "service_date", ctx, errors), ctx, errors) or date.min,
                period=_req(row, "period", ctx, errors),
                scheduled=scheduled,
                completed=completed,
                vehicle_id=_req(row, "vehicle_id", ctx, errors),
            )
        )

    operations = []
    for i, row in enumerate(
        _rows(root / "operations.csv", ["vehicle_id", "date", "charge_kwh", "maintenance_minutes", "reason"], errors),
        start=2,
    ):
        ctx = f"operations.csv 第{i}行"
        operations.append(
            OperationRecord(
                vehicle_id=_req(row, "vehicle_id", ctx, errors),
                day=_as_date(_req(row, "date", ctx, errors), ctx, errors) or date.min,
                charge_kwh=_as_float(_req(row, "charge_kwh", ctx, errors), ctx, errors, minimum=0),
                maintenance_minutes=_as_int(_req(row, "maintenance_minutes", ctx, errors), ctx, errors, minimum=0),
                reason=_opt(row, "reason"),
            )
        )

    depots = []
    for i, row in enumerate(
        _rows(
            root / "depot_constraints.csv",
            ["depot_id", "route_id", "period", "charger_ports", "available_kwh", "assigned_vehicle_ids"],
            errors,
        ),
        start=2,
    ):
        ctx = f"depot_constraints.csv 第{i}行"
        depots.append(
            DepotConstraint(
                depot_id=_req(row, "depot_id", ctx, errors),
                route_id=_req(row, "route_id", ctx, errors),
                period=_req(row, "period", ctx, errors),
                charger_ports=_as_int(_req(row, "charger_ports", ctx, errors), ctx, errors, minimum=0),
                available_kwh=_as_float(_req(row, "available_kwh", ctx, errors), ctx, errors, minimum=0),
                assigned_vehicle_ids=tuple(
                    x for x in (_opt(row, "assigned_vehicle_ids")).split("|") if x
                ),
            )
        )

    targets = []
    for i, row in enumerate(
        _rows(
            root / "coverage_targets.csv",
            ["route_id", "period", "required_trips", "is_peak", "effective_from", "effective_to"],
            errors,
        ),
        start=2,
    ):
        ctx = f"coverage_targets.csv 第{i}行"
        eff_from = _as_date(_req(row, "effective_from", ctx, errors), ctx, errors)
        eff_to = _as_date(_opt(row, "effective_to"), ctx, errors)
        if eff_from and eff_to and eff_to < eff_from:
            _fail(ctx, errors, "effective_to 早于 effective_from")
        targets.append(
            CoverageTarget(
                route_id=_req(row, "route_id", ctx, errors),
                period=_req(row, "period", ctx, errors),
                required_trips=_as_int(_req(row, "required_trips", ctx, errors), ctx, errors, minimum=0),
                is_peak=_as_bool(_req(row, "is_peak", ctx, errors), ctx, errors),
                effective_from=eff_from or date.min,
                effective_to=eff_to,
            )
        )

    vehicle_ids = [v.vehicle_id for v in vehicles]
    if len(set(vehicle_ids)) != len(vehicle_ids):
        _fail("vehicles.csv", errors, "vehicle_id 重复")
    trip_ids = [t.trip_id for t in trips]
    if len(set(trip_ids)) != len(trip_ids):
        _fail("service.csv", errors, "trip_id 重复")
    if errors:
        raise DatasetError(errors)

    # 引用完整性：不阻断载入，作为数据质量问题上浮
    issues = []
    known_vehicles = set(vehicle_ids)
    known_routes = {r.route_id for r in routes}
    for v in vehicles:
        if v.route_id not in known_routes:
            issues.append(Issue("UNKNOWN_ROUTE", f"车辆 {v.vehicle_id} 挂在未知线路 {v.route_id}", (v.vehicle_id, v.route_id)))
    for t in trips:
        if t.vehicle_id not in known_vehicles:
            issues.append(Issue("UNKNOWN_VEHICLE", f"班次 {t.trip_id} 引用未知车辆 {t.vehicle_id}", (t.trip_id, t.vehicle_id)))
        if t.route_id not in known_routes:
            issues.append(Issue("UNKNOWN_ROUTE", f"班次 {t.trip_id} 引用未知线路 {t.route_id}", (t.trip_id, t.route_id)))
    for op in operations:
        if op.vehicle_id not in known_vehicles:
            issues.append(Issue("UNKNOWN_VEHICLE", f"作业记录引用未知车辆 {op.vehicle_id}（{op.day.isoformat()}）", (op.vehicle_id,)))
    for d in depots:
        if d.route_id not in known_routes:
            issues.append(Issue("UNKNOWN_ROUTE", f"场站 {d.depot_id} 引用未知线路 {d.route_id}", (d.depot_id, d.route_id)))
        for vid in d.assigned_vehicle_ids:
            if vid not in known_vehicles:
                issues.append(Issue("UNKNOWN_VEHICLE", f"场站 {d.depot_id} 登记未知车辆 {vid}", (d.depot_id, vid)))
    for tg in targets:
        if tg.route_id not in known_routes:
            issues.append(Issue("UNKNOWN_ROUTE", f"覆盖目标引用未知线路 {tg.route_id}", (tg.route_id,)))

    return Dataset(
        version=version or root.name,
        source=str(root),
        vehicles=vehicles,
        routes=routes,
        trips=trips,
        operations=operations,
        depots=depots,
        targets=targets,
        issues=issues,
    )
