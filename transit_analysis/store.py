"""方案留存：选定方案连同所采用的资料版本写入本地 JSON 存储。

留存的记录包含方案全文、资料版本标识、评估结果与留存时间，
供下月复核时按同一版本重现结论。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def save_proposal(store_dir, proposal, dataset_version: str, report) -> Path:
    root = Path(store_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "proposal_id": proposal.proposal_id,
        "title": proposal.title,
        "note": proposal.note,
        "dataset_version": dataset_version,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "actions": proposal.actions,
        "evaluation": report.as_dict(),
    }
    path = root / f"{_safe_name(proposal.proposal_id)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_proposals(store_dir) -> list:
    root = Path(store_dir)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        evaluation = data.get("evaluation") or {}
        out.append(
            {
                "proposal_id": data.get("proposal_id"),
                "title": data.get("title"),
                "dataset_version": data.get("dataset_version"),
                "saved_at": data.get("saved_at"),
                "violations": len(evaluation.get("violations") or []),
                "coverage_harmed": evaluation.get("coverage_harmed"),
            }
        )
    return out


def load_saved_proposal(store_dir, proposal_id: str) -> dict:
    path = Path(store_dir) / f"{_safe_name(proposal_id)}.json"
    if not path.is_file():
        raise FileNotFoundError(f"未找到留存方案: {proposal_id}")
    return json.loads(path.read_text(encoding="utf-8"))
