"""领域模型：车辆、线路版本、班次、充电与维修、场站约束、覆盖目标。

车辆、线路、覆盖目标均为带生效日期的资料；同一线路可存在多个
生效区间不重叠的版本（线路调整），用于划分可比运营区间。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Issue:
    """数据质量或约束问题；kind 为机器可读标识，refs 为可追溯对象。"""

    kind: str
    message: str
    refs: tuple = ()

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "refs": list(self.refs)}


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    route_id: str
    powertrain: str
    battery_kwh: float
    capacity: float
    active_from: date
    active_to: date | None

    @property
    def is_electric(self) -> bool:
        return self.powertrain == "battery_electric"

    def active_on(self, day: date) -> bool:
        if day < self.active_from:
            return False
        return self.active_to is None or day <= self.active_to


@dataclass(frozen=True)
class RouteVersion:
    route_id: str
    route_name: str
    effective_from: date
    effective_to: date | None

    def covers(self, day: date) -> bool:
        if day < self.effective_from:
            return False
        return self.effective_to is None or day <= self.effective_to


@dataclass(frozen=True)
class TripRecord:
    trip_id: str
    route_id: str
    service_date: date
    period: str
    scheduled: int
    completed: int
    vehicle_id: str

    @property
    def cancelled(self) -> int:
        return self.scheduled - self.completed


@dataclass(frozen=True)
class OperationRecord:
    vehicle_id: str
    day: date
    charge_kwh: float
    maintenance_minutes: int
    reason: str


@dataclass(frozen=True)
class DepotConstraint:
    depot_id: str
    route_id: str
    period: str
    charger_ports: int
    available_kwh: float
    assigned_vehicle_ids: tuple


@dataclass(frozen=True)
class CoverageTarget:
    route_id: str
    period: str
    required_trips: int
    is_peak: bool
    effective_from: date
    effective_to: date | None

    def covers(self, day: date) -> bool:
        if day < self.effective_from:
            return False
        return self.effective_to is None or day <= self.effective_to


@dataclass
class Dataset:
    """一个资料版本的全量输入。version 通常为数据目录名。"""

    version: str
    source: str
    vehicles: list
    routes: list
    trips: list
    operations: list
    depots: list
    targets: list
    issues: list = field(default_factory=list)

    def __post_init__(self):
        self.vehicles_by_id = {v.vehicle_id: v for v in self.vehicles}
        self._ops_by_vehicle_day = {}
        for op in self.operations:
            self._ops_by_vehicle_day.setdefault((op.vehicle_id, op.day), []).append(op)

    def vehicle(self, vehicle_id: str) -> Vehicle | None:
        return self.vehicles_by_id.get(vehicle_id)

    def vehicles_for_route(self, route_id: str) -> list:
        return [v for v in self.vehicles if v.route_id == route_id]

    def operations_for(self, vehicle_id: str, day: date) -> list:
        return self._ops_by_vehicle_day.get((vehicle_id, day), [])

    def maintenance_minutes(self, vehicle_id: str, day: date) -> int:
        return sum(op.maintenance_minutes for op in self.operations_for(vehicle_id, day))

    def targets_for(self, route_id: str, day: date) -> list:
        return [
            t for t in self.targets if t.route_id == route_id and t.covers(day)
        ]
