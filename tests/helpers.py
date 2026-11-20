"""测试共享工具：在临时目录构造数据集。"""
from __future__ import annotations

from pathlib import Path

MINIMAL_FILES = {
    "vehicles.csv": (
        "vehicle_id,route_id,powertrain,battery_kwh,capacity,active_from,active_to\n"
        "E1,R,battery_electric,300,80,2026-01-01,\n"
        "D1,R,diesel,0,80,2026-01-01,\n"
    ),
    "routes.csv": (
        "route_id,route_name,effective_from,effective_to\n"
        "R,测试线,2026-01-01,\n"
    ),
    "service.csv": (
        "trip_id,route_id,service_date,period,scheduled,completed,vehicle_id\n"
        "T1,R,2026-04-02,AM,10,10,E1\n"
        "T2,R,2026-04-02,PM,10,10,D1\n"
    ),
    "operations.csv": (
        "vehicle_id,date,charge_kwh,maintenance_minutes,reason\n"
        "E1,2026-04-02,80,0,\n"
        "D1,2026-04-02,0,0,\n"
    ),
    "depot_constraints.csv": (
        "depot_id,route_id,period,charger_ports,available_kwh,assigned_vehicle_ids\n"
        "DP,R,AM,2,500,E1\n"
    ),
    "coverage_targets.csv": (
        "route_id,period,required_trips,is_peak,effective_from,effective_to\n"
        "R,AM,10,1,2026-01-01,\n"
        "R,PM,10,1,2026-01-01,\n"
    ),
}


def write_dataset(root: Path, overrides: dict | None = None) -> Path:
    """写入一个最小合法数据集，overrides 可按文件名整体替换内容。"""
    root.mkdir(parents=True, exist_ok=True)
    files = dict(MINIMAL_FILES)
    files.update(overrides or {})
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    return root
