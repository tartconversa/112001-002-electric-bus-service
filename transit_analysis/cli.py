"""命令行入口：校验、报表、版本对照、方案评估与留存。"""
from __future__ import annotations

import argparse
import json
import sys

from .compare import compare_datasets
from .loader import DatasetError, load_dataset
from .metrics import compute_metrics
from .report import format_comparison, format_impact, format_metrics
from .scenarios import ProposalError, evaluate_proposal, load_proposal
from .store import list_proposals, save_proposal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transit-analysis",
        description="电动公交运营分析：按可比运营区间联合呈现电动化、运力、可靠性与能源表现",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="校验数据集结构并列出数据质量问题")
    p.add_argument("--data", default="data", help="数据集目录（一个目录即一个资料版本）")

    p = sub.add_parser("report", help="按线路与可比区间输出联合指标")
    p.add_argument("--data", default="data")
    p.add_argument("--route", help="只输出指定线路")
    p.add_argument("--detail", action="store_true", help="展开班次、车辆与例外明细")
    p.add_argument("--json", action="store_true", help="以 JSON 输出")

    p = sub.add_parser("compare", help="对照两个资料版本（原始观测 vs 更正后解释）")
    p.add_argument("--data", default="data", help="原始资料版本目录")
    p.add_argument("--other", required=True, help="更正后资料版本目录")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("propose", help="评估调度方案对高峰班次、服务覆盖与线路指标的影响")
    p.add_argument("--data", default="data")
    p.add_argument("--proposal", required=True, help="方案 JSON 文件")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("save", help="留存选定方案及其资料版本，供下月复核")
    p.add_argument("--data", default="data")
    p.add_argument("--proposal", required=True)
    p.add_argument("--store", default="proposal_store")
    p.add_argument("--force", action="store_true", help="存在校验问题时仍强制留存")

    p = sub.add_parser("review", help="查看已留存的方案")
    p.add_argument("--store", default="proposal_store")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except DatasetError as exc:
        print("数据集校验失败:", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 2
    except ProposalError as exc:
        print(f"方案文件非法: {exc}", file=sys.stderr)
        return 2


def _run(args) -> int:
    if args.command == "validate":
        dataset = load_dataset(args.data)
        print(f"数据集 {dataset.version}: 车辆 {len(dataset.vehicles)}，班次 {len(dataset.trips)}，"
              f"作业记录 {len(dataset.operations)}，覆盖目标 {len(dataset.targets)}")
        if dataset.issues:
            print("数据质量问题:")
            for issue in dataset.issues:
                print(f"  - [{issue.kind}] {issue.message}")
            return 1
        print("数据质量: 未发现引用问题")
        return 0

    if args.command == "report":
        dataset = load_dataset(args.data)
        metrics = compute_metrics(dataset)
        if args.route:
            metrics = [m for m in metrics if m.route_id == args.route]
        if args.json:
            print(json.dumps([m.as_dict() for m in metrics], ensure_ascii=False, indent=2))
        else:
            print(format_metrics(metrics, detail=args.detail))
        return 0

    if args.command == "compare":
        baseline = load_dataset(args.data)
        revised = load_dataset(args.other)
        comparison = compare_datasets(baseline, revised)
        if args.json:
            print(json.dumps(comparison.as_dict(), ensure_ascii=False, indent=2, default=str))
        else:
            print(format_comparison(comparison))
        return 0

    if args.command == "propose":
        dataset = load_dataset(args.data)
        proposal = load_proposal(args.proposal)
        report = evaluate_proposal(dataset, proposal)
        if args.json:
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_impact(report))
        return 1 if report.violations else 0

    if args.command == "save":
        dataset = load_dataset(args.data)
        proposal = load_proposal(args.proposal)
        report = evaluate_proposal(dataset, proposal)
        print(format_impact(report))
        if report.violations and not args.force:
            print("存在校验问题，未留存；如确认仍要留存请使用 --force", file=sys.stderr)
            return 1
        path = save_proposal(args.store, proposal, dataset.version, report)
        print(f"已留存: {path}（资料版本 {dataset.version}）")
        return 0

    if args.command == "review":
        rows = list_proposals(args.store)
        if not rows:
            print("暂无留存方案")
            return 0
        for row in rows:
            harmed = {True: "覆盖受损", False: "覆盖未受损", None: "未知"}[row["coverage_harmed"]]
            print(
                f"{row['proposal_id']} | {row['title']} | 资料版本 {row['dataset_version']} | "
                f"校验问题 {row['violations']} | {harmed} | 留存于 {row['saved_at']}"
            )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
