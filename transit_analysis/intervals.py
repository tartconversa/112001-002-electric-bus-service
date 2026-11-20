"""可比运营区间：日历月 × 线路版本 的切分。

线路调整（同一路线号的新生效区间）会切开日历月，使调整前后的
区间不被直接比较；被切开的区间带 route_change_bounded 标记。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Interval:
    route_id: str
    route_name: str
    start: date
    end: date
    route_change_bounded: bool

    @property
    def label(self) -> str:
        return f"{self.route_id}:{self.start.isoformat()}..{self.end.isoformat()}"


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _month_end(day: date) -> date:
    return _next_month(day) - timedelta(days=1)


def default_horizon(dataset) -> tuple[date, date] | None:
    days = [t.service_date for t in dataset.trips]
    if not days:
        return None
    return _month_start(min(days)), _month_end(max(days))


def build_intervals(dataset, horizon=None) -> list:
    """按线路版本与日历月切分可比运营区间。"""
    if horizon is None:
        horizon = default_horizon(dataset)
        if horizon is None:
            return []
    start, end = horizon
    intervals = []
    ordered = sorted(dataset.routes, key=lambda r: (r.route_id, r.effective_from))
    for version in ordered:
        month = _month_start(start)
        while month <= end:
            month_end = _month_end(month)
            seg_start = max(month, version.effective_from, start)
            seg_end = min(month_end, version.effective_to or month_end, end)
            if seg_start <= seg_end:
                intervals.append(
                    Interval(
                        route_id=version.route_id,
                        route_name=version.route_name,
                        start=seg_start,
                        end=seg_end,
                        route_change_bounded=(seg_start > month) or (seg_end < month_end),
                    )
                )
            month = _next_month(month)
    return sorted(intervals, key=lambda i: (i.route_id, i.start))
