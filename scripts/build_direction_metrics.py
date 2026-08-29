"""Compute direction-level price-return distributions from the local stockdb.

The script does not decide whether a direction passes investment thresholds.
It selects the longest available ETF history among products with exactly the
same source-confirmed tracking target, then preserves the selected proxy and
all data limitations in the local result files.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "data" / "local"
STOCKDB_PYTHON = Path(r"C:\tools\free-stockdb\app\stockdb\pybao")
START = "20160829"
END = "20260828"
MIN_FULL_WINDOW_DAYS = 365 * 8

sys.path.insert(0, str(PROJECT / "src"))
from etf_investment.market_data import DailyBar  # noqa: E402
from etf_investment.metrics import annualized_return, summarize  # noqa: E402


def valid_bars(rows: list[dict[str, Any]]) -> list[DailyBar]:
    result: list[DailyBar] = []
    for row in rows:
        try:
            close = float(row["close"])
            if close <= 0:
                continue
            raw_date = str(row["date"])
            trade_date = (
                date.fromisoformat(raw_date)
                if "-" in raw_date
                else date(int(raw_date) // 10000, int(raw_date[4:6]), int(raw_date[6:8]))
            )
            result.append(DailyBar(
                trade_date, float(row["open"]), float(row["high"]), float(row["low"]), close,
                float(row["volume"]) if row.get("volume") is not None else None,
                float(row["amount"]) if row.get("amount") is not None else None, "none",
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(result, key=lambda item: item.trade_date)


def period_metrics(bars: list[DailyBar], years: int) -> tuple[float | None, float | None]:
    end = bars[-1].trade_date
    target = date(end.year - years, end.month, min(end.day, 28))
    start = next((bar for bar in bars if bar.trade_date >= target), None)
    if start is None or (end - start.trade_date).days < int(years * 365 * 0.97):
        return None, None
    result = bars[-1].close / start.close - 1
    return result, annualized_return(start.close, bars[-1].close, (end - start.trade_date).days / 365.2425)


def load_many(rd: Any, codes: list[str]) -> dict[str, list[DailyBar]]:
    loaded: dict[str, list[DailyBar]] = {}
    for index in range(0, len(codes), 40):
        batch = codes[index:index + 40]
        raw = rd.get_data(batch, start=START, end=END, frequency="1d", fq=None)
        for code in batch:
            loaded[code] = valid_bars(raw.get(code, []))
        print(f"已读取 {min(index + len(batch), len(codes))}/{len(codes)} 个代理日线")
    return loaded


def main() -> None:
    if not STOCKDB_PYTHON.exists():
        raise SystemExit("未找到 free-stockdb SDK")
    sys.path.insert(0, str(STOCKDB_PYTHON))
    from stock_sdk import rd  # type: ignore[import-not-found]

    with (OUTPUT / "etf_universe_decisions.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        identities = [row for row in csv.DictReader(handle) if row["passive_tracking"] == "True"]
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in identities:
        groups[item["investment_direction"]].append(item)
    first_candidates = [sorted(items, key=lambda item: item["code"])[0]["code"] for items in groups.values()]
    bars_by_code = load_many(rd, first_candidates)

    # A short first proxy does not make a direction short.  Only then query its
    # same-target alternatives, which is the minimum needed replacement check.
    replacement_codes = sorted({
        item["code"]
        for direction, items in groups.items()
        if len(bars_by_code[sorted(items, key=lambda item: item["code"])[0]["code"]]) < MIN_FULL_WINDOW_DAYS
        for item in items
    } - set(bars_by_code))
    bars_by_code.update(load_many(rd, replacement_codes))

    results: list[dict[str, object]] = []
    for direction, items in sorted(groups.items()):
        best = max(items, key=lambda item: (len(bars_by_code.get(item["code"], [])), item["code"]))
        bars = bars_by_code.get(best["code"], [])
        if len(bars) < 2:
            results.append({
                "investment_direction": direction, "status": "data_unavailable", "proxy_code": best["code"],
                "proxy_name": best["name"], "same_target_etf_count": len(items), "data_note": "本地日线不足，未计算指标。",
            })
            continue
        values = summarize(bars)
        one_return, one_cagr = period_metrics(bars, 1)
        three_return, three_cagr = period_metrics(bars, 3)
        five_return, five_cagr = period_metrics(bars, 5)
        results.append({
            "investment_direction": direction, "status": "available", "proxy_code": best["code"],
            "proxy_name": best["name"], "same_target_etf_count": len(items),
            "data_start": values["data_start"], "data_end": values["data_end"],
            "trading_days": values["trading_days"], "history_years": values["history_years"],
            "return_basis": values["return_basis"], "cumulative_return": values["cumulative_return"],
            "cagr": values["cagr"], "return_1y": one_return, "cagr_1y": one_cagr,
            "return_3y": three_return, "cagr_3y": three_cagr,
            "return_5y": five_return, "cagr_5y": five_cagr,
            "max_drawdown": values["max_drawdown"], "max_drawdown_peak": values["max_drawdown_peak"],
            "max_drawdown_trough": values["max_drawdown_trough"], "max_drawdown_recovery": values["max_drawdown_recovery"],
            "current_drawdown": values["current_drawdown"], "annualized_volatility": values["annualized_volatility"],
            "rolling_3y_sample_count": values["rolling"]["3"]["sample_count"],
            "rolling_3y_median": values["rolling"]["3"]["median"],
            "rolling_3y_worst": values["rolling"]["3"]["worst"],
            "rolling_3y_best": values["rolling"]["3"]["best"],
            "rolling_3y_positive_ratio": values["rolling"]["3"]["positive_ratio"],
            "rolling_5y_sample_count": values["rolling"]["5"]["sample_count"],
            "rolling_5y_median": values["rolling"]["5"]["median"],
            "rolling_5y_worst": values["rolling"]["5"]["worst"],
            "rolling_5y_best": values["rolling"]["5"]["best"],
            "rolling_5y_positive_ratio": values["rolling"]["5"]["positive_ratio"],
            "data_note": "使用同一公开跟踪标的中本地日线最长的 ETF 代理；价格收益口径，未将分红复投计入。",
        })

    columns = sorted({key for row in results for key in row})
    with (OUTPUT / "direction_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(results)
    available = [row for row in results if row["status"] == "available"]
    summary = {
        "direction_count": len(results), "available_count": len(available),
        "data_unavailable_count": len(results) - len(available),
        "history_near_10y_count": sum(float(row["history_years"]) >= 9.95 for row in available),
        "source": "free-stockdb local daily data, fq=None, 2016-08-29 to 2026-08-28",
        "return_basis": "price_return",
    }
    (OUTPUT / "direction_metrics_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
