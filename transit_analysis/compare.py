"""两个资料版本的对照：保留原始观测与更正后的解释。

数据缺失、维修记录晚到或线路调整时，更正后的数据集作为新版本载入；
对照结果同时保留两个版本的指标值与记录级差异，便于区分真实改善
与不可比区间。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .config import AnalysisConfig
from .metrics import compute_metrics

COMPARE_FIELDS = (
    ("scheduled_trips", "计划班次"),
    ("completed_trips", "完成班次"),
    ("reliability", "班次完成率"),
    ("available_capacity", "可用运力"),
    ("electric_capacity_share", "电动运力占比"),
    ("zero_emission_completed_share", "零排放服务占比(完成口径)"),
    ("zero_emission_scheduled_share", "零排放服务占比(计划口径)"),
    ("emissions_kg", "排放量kg"),
    ("intensity_per_completed_trip", "排放强度/完成班次"),
    ("intensity_per_scheduled_trip", "排放强度/计划班次"),
    ("coverage_ratio", "覆盖达成率"),
    ("shortfall_cells", "覆盖缺口单元数"),
)


@dataclass
class MetricChange:
    field: str
    label: str
    baseline: object
    revised: object

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "label": self.label,
            "baseline": self.baseline,
            "revised": self.revised,
        }


@dataclass
class IntervalComparison:
    route_id: str
    label: str
    status: str  # UNCHANGED / CORRECTED / ONLY_IN_BASELINE / ONLY_IN_REVISED
    changes: list = field(default_factory=list)
    baseline_flags: list = field(default_factory=list)
    revised_flags: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "label": self.label,
            "status": self.status,
            "changes": [c.as_dict() for c in self.changes],
            "baseline_flags": list(self.baseline_flags),
            "revised_flags": list(self.revised_flags),
        }


@dataclass
class DatasetComparison:
    baseline_version: str
    revised_version: str
    record_diffs: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.record_diffs) or any(r.status != "UNCHANGED" for r in self.rows)

    def as_dict(self) -> dict:
        return {
            "baseline_version": self.baseline_version,
            "revised_version": self.revised_version,
            "record_diffs": list(self.record_diffs),
            "rows": [r.as_dict() for r in self.rows],
        }


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= 1e-9
    return a == b


def _diff_keyed(name, a_rows, b_rows, key, fields):
    diffs = []
    a_map = {key(r): r for r in a_rows}
    b_map = {key(r): r for r in b_rows}
    for k in sorted(a_map.keys() - b_map.keys()):
        diffs.append(f"{name} 删除: {k}")
    for k in sorted(b_map.keys() - a_map.keys()):
        diffs.append(f"{name} 新增: {k}")
    for k in sorted(a_map.keys() & b_map.keys()):
        for f in fields:
            va, vb = getattr(a_map[k], f), getattr(b_map[k], f)
            if va != vb:
                diffs.append(f"{name} {k} 字段 {f}: {va} -> {vb}")
    return diffs


def _op_key(op):
    return (op.vehicle_id, op.day.isoformat(), op.charge_kwh, op.maintenance_minutes, op.reason)


def _describe_op(key):
    vid, day, kwh, minutes, reason = key
    parts = [f"车辆{vid}", day]
    if kwh:
        parts.append(f"充电{kwh}kWh")
    if minutes:
        parts.append(f"维修{minutes}分钟")
    if reason:
        parts.append(f"({reason})")
    return " ".join(parts)


def diff_records(a, b) -> list:
    """记录级差异说明（新增/删除/字段变化）。"""
    diffs = []
    diffs += _diff_keyed(
        "车辆", a.vehicles, b.vehicles,
        key=lambda v: v.vehicle_id,
        fields=("route_id", "powertrain", "battery_kwh", "capacity", "active_from", "active_to"),
    )
    diffs += _diff_keyed(
        "线路", a.routes, b.routes,
        key=lambda r: (r.route_id, r.effective_from),
        fields=("route_name", "effective_to"),
    )
    diffs += _diff_keyed(
        "班次", a.trips, b.trips,
        key=lambda t: t.trip_id,
        fields=("route_id", "service_date", "period", "scheduled", "completed", "vehicle_id"),
    )
    diffs += _diff_keyed(
        "场站约束", a.depots, b.depots,
        key=lambda d: (d.depot_id, d.route_id, d.period),
        fields=("charger_ports", "available_kwh", "assigned_vehicle_ids"),
    )
    diffs += _diff_keyed(
        "覆盖目标", a.targets, b.targets,
        key=lambda t: (t.route_id, t.period, t.effective_from),
        fields=("required_trips", "is_peak", "effective_to"),
    )
    a_ops = Counter(_op_key(o) for o in a.operations)
    b_ops = Counter(_op_key(o) for o in b.operations)
    for key, _ in sorted((b_ops - a_ops).items()):
        diffs.append(f"作业记录 新增: {_describe_op(key)}")
    for key, _ in sorted((a_ops - b_ops).items()):
        diffs.append(f"作业记录 删除: {_describe_op(key)}")
    return diffs


def compare_datasets(a, b, config: AnalysisConfig | None = None) -> DatasetComparison:
    """对照两个资料版本；a 为原始观测，b 为更正后的解释。"""
    config = config or AnalysisConfig()
    a_metrics = {m.label: m for m in compute_metrics(a, config)}
    b_metrics = {m.label: m for m in compute_metrics(b, config)}
    rows = []
    for label in sorted(a_metrics.keys() | b_metrics.keys()):
        ma = a_metrics.get(label)
        mb = b_metrics.get(label)
        if ma is None:
            rows.append(
                IntervalComparison(mb.route_id, label, "ONLY_IN_REVISED", [], [], list(mb.comparability))
            )
            continue
        if mb is None:
            rows.append(
                IntervalComparison(ma.route_id, label, "ONLY_IN_BASELINE", [], list(ma.comparability), [])
            )
            continue
        changes = [
            MetricChange(attr, zh, getattr(ma, attr), getattr(mb, attr))
            for attr, zh in COMPARE_FIELDS
            if not _close(getattr(ma, attr), getattr(mb, attr))
        ]
        status = (
            "CORRECTED"
            if changes or ma.comparability != mb.comparability
            else "UNCHANGED"
        )
        rows.append(
            IntervalComparison(
                ma.route_id,
                label,
                status,
                changes,
                list(ma.comparability),
                list(mb.comparability),
            )
        )
    return DatasetComparison(
        baseline_version=a.version,
        revised_version=b.version,
        record_diffs=diff_records(a, b),
        rows=rows,
    )
