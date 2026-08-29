"""Merge freshly recomputed ETF metrics with previously verified index supplements.

This is a network-free recovery path. It preserves only index rows already
written by the strict-match script with their original source labels; all other
directions come from the newly recomputed ETF proxy metrics.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
LOCAL = PROJECT / "data" / "local"
HISTORY_HORIZON_YEARS = 9.95


def main() -> None:
    final_path = LOCAL / "direction_longterm_metrics.csv"
    with (LOCAL / "direction_metrics.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        fresh = list(csv.DictReader(handle))
    with final_path.open("r", encoding="utf-8-sig", newline="") as handle:
        previous = {row["investment_direction"]: row for row in csv.DictReader(handle)}
    merged: list[dict[str, object]] = []
    for row in fresh:
        prior = previous.get(row["investment_direction"])
        if prior and prior.get("source_type") == "public_index":
            merged.append(prior)
        else:
            merged.append({
                **row, "source_type": "etf_proxy", "source_name": "free-stockdb 本地日线", "source_url": "",
                "source_code": row["proxy_code"], "source_index_name": "", "mapping_status": "not_used",
                "mapping_basis": "ETF 代理已有近十年历史" if float(row.get("history_years") or 0) >= HISTORY_HORIZON_YEARS else "尚未找到唯一严格指数名称匹配。",
            })
    columns = sorted({key for row in merged for key in row})
    with final_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader(); writer.writerows(merged)
    summary = {
        "total_directions": len(merged),
        "index_history_used": sum(row["source_type"] == "public_index" for row in merged),
        "near_10y_after_supplement": sum(float(row.get("history_years") or 0) >= HISTORY_HORIZON_YEARS for row in merged),
        "remaining_short_or_unavailable": sum(float(row.get("history_years") or 0) < HISTORY_HORIZON_YEARS for row in merged),
        "recovery_note": "复用此前唯一严格名称匹配且已验证的指数补数；未在网络失败时新增任何匹配。",
    }
    (LOCAL / "direction_longterm_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
