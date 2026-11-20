"""按线路与可比运营区间计算的联合指标。

口径设计：
- 取消班次不被记作效率提升：零排放占比与排放强度同时给出
  “占完成服务”和“占计划服务”两个口径。前者可被削减班次粉饰，
  后者不能；两者并列即暴露以服务为代价的“改善”。
- 车队结构按载客能力（capacity）加权，不按车辆台数直接比较，
  不同电池容量与车型因此可比。
- 换车与临时停驶影响相应时段可用运力：在役窗口之外的车辆不计入，
  维修分钟按当日理论运营分钟折算扣减。
- 数据缺失（有班次但无充电/维修记录）标记 PROVISIONAL_DATA，
  指标视为暂定，而不是按零处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import AnalysisConfig
from .intervals import Interval, build_intervals
from .models import Dataset, Issue


@dataclass
class PeriodCell:
    """区间内单个时段（如 AM/PM）的汇总。"""

    period: str
    scheduled: int = 0
    completed: int = 0
    required: int = 0
    is_peak: bool = False

    @property
    def cancelled(self) -> int:
        return self.scheduled - self.completed

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "scheduled": self.scheduled,
            "completed": self.completed,
            "cancelled": self.cancelled,
            "required": self.required,
            "is_peak": self.is_peak,
        }


@dataclass
class RouteIntervalMetrics:
    route_id: str
    route_name: str
    start: object
    end: object
    label: str
    operating_days: int
    scheduled_trips: int
    completed_trips: int
    cancelled_trips: int
    reliability: float | None
    scheduled_capacity: float
    delivered_capacity: float
    available_capacity: float
    electric_available_capacity: float
    electric_capacity_share: float | None
    zero_emission_completed_share: float | None
    zero_emission_scheduled_share: float | None
    electric_completed_trips: int
    diesel_completed_trips: int
    charge_kwh: float
    emissions_kg: float
    intensity_per_completed_trip: float | None
    intensity_per_scheduled_trip: float | None
    kwh_per_electric_trip: float | None
    coverage_required: int
    coverage_ratio: float | None
    coverage_met: bool
    shortfall_cells: int
    peak_scheduled: int
    peak_completed: int
    periods: dict = field(default_factory=dict)
    comparability: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)
    trip_ids: list = field(default_factory=list)
    vehicle_ids: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "route_name": self.route_name,
            "interval": {
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
                "label": self.label,
            },
            "operating_days": self.operating_days,
            "trips": {
                "scheduled": self.scheduled_trips,
                "completed": self.completed_trips,
                "cancelled": self.cancelled_trips,
                "reliability": self.reliability,
                "peak_scheduled": self.peak_scheduled,
                "peak_completed": self.peak_completed,
            },
            "capacity": {
                "scheduled": self.scheduled_capacity,
                "delivered": self.delivered_capacity,
                "available": self.available_capacity,
                "electric_available": self.electric_available_capacity,
                "electric_share": self.electric_capacity_share,
            },
            "zero_emission": {
                "share_of_completed": self.zero_emission_completed_share,
                "share_of_scheduled": self.zero_emission_scheduled_share,
                "electric_completed_trips": self.electric_completed_trips,
                "diesel_completed_trips": self.diesel_completed_trips,
            },
            "energy": {
                "charge_kwh": self.charge_kwh,
                "emissions_kg": self.emissions_kg,
                "intensity_per_completed_trip": self.intensity_per_completed_trip,
                "intensity_per_scheduled_trip": self.intensity_per_scheduled_trip,
                "kwh_per_electric_trip": self.kwh_per_electric_trip,
            },
            "coverage": {
                "required": self.coverage_required,
                "ratio": self.coverage_ratio,
                "met": self.coverage_met,
                "shortfall_cells": self.shortfall_cells,
            },
            "periods": {p: cell.as_dict() for p, cell in sorted(self.periods.items())},
            "comparability": list(self.comparability),
            "exceptions": [e.as_dict() for e in self.exceptions],
            "trip_ids": list(self.trip_ids),
            "vehicle_ids": list(self.vehicle_ids),
        }


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def compute_interval_metrics(dataset: Dataset, interval: Interval, config: AnalysisConfig) -> RouteIntervalMetrics:
    trips = [
        t
        for t in dataset.trips
        if t.route_id == interval.route_id and interval.start <= t.service_date <= interval.end
    ]
    days = sorted({t.service_date for t in trips})
    exceptions = []
    comparability = []
    if interval.route_change_bounded:
        comparability.append("ROUTE_CHANGE_BOUNDARY")
    if not days:
        comparability.append("NO_DATA")

    periods = {}
    completed_cells = {}
    scheduled_capacity = 0.0
    delivered_capacity = 0.0
    electric_scheduled_capacity = 0.0
    electric_delivered_capacity = 0.0
    electric_completed = 0
    diesel_completed = 0
    vehicle_ids = set()

    for t in trips:
        cell = periods.setdefault(t.period, PeriodCell(period=t.period))
        cell.scheduled += t.scheduled
        cell.completed += t.completed
        key = (t.service_date, t.period)
        completed_cells[key] = completed_cells.get(key, 0) + t.completed
        vehicle_ids.add(t.vehicle_id)
        vehicle = dataset.vehicle(t.vehicle_id)
        if vehicle is None:
            exceptions.append(
                Issue("UNKNOWN_VEHICLE", f"班次 {t.trip_id} 引用未知车辆 {t.vehicle_id}", (t.trip_id, t.vehicle_id))
            )
            capacity = 0.0
            electric = False
        else:
            capacity = vehicle.capacity
            electric = vehicle.is_electric
            if not vehicle.active_on(t.service_date):
                exceptions.append(
                    Issue(
                        "VEHICLE_INACTIVE_FOR_TRIP",
                        f"班次 {t.trip_id} 用车 {vehicle.vehicle_id} 在 {t.service_date.isoformat()} 不在役",
                        (t.trip_id, vehicle.vehicle_id),
                    )
                )
        scheduled_capacity += t.scheduled * capacity
        delivered_capacity += t.completed * capacity
        if electric:
            electric_scheduled_capacity += t.scheduled * capacity
            electric_delivered_capacity += t.completed * capacity
            electric_completed += t.completed
        else:
            # 未知车辆按非零排放保守计入
            diesel_completed += t.completed

    # 可用运力：在役车辆按维修分钟折算，仅统计有班次的运营日
    available_capacity = 0.0
    electric_available = 0.0
    route_vehicles = dataset.vehicles_for_route(interval.route_id)
    for day in days:
        for vehicle in route_vehicles:
            if not vehicle.active_on(day):
                continue
            vehicle_ids.add(vehicle.vehicle_id)
            maintenance = dataset.maintenance_minutes(vehicle.vehicle_id, day)
            factor = max(0.0, 1.0 - maintenance / config.operating_minutes_per_day)
            available_capacity += vehicle.capacity * factor
            if vehicle.is_electric:
                electric_available += vehicle.capacity * factor

    # 有班次但无充电/维修记录 → 暂定口径，而非按零处理
    missing = sorted(
        {
            (t.vehicle_id, t.service_date)
            for t in trips
            if dataset.vehicle(t.vehicle_id) is not None
            and not dataset.operations_for(t.vehicle_id, t.service_date)
        }
    )
    for vid, day in missing:
        exceptions.append(
            Issue(
                "MISSING_OPERATIONS",
                f"车辆 {vid} 在 {day.isoformat()} 有班次但缺少充电/维修记录",
                (vid, day.isoformat()),
            )
        )
    if missing:
        comparability.append("PROVISIONAL_DATA")

    route_vehicle_ids = {v.vehicle_id for v in route_vehicles}
    charge_kwh = sum(
        op.charge_kwh
        for op in dataset.operations
        if op.vehicle_id in route_vehicle_ids and interval.start <= op.day <= interval.end
    )
    emissions = (
        charge_kwh * config.grid_emission_kg_per_kwh
        + diesel_completed * config.diesel_emission_kg_per_trip
    )

    # 服务覆盖目标：按运营日 × 时段逐格核对
    coverage_required = 0
    targeted_completed = 0
    shortfall_cells = 0
    for day in days:
        for target in dataset.targets_for(interval.route_id, day):
            cell = periods.setdefault(target.period, PeriodCell(period=target.period))
            cell.required += target.required_trips
            if target.is_peak:
                cell.is_peak = True
            coverage_required += target.required_trips
            got = completed_cells.get((day, target.period), 0)
            targeted_completed += got
            if got < target.required_trips:
                shortfall_cells += 1
                exceptions.append(
                    Issue(
                        "SERVICE_SHORTFALL",
                        f"{day.isoformat()} {target.period} 完成 {got} 班，低于覆盖目标 {target.required_trips} 班",
                        (interval.route_id, day.isoformat(), target.period),
                    )
                )

    scheduled = sum(t.scheduled for t in trips)
    completed = sum(t.completed for t in trips)
    peak_periods = {c.period for c in periods.values() if c.is_peak}
    peak_scheduled = sum(t.scheduled for t in trips if t.period in peak_periods)
    peak_completed = sum(t.completed for t in trips if t.period in peak_periods)

    return RouteIntervalMetrics(
        route_id=interval.route_id,
        route_name=interval.route_name,
        start=interval.start,
        end=interval.end,
        label=interval.label,
        operating_days=len(days),
        scheduled_trips=scheduled,
        completed_trips=completed,
        cancelled_trips=scheduled - completed,
        reliability=_ratio(completed, scheduled),
        scheduled_capacity=scheduled_capacity,
        delivered_capacity=delivered_capacity,
        available_capacity=available_capacity,
        electric_available_capacity=electric_available,
        electric_capacity_share=_ratio(electric_available, available_capacity),
        zero_emission_completed_share=_ratio(electric_delivered_capacity, delivered_capacity),
        zero_emission_scheduled_share=_ratio(electric_scheduled_capacity, scheduled_capacity),
        electric_completed_trips=electric_completed,
        diesel_completed_trips=diesel_completed,
        charge_kwh=charge_kwh,
        emissions_kg=emissions,
        intensity_per_completed_trip=_ratio(emissions, completed),
        intensity_per_scheduled_trip=_ratio(emissions, scheduled),
        kwh_per_electric_trip=_ratio(charge_kwh, electric_completed),
        coverage_required=coverage_required,
        coverage_ratio=_ratio(targeted_completed, coverage_required),
        coverage_met=coverage_required > 0 and shortfall_cells == 0,
        shortfall_cells=shortfall_cells,
        peak_scheduled=peak_scheduled,
        peak_completed=peak_completed,
        periods=periods,
        comparability=comparability,
        exceptions=exceptions,
        trip_ids=sorted(t.trip_id for t in trips),
        vehicle_ids=sorted(vehicle_ids),
    )


def compute_metrics(dataset: Dataset, config: AnalysisConfig | None = None, horizon=None) -> list:
    config = config or AnalysisConfig()
    return [
        compute_interval_metrics(dataset, interval, config)
        for interval in build_intervals(dataset, horizon)
    ]
