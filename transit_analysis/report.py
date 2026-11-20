"""报表渲染：线路汇总、版本对照、方案影响的文本输出。

JSON 输出直接使用各对象的 as_dict()。文本输出中每个线路区间可
展开到组成结论的班次、车辆与例外，支持从汇总向下追溯。
"""
from __future__ import annotations

FLAG_LABELS = {
    "ROUTE_CHANGE_BOUNDARY": "线路调整边界",
    "NO_DATA": "无数据",
    "PROVISIONAL_DATA": "暂定(数据缺失)",
}


def _pct(value):
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def format_metrics(metrics, detail: bool = False) -> str:
    lines = []
    for m in metrics:
        flags = "、".join(FLAG_LABELS.get(f, f) for f in m.comparability) or "可比"
        lines.append(
            f"[{m.label}] {m.route_name} 运营日 {m.operating_days} 天（{flags}）"
        )
        lines.append(
            "  班次: 计划 {scheduled} / 完成 {completed} / 取消 {cancelled}，完成率 {rel}；"
            "高峰计划 {ps} / 高峰完成 {pc}".format(
                scheduled=m.scheduled_trips,
                completed=m.completed_trips,
                cancelled=m.cancelled_trips,
                rel=_pct(m.reliability),
                ps=m.peak_scheduled,
                pc=m.peak_completed,
            )
        )
        lines.append(
            "  运力: 可用 {avail}，电动占比 {eshare}（按载客能力加权）；"
            "零排放服务占比 完成口径 {zc} / 计划口径 {zs}".format(
                avail=_num(m.available_capacity),
                eshare=_pct(m.electric_capacity_share),
                zc=_pct(m.zero_emission_completed_share),
                zs=_pct(m.zero_emission_scheduled_share),
            )
        )
        lines.append(
            "  能源: 充电 {kwh} kWh，排放 {em} kg；强度/完成班次 {ic} kg，"
            "强度/计划班次 {isc} kg".format(
                kwh=_num(m.charge_kwh),
                em=_num(m.emissions_kg),
                ic=_num(m.intensity_per_completed_trip, 2),
                isc=_num(m.intensity_per_scheduled_trip, 2),
            )
        )
        lines.append(
            "  覆盖: 目标 {req} 班，达成 {ratio}，缺口单元 {cells} 个{met}".format(
                req=m.coverage_required,
                ratio=_pct(m.coverage_ratio),
                cells=m.shortfall_cells,
                met="" if m.coverage_met else "（未达成）",
            )
        )
        if detail:
            if m.periods:
                for period, cell in sorted(m.periods.items()):
                    peak = "高峰" if cell.is_peak else "平峰"
                    lines.append(
                        f"    时段 {period}（{peak}）: 计划 {cell.scheduled} / 完成 {cell.completed}"
                        f" / 取消 {cell.cancelled}，目标 {cell.required}"
                    )
            if m.exceptions:
                lines.append("    例外:")
                for e in m.exceptions:
                    lines.append(f"      - [{e.kind}] {e.message}")
            if m.trip_ids:
                lines.append(f"    班次: {', '.join(m.trip_ids)}")
            if m.vehicle_ids:
                lines.append(f"    车辆: {', '.join(m.vehicle_ids)}")
    return "\n".join(lines)


def format_comparison(comparison) -> str:
    lines = [
        f"资料版本对照: {comparison.baseline_version}（原始观测） vs {comparison.revised_version}（更正后）"
    ]
    if comparison.record_diffs:
        lines.append("记录级差异:")
        for diff in comparison.record_diffs:
            lines.append(f"  - {diff}")
    else:
        lines.append("记录级差异: 无")
    for row in comparison.rows:
        status = {
            "UNCHANGED": "无变化",
            "CORRECTED": "已更正",
            "ONLY_IN_BASELINE": "仅原始版本",
            "ONLY_IN_REVISED": "仅更正版本",
        }.get(row.status, row.status)
        lines.append(f"[{row.label}] {status}")
        for change in row.changes:
            lines.append(
                f"    {change.label}: {_fmt_value(change.baseline)} -> {_fmt_value(change.revised)}"
            )
        if row.baseline_flags != row.revised_flags:
            before = "、".join(FLAG_LABELS.get(f, f) for f in row.baseline_flags) or "可比"
            after = "、".join(FLAG_LABELS.get(f, f) for f in row.revised_flags) or "可比"
            lines.append(f"    可比性标记: {before} -> {after}")
    return "\n".join(lines)


def _fmt_value(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def format_impact(report) -> str:
    lines = [f"方案 {report.proposal_id}（资料版本 {report.dataset_version}）影响评估"]
    if report.violations:
        lines.append("校验问题:")
        for v in report.violations:
            lines.append(f"  - [{v.kind}] {v.message}")
    else:
        lines.append("校验问题: 无")
    for impact in report.route_impacts:
        lines.append(f"线路 {impact.route_id}:")
        lines.append(
            "    可用运力 {ab} -> {aa}；电动运力占比 {eb} -> {ea}".format(
                ab=_num(impact.available_capacity_before),
                aa=_num(impact.available_capacity_after),
                eb=_pct(impact.electric_capacity_share_before),
                ea=_pct(impact.electric_capacity_share_after),
            )
        )
        lines.append(
            "    排放: 基线观测 {obs} kg；同口径推算 {pb} -> {pa} kg".format(
                obs=_num(impact.emissions_observed_before),
                pb=_num(impact.emissions_projected_before),
                pa=_num(impact.emissions_projected_after),
            )
        )
        if impact.at_risk_trips:
            lines.append(
                f"    风险班次: {', '.join(impact.at_risk_trips)}"
                f"（计划 {impact.at_risk_scheduled} 班，其中高峰 {impact.peak_at_risk_scheduled} 班）"
            )
        if impact.coverage_cells_newly_short:
            lines.append("    覆盖受损单元:")
            for cell in impact.coverage_cells_newly_short:
                lines.append(f"      - {cell}")
        lines.append(f"    既定服务覆盖: {'受损' if impact.coverage_harmed else '未受损'}")
    lines.append(f"总体: 服务覆盖{'受损' if report.coverage_harmed else '未受损'}")
    return "\n".join(lines)
