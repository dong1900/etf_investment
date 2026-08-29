"""Human-readable reports rendered from persisted evidence, never from hidden state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import CatalogService


def render_trace_markdown(catalog: CatalogService, subject_type: str, subject_key: str) -> str:
    events = catalog.trace(subject_type, subject_key)
    lines = [f"# {subject_type} {subject_key} 筛选证据链", ""]
    if not events:
        return "\n".join(lines + ["暂无已记录的筛选证据。", ""])
    lines.extend(["| 阶段 | 状态 | 规则版本 | 数据区间 | 最终影响 |", "| --- | --- | --- | --- | --- |"])
    for event in events:
        evidence = event["evidence"]
        lines.append("| {stage} | {status} | {version} | {period} | {impact} |".format(
            stage=event["stage"], status=event["status"], version=event["rule_version"] or "未使用阈值规则",
            period=evidence["data_period"], impact=evidence["impact"],
        ))
    for event in events:
        evidence: dict[str, Any] = event["evidence"]
        lines.extend(["", f"## {event['stage']}：{event['status']}", "", event["summary"], "", "### 机器可读证据", "", "```json", json.dumps(evidence, ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines) + "\n"


def write_trace_report(catalog: CatalogService, subject_type: str, subject_key: str, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_trace_markdown(catalog, subject_type, subject_key), encoding="utf-8")

