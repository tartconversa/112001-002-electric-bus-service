"""分析参数：排放因子、折算阈值等可调假设。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """指标计算所用的全局假设。

    operating_minutes_per_day: 单车单日理论运营分钟数，用于把维修停驶
        分钟折算为当日可用运力的扣减比例。
    grid_emission_kg_per_kwh: 电力排放因子（kg CO2e / kWh）。
    diesel_emission_kg_per_trip: 柴油车单班次排放（kg CO2e），合成数据
        未提供油耗记录时的约定参数。
    electric_kwh_per_trip_default: 线路无电耗观测时，方案推算用的
        单班次电耗缺省值（kWh）。
    """

    operating_minutes_per_day: int = 720
    grid_emission_kg_per_kwh: float = 0.55
    diesel_emission_kg_per_trip: float = 18.0
    electric_kwh_per_trip_default: float = 15.0
