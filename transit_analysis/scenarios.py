"""调度方案：车辆替换、临时停驶、班次改派与充电安排。

方案先校验（场站接口数、时段电量、同一车辆同一时段不得重复排班、
充电与班次不得冲突等），再应用到某一资料版本上，评估对高峰班次、
服务覆盖与各线路指标的共同影响；通过的方案可连同所采用的资料
版本一起留存，供下月复核。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

from .config import AnalysisConfig
from .metrics import compute_metrics
from .models import Dataset, Issue, Vehicle

ACTION_TYPES = ("replace_vehicle", "retire_vehicle", "assign_trip", "charging_plan")


class ProposalError(Exception):
    """方案文件结构非法。"""


@dataclass
class Proposal:
    proposal_id: str
    title: str
    actions: list
    note: str = ""

    @staticmethod
    def from_dict(data) -> "Proposal":
        if not isinstance(data, dict):
            raise ProposalError("方案必须是 JSON 对象")
        proposal_id = str(data.get("proposal_id") or "").strip()
        if not proposal_id:
            raise ProposalError("缺少 proposal_id")
        actions = data.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ProposalError("actions 必须是非空列表")
        for index, action in enumerate(actions, 1):
            _check_action(index, action)
        return Proposal(
            proposal_id=proposal_id,
            title=str(data.get("title") or proposal_id),
            actions=actions,
            note=str(data.get("note") or ""),
        )

    def as_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "note": self.note,
            "actions": self.actions,
        }


def load_proposal(path) -> Proposal:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalError(f"无法读取方案文件: {exc}") from exc
    return Proposal.from_dict(data)


def _parse_date_field(value, ctx):
    try:
        date.fromisoformat(str(value))
    except ValueError:
        raise ProposalError(f"{ctx}: 日期格式非法 {value!r}")


def _check_action(index, action):
    ctx = f"actions[{index}]"
    if not isinstance(action, dict):
        raise ProposalError(f"{ctx}: 必须是对象")
    kind = action.get("type")
    if kind not in ACTION_TYPES:
        raise ProposalError(f"{ctx}: 未知动作类型 {kind!r}")

    def req(*keys):
        for key in keys:
            if action.get(key) in (None, ""):
                raise ProposalError(f"{ctx}: 缺少字段 {key}")

    if kind == "replace_vehicle":
        req("vehicle_id", "effective_from", "with")
        _parse_date_field(action["effective_from"], ctx)
        spec = action["with"]
        if not isinstance(spec, dict):
            raise ProposalError(f"{ctx}: with 必须是对象")
        for key in ("vehicle_id", "powertrain", "battery_kwh", "capacity"):
            if spec.get(key) in (None, ""):
                raise ProposalError(f"{ctx}: with 缺少字段 {key}")
    elif kind == "retire_vehicle":
        req("vehicle_id", "effective_from")
        _parse_date_field(action["effective_from"], ctx)
    elif kind == "assign_trip":
        req("trip_id", "vehicle_id")
    elif kind == "charging_plan":
        req("depot_id", "entries")
        entries = action["entries"]
        if not isinstance(entries, list) or not entries:
            raise ProposalError(f"{ctx}: entries 必须是非空列表")
        for j, entry in enumerate(entries, 1):
            ectx = f"{ctx}.entries[{j}]"
            if not isinstance(entry, dict):
                raise ProposalError(f"{ectx}: 必须是对象")
            for key in ("vehicle_id", "date", "period", "kwh"):
                if entry.get(key) in (None, ""):
                    raise ProposalError(f"{ectx}: 缺少字段 {key}")
            _parse_date_field(entry["date"], ectx)
            try:
                if float(entry["kwh"]) <= 0:
                    raise ProposalError(f"{ectx}: kwh 必须为正数")
            except (TypeError, ValueError):
                raise ProposalError(f"{ectx}: kwh 数值非法 {entry['kwh']!r}")


def apply_proposal(dataset: Dataset, proposal: Proposal) -> Dataset:
    """把方案中的台账类动作应用到某一资料版本，返回新的数据集。

    charging_plan 不改变台账，仅参与校验与评估。未知引用在此跳过，
    由 validate_proposal 统一报告。
    """
    vehicles = list(dataset.vehicles)
    trips = list(dataset.trips)

    def find_vehicle(vid):
        for i, v in enumerate(vehicles):
            if v.vehicle_id == vid:
                return i
        return None

    for action in proposal.actions:
        kind = action["type"]
        if kind == "replace_vehicle":
            spec = action["with"]
            idx = find_vehicle(action["vehicle_id"])
            if idx is None or find_vehicle(spec["vehicle_id"]) is not None:
                continue
            effective = date.fromisoformat(action["effective_from"])
            old = vehicles[idx]
            end = effective - timedelta(days=1)
            if old.active_to is not None:
                end = min(end, old.active_to)
            vehicles[idx] = replace(old, active_to=end)
            vehicles.append(
                Vehicle(
                    vehicle_id=spec["vehicle_id"],
                    route_id=old.route_id,
                    powertrain=spec["powertrain"],
                    battery_kwh=float(spec["battery_kwh"]),
                    capacity=float(spec["capacity"]),
                    active_from=effective,
                    active_to=None,
                )
            )
            trips = [
                replace(t, vehicle_id=spec["vehicle_id"])
                if t.vehicle_id == old.vehicle_id and t.service_date >= effective
                else t
                for t in trips
            ]
        elif kind == "retire_vehicle":
            idx = find_vehicle(action["vehicle_id"])
            if idx is None:
                continue
            effective = date.fromisoformat(action["effective_from"])
            old = vehicles[idx]
            end = effective - timedelta(days=1)
            if old.active_to is not None:
                end = min(end, old.active_to)
            vehicles[idx] = replace(old, active_to=end)
        elif kind == "assign_trip":
            trips = [
                replace(t, vehicle_id=action["vehicle_id"])
                if t.trip_id == action["trip_id"]
                else t
                for t in trips
            ]
    return Dataset(
        version=f"{dataset.version}+{proposal.proposal_id}",
        source=dataset.source,
        vehicles=vehicles,
        routes=dataset.routes,
        trips=trips,
        operations=dataset.operations,
        depots=dataset.depots,
        targets=dataset.targets,
        issues=list(dataset.issues),
    )


def _depot_slot(dataset, depot_id, period, route_id):
    for d in dataset.depots:
        if d.depot_id == depot_id and d.period == period and d.route_id == route_id:
            return d
    return None


def _depot_slots(dataset, depot_id, period):
    return [d for d in dataset.depots if d.depot_id == depot_id and d.period == period]


def validate_proposal(dataset: Dataset, proposal: Proposal, config: AnalysisConfig | None = None) -> list:
    """结构引用校验 + 应用方案后的台账约束校验。"""
    issues = []
    for action in proposal.actions:
        kind = action["type"]
        if kind in ("replace_vehicle", "retire_vehicle"):
            if dataset.vehicle(action["vehicle_id"]) is None:
                issues.append(
                    Issue("UNKNOWN_VEHICLE", f"方案引用未知车辆 {action['vehicle_id']}", (action["vehicle_id"],))
                )
        if kind == "replace_vehicle":
            spec = action["with"]
            if dataset.vehicle(spec["vehicle_id"]) is not None:
                issues.append(
                    Issue("VEHICLE_ID_CONFLICT", f"替换车辆编号 {spec['vehicle_id']} 已存在", (spec["vehicle_id"],))
                )
            if spec["powertrain"] == "battery_electric" and float(spec["battery_kwh"]) <= 0:
                issues.append(Issue("BAD_SPEC", "纯电动替换车必须配置正电池容量", (spec["vehicle_id"],)))
            if float(spec["capacity"]) <= 0:
                issues.append(Issue("BAD_SPEC", "替换车载客能力必须为正数", (spec["vehicle_id"],)))
        if kind == "assign_trip":
            trip = next((t for t in dataset.trips if t.trip_id == action["trip_id"]), None)
            if trip is None:
                issues.append(Issue("UNKNOWN_TRIP", f"方案引用未知班次 {action['trip_id']}", (action["trip_id"],)))
            elif dataset.vehicle(action["vehicle_id"]) is None:
                issues.append(
                    Issue("UNKNOWN_VEHICLE", f"方案引用未知车辆 {action['vehicle_id']}", (action["vehicle_id"],))
                )

    scenario = apply_proposal(dataset, proposal)

    # 改派目标车辆在班次日须有效（按应用方案后的台账判断）
    for action in proposal.actions:
        if action["type"] != "assign_trip":
            continue
        trip = next((t for t in scenario.trips if t.trip_id == action["trip_id"]), None)
        vehicle = scenario.vehicle(action["vehicle_id"])
        if trip is not None and vehicle is not None and not vehicle.active_on(trip.service_date):
            issues.append(
                Issue(
                    "ASSIGN_INACTIVE_VEHICLE",
                    f"车辆 {vehicle.vehicle_id} 在 {trip.service_date.isoformat()} 不在役，无法承接班次 {trip.trip_id}",
                    (vehicle.vehicle_id, trip.trip_id),
                )
            )

    # 同一车辆同一日期同一时段不得重复排入两个班次
    slots = {}
    for t in scenario.trips:
        slots.setdefault((t.vehicle_id, t.service_date, t.period), []).append(t.trip_id)
    for (vid, day, period), ids in sorted(slots.items()):
        if len(ids) > 1:
            issues.append(
                Issue(
                    "DOUBLE_BOOKING",
                    f"车辆 {vid} 在 {day.isoformat()} {period} 被重复排入班次: {', '.join(ids)}",
                    (vid, day.isoformat(), period, *ids),
                )
            )

    # 充电方案：场站接口数、时段电量、车辆登记、与班次冲突
    for action in proposal.actions:
        if action["type"] != "charging_plan":
            continue
        depot_id = action["depot_id"]
        entries = action["entries"]
        for entry in entries:
            vid = entry["vehicle_id"]
            day = date.fromisoformat(entry["date"])
            period = entry["period"]
            vehicle = dataset.vehicle(vid)
            if vehicle is None:
                issues.append(Issue("UNKNOWN_VEHICLE", f"充电计划引用未知车辆 {vid}", (vid,)))
                continue
            if not vehicle.is_electric:
                issues.append(Issue("NON_ELECTRIC_VEHICLE", f"车辆 {vid} 非纯电动车，不能安排充电", (vid,)))
            slots = _depot_slots(dataset, depot_id, period)
            if not slots:
                issues.append(
                    Issue(
                        "UNKNOWN_DEPOT_SLOT",
                        f"场站 {depot_id} 在 {period} 时段无约束记录",
                        (depot_id, period),
                    )
                )
            elif not any(vid in s.assigned_vehicle_ids for s in slots):
                issues.append(
                    Issue(
                        "VEHICLE_NOT_ASSIGNED_TO_DEPOT",
                        f"车辆 {vid} 未登记在场站 {depot_id} {period} 时段",
                        (vid, depot_id, period),
                    )
                )
            for t in scenario.trips:
                if t.vehicle_id == vid and t.service_date == day and t.period == period:
                    issues.append(
                        Issue(
                            "CHARGE_TRIP_CONFLICT",
                            f"车辆 {vid} 在 {day.isoformat()} {period} 同时被安排充电与班次 {t.trip_id}",
                            (vid, day.isoformat(), period, t.trip_id),
                        )
                    )
        # 同一车辆同一时段只能有一个充电安排
        by_vehicle_slot = {}
        for entry in entries:
            by_vehicle_slot.setdefault(
                (entry["vehicle_id"], entry["date"], entry["period"]), []
            ).append(depot_id)
        for (vid, day, period), depots in sorted(by_vehicle_slot.items()):
            if len(depots) > 1:
                issues.append(
                    Issue(
                        "DUPLICATE_CHARGE_ENTRY",
                        f"车辆 {vid} 在 {day} {period} 被重复安排充电",
                        (vid, day, period),
                    )
                )
        groups = {}
        for entry in entries:
            vehicle = dataset.vehicle(entry["vehicle_id"])
            route_id = vehicle.route_id if vehicle else ""
            key = (depot_id, entry["date"], entry["period"], route_id)
            groups.setdefault(key, []).append(entry)
        for (did, day, period, route_id), group in sorted(groups.items()):
            slot = _depot_slot(dataset, did, period, route_id)
            if slot is None:
                continue
            if len(group) > slot.charger_ports:
                issues.append(
                    Issue(
                        "DEPOT_PORTS_EXCEEDED",
                        f"{did} {day} {period} 计划充电 {len(group)} 辆，超过接口数 {slot.charger_ports}",
                        (did, day, period),
                    )
                )
            total_kwh = sum(float(e["kwh"]) for e in group)
            if total_kwh > slot.available_kwh:
                issues.append(
                    Issue(
                        "DEPOT_ENERGY_EXCEEDED",
                        f"{did} {day} {period} 计划充电 {total_kwh} kWh，超过时段可用电量 {slot.available_kwh} kWh",
                        (did, day, period),
                    )
                )
    return issues


@dataclass
class RouteImpact:
    route_id: str
    available_capacity_before: float
    available_capacity_after: float
    electric_capacity_share_before: float | None
    electric_capacity_share_after: float | None
    emissions_observed_before: float
    emissions_projected_before: float
    emissions_projected_after: float
    at_risk_trips: list = field(default_factory=list)
    at_risk_scheduled: int = 0
    peak_at_risk_scheduled: int = 0
    coverage_cells_newly_short: list = field(default_factory=list)
    coverage_harmed: bool = False

    def as_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "available_capacity_before": self.available_capacity_before,
            "available_capacity_after": self.available_capacity_after,
            "electric_capacity_share_before": self.electric_capacity_share_before,
            "electric_capacity_share_after": self.electric_capacity_share_after,
            "emissions_observed_before": self.emissions_observed_before,
            "emissions_projected_before": self.emissions_projected_before,
            "emissions_projected_after": self.emissions_projected_after,
            "at_risk_trips": list(self.at_risk_trips),
            "at_risk_scheduled": self.at_risk_scheduled,
            "peak_at_risk_scheduled": self.peak_at_risk_scheduled,
            "coverage_cells_newly_short": list(self.coverage_cells_newly_short),
            "coverage_harmed": self.coverage_harmed,
        }


@dataclass
class ImpactReport:
    proposal_id: str
    dataset_version: str
    violations: list = field(default_factory=list)
    route_impacts: list = field(default_factory=list)

    @property
    def coverage_harmed(self) -> bool:
        return any(r.coverage_harmed for r in self.route_impacts)

    def as_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "dataset_version": self.dataset_version,
            "coverage_harmed": self.coverage_harmed,
            "violations": [v.as_dict() for v in self.violations],
            "route_impacts": [r.as_dict() for r in self.route_impacts],
        }


def _group_by_route(metrics) -> dict:
    grouped = {}
    for m in metrics:
        grouped.setdefault(m.route_id, []).append(m)
    return grouped


def _aggregate(metrics) -> dict:
    out = {
        "available_capacity": 0.0,
        "electric_available": 0.0,
        "emissions": 0.0,
        "charge_kwh": 0.0,
        "electric_completed": 0,
        "completed": 0,
        "scheduled": 0,
    }
    for m in metrics:
        out["available_capacity"] += m.available_capacity
        out["electric_available"] += m.electric_available_capacity
        out["emissions"] += m.emissions_kg
        out["charge_kwh"] += m.charge_kwh
        out["electric_completed"] += m.electric_completed_trips
        out["completed"] += m.completed_trips
        out["scheduled"] += m.scheduled_trips
    return out


def _share(agg):
    if not agg["available_capacity"]:
        return None
    return round(agg["electric_available"] / agg["available_capacity"], 6)


def evaluate_proposal(dataset: Dataset, proposal: Proposal, config: AnalysisConfig | None = None) -> ImpactReport:
    """评估方案对高峰班次、服务覆盖与各线路指标的共同影响。

    排放推算口径：方案后仍在役可执行的班次，电动车按该线路基线
    观测的单班次电耗折算，柴油车按单班次排放参数折算；已停驶
    车辆名下、又未改派的班次记为“风险班次”，不再计入可保障服务。
    """
    config = config or AnalysisConfig()
    violations = validate_proposal(dataset, proposal, config)
    scenario = apply_proposal(dataset, proposal)
    base_metrics = compute_metrics(dataset, config)
    scen_metrics = compute_metrics(scenario, config)

    def at_risk(ds):
        risk = []
        for t in ds.trips:
            vehicle = ds.vehicle(t.vehicle_id)
            if vehicle is None or not vehicle.active_on(t.service_date):
                risk.append(t)
        return risk

    base_risk_ids = {t.trip_id for t in at_risk(dataset)}
    scen_risk_list = at_risk(scenario)
    scen_risk_ids = {t.trip_id for t in scen_risk_list}

    base_by_route = _group_by_route(base_metrics)
    scen_by_route = _group_by_route(scen_metrics)

    kwh_per_trip = {}
    for route_id, route_metrics in base_by_route.items():
        agg = _aggregate(route_metrics)
        if agg["electric_completed"]:
            kwh_per_trip[route_id] = agg["charge_kwh"] / agg["electric_completed"]
        else:
            kwh_per_trip[route_id] = config.electric_kwh_per_trip_default

    def projected_emissions(ds, route_id, risk_ids):
        total = 0.0
        for t in ds.trips:
            if t.route_id != route_id or t.trip_id in risk_ids:
                continue
            vehicle = ds.vehicle(t.vehicle_id)
            if vehicle is not None and vehicle.is_electric:
                total += (
                    t.completed
                    * kwh_per_trip.get(route_id, config.electric_kwh_per_trip_default)
                    * config.grid_emission_kg_per_kwh
                )
            else:
                total += t.completed * config.diesel_emission_kg_per_trip
        return total

    impacts = []
    for route_id in sorted(set(base_by_route) | set(scen_by_route)):
        b_agg = _aggregate(base_by_route.get(route_id, []))
        s_agg = _aggregate(scen_by_route.get(route_id, []))
        risk_trips = [t for t in scen_risk_list if t.route_id == route_id]
        peak_periods = {tg.period for tg in scenario.targets if tg.route_id == route_id and tg.is_peak}
        peak_at_risk = sum(t.scheduled for t in risk_trips if t.period in peak_periods)

        # 覆盖影响：方案后可保障的班次是否仍满足既定服务覆盖目标
        newly_short = []
        days = sorted({t.service_date for t in scenario.trips if t.route_id == route_id})
        for day in days:
            for target in dataset.targets_for(route_id, day):
                sched_cell = sum(
                    t.scheduled
                    for t in scenario.trips
                    if t.route_id == route_id and t.service_date == day and t.period == target.period
                )
                risk_cell = sum(
                    t.scheduled for t in risk_trips if t.service_date == day and t.period == target.period
                )
                base_risk_cell = sum(
                    t.scheduled
                    for t in dataset.trips
                    if t.trip_id in base_risk_ids and t.service_date == day and t.period == target.period
                )
                proj_after = sched_cell - risk_cell
                proj_before = sched_cell - base_risk_cell
                if proj_after < target.required_trips and proj_after < proj_before:
                    newly_short.append(
                        f"{day.isoformat()} {target.period}（可保障 {proj_after}/{target.required_trips} 班）"
                    )

        impacts.append(
            RouteImpact(
                route_id=route_id,
                available_capacity_before=round(b_agg["available_capacity"], 3),
                available_capacity_after=round(s_agg["available_capacity"], 3),
                electric_capacity_share_before=_share(b_agg),
                electric_capacity_share_after=_share(s_agg),
                emissions_observed_before=round(b_agg["emissions"], 3),
                emissions_projected_before=round(projected_emissions(dataset, route_id, base_risk_ids), 3),
                emissions_projected_after=round(projected_emissions(scenario, route_id, scen_risk_ids), 3),
                at_risk_trips=sorted(t.trip_id for t in risk_trips),
                at_risk_scheduled=sum(t.scheduled for t in risk_trips),
                peak_at_risk_scheduled=peak_at_risk,
                coverage_cells_newly_short=newly_short,
                coverage_harmed=bool(newly_short),
            )
        )
    return ImpactReport(proposal.proposal_id, dataset.version, violations, impacts)
