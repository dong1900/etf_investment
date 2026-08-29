"""Supplement short ETF histories with strictly matched public index histories.

Only directions whose ETF proxy is shorter than the project research horizon
are considered.  A direction is supplemented only when its source-disclosed
tracking-target name has one unique, transparent match in the public index
directory.  No fuzzy match and no guessed index code is accepted.
"""

from __future__ import annotations

import csv
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


PROJECT = Path(__file__).resolve().parents[1]
LOCAL = PROJECT / "data" / "local"
HISTORY_HORIZON_YEARS = 9.95
DIRECTORY_ENDPOINT = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_ENDPOINT = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
USER_AGENT = "ETF-investment-research/0.1 (local personal research)"

import sys
sys.path.insert(0, str(PROJECT / "src"))
from etf_investment.market_data import DailyBar  # noqa: E402
from etf_investment.metrics import annualized_return, summarize  # noqa: E402


def request_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def normalize_name(value: str) -> str:
    """Only remove explicit generic suffixes; do not infer similar exposures."""
    value = re.sub(r"[\s()（）]", "", value)
    value = re.sub(r"指数$", "", value)
    return value


def index_directory() -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    # Eastmoney's public directory separates Shanghai (m:1) and Shenzhen
    # (m:0) index records. The market is preserved for later secid construction.
    for market, total in (("1", 179), ("0", 282)):
        for page in range(1, math.ceil(total / 100) + 1):
            url = (
                f"{DIRECTORY_ENDPOINT}?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3"
                f"&fs=m%3A{market}%2Bs%3A2&fields=f12%2Cf14"
            )
            for row in request_json(url).get("data", {}).get("diff", []):
                code, name = str(row.get("f12", "")), str(row.get("f14", ""))
                if code and name:
                    result.append({"market": market, "code": code, "name": name})
    return result


def index_bars(index: dict[str, str]) -> tuple[list[DailyBar], str | None]:
    secid = f"{index['market']}.{index['code']}"
    url = (
        f"{KLINE_ENDPOINT}?secid={secid}&klt=101&fqt=0&beg=20100101&end=20260828&lmt=0"
        "&fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6"
        "&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61"
    )
    try:
        payload = request_json(url)
        data = payload.get("data") or {}
        if str(data.get("code")) != index["code"]:
            return [], "响应代码与目录代码不一致"
        bars = []
        for raw in data.get("klines") or []:
            fields = raw.split(",")
            if len(fields) < 5:
                continue
            try:
                bars.append(DailyBar(
                    date.fromisoformat(fields[0]), float(fields[1]), float(fields[3]), float(fields[4]), float(fields[2]),
                    float(fields[5]) if len(fields) > 5 else None,
                    float(fields[6]) if len(fields) > 6 else None, "none",
                ))
            except (ValueError, TypeError):
                continue
        return bars, None
    except Exception as error:  # failures are retained as data limitations
        return [], f"{type(error).__name__}: {error}"


def period_metrics(bars: list[DailyBar], years: int) -> tuple[float | None, float | None]:
    end = bars[-1].trade_date
    target = date(end.year - years, end.month, min(end.day, 28))
    start = next((bar for bar in bars if bar.trade_date >= target), None)
    if start is None or (end - start.trade_date).days < int(years * 365 * .97):
        return None, None
    total = bars[-1].close / start.close - 1
    return total, annualized_return(start.close, bars[-1].close, (end - start.trade_date).days / 365.2425)


def metric_row(base: dict[str, str], bars: list[DailyBar], index: dict[str, str]) -> dict[str, object]:
    values = summarize(bars)
    one, one_cagr = period_metrics(bars, 1)
    three, three_cagr = period_metrics(bars, 3)
    five, five_cagr = period_metrics(bars, 5)
    return {
        **base, "source_type": "public_index", "source_name": "东方财富公开沪深指数目录与历史日线接口",
        "source_url": f"{KLINE_ENDPOINT}?secid={index['market']}.{index['code']}",
        "source_code": index["code"], "source_index_name": index["name"],
        "mapping_status": "unique_exact_normalized_match",
        "mapping_basis": "跟踪标的与公开目录名称仅去除通用‘指数’后唯一相同。",
        "data_start": values["data_start"], "data_end": values["data_end"], "trading_days": values["trading_days"],
        "history_years": values["history_years"], "return_basis": "price_return",
        "cumulative_return": values["cumulative_return"], "cagr": values["cagr"],
        "return_1y": one, "cagr_1y": one_cagr, "return_3y": three, "cagr_3y": three_cagr,
        "return_5y": five, "cagr_5y": five_cagr, "max_drawdown": values["max_drawdown"],
        "annual_returns": json.dumps(values["annual_returns"], ensure_ascii=False, sort_keys=True),
        "annual_return_mean": values["annual_return_mean"], "annual_return_median": values["annual_return_median"],
        "positive_year_ratio": values["positive_year_ratio"], "annual_return_best": values["annual_return_best"],
        "annual_return_worst": values["annual_return_worst"], "current_year_ytd": values["current_year_ytd"],
        "max_drawdown_peak": values["max_drawdown_peak"], "max_drawdown_trough": values["max_drawdown_trough"],
        "max_drawdown_recovery": values["max_drawdown_recovery"], "current_drawdown": values["current_drawdown"],
        "annualized_volatility": values["annualized_volatility"],
        "rolling_3y_sample_count": values["rolling"]["3"]["sample_count"], "rolling_3y_median": values["rolling"]["3"]["median"],
        "rolling_3y_worst": values["rolling"]["3"]["worst"], "rolling_3y_best": values["rolling"]["3"]["best"],
        "rolling_3y_positive_ratio": values["rolling"]["3"]["positive_ratio"],
        "rolling_5y_sample_count": values["rolling"]["5"]["sample_count"], "rolling_5y_median": values["rolling"]["5"]["median"],
        "rolling_5y_worst": values["rolling"]["5"]["worst"], "rolling_5y_best": values["rolling"]["5"]["best"],
        "rolling_5y_positive_ratio": values["rolling"]["5"]["positive_ratio"],
        "data_note": "公开指数未复权价格日线；仅用于 ETF 历史不足方向的长期价值研究，不用于 ETF 可交易策略回测。",
    }


def main() -> None:
    with (LOCAL / "direction_metrics.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        original = list(csv.DictReader(handle))
    catalog = index_directory()
    by_name: dict[str, list[dict[str, str]]] = {}
    for item in catalog:
        by_name.setdefault(normalize_name(item["name"]), []).append(item)

    mapping_rows: list[dict[str, object]] = []
    eligible: list[tuple[dict[str, str], dict[str, str]]] = []
    for row in original:
        years = float(row.get("history_years") or 0)
        if years >= HISTORY_HORIZON_YEARS:
            continue
        matches = by_name.get(normalize_name(row["investment_direction"]), [])
        status = "no_exact_match" if not matches else "ambiguous_exact_match" if len(matches) > 1 else "matched"
        mapping = {"investment_direction": row["investment_direction"], "etf_proxy_code": row["proxy_code"], "etf_history_years": years,
                   "normalized_target": normalize_name(row["investment_direction"]), "mapping_status": status,
                   "match_count": len(matches), "index_code": matches[0]["code"] if len(matches) == 1 else "",
                   "index_name": matches[0]["name"] if len(matches) == 1 else ""}
        mapping_rows.append(mapping)
        if len(matches) == 1:
            eligible.append((row, matches[0]))

    fetched: dict[str, tuple[list[DailyBar], str | None, dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(index_bars, index): (row, index) for row, index in eligible}
        for number, task in enumerate(as_completed(tasks), start=1):
            row, index = tasks[task]
            bars, error = task.result()
            fetched[row["investment_direction"]] = (bars, error, index)
            if number % 25 == 0 or number == len(tasks):
                print(f"已读取 {number}/{len(tasks)} 条严格匹配指数日线")

    merged: list[dict[str, object]] = []
    for row in original:
        found = fetched.get(row["investment_direction"])
        if found is not None and len(found[0]) >= 2:
            merged.append(metric_row(row, found[0], found[2]))
        else:
            merged.append({
                **row, "source_type": "etf_proxy", "source_name": "free-stockdb 本地日线", "source_url": "",
                "source_code": row["proxy_code"], "source_index_name": "", "mapping_status": "not_used",
                "mapping_basis": "ETF 代理已有近十年历史" if float(row.get("history_years") or 0) >= HISTORY_HORIZON_YEARS else "无唯一严格指数名称匹配或指数日线不可用。",
            })
    for mapping in mapping_rows:
        item = fetched.get(str(mapping["investment_direction"]))
        mapping["history_fetch_error"] = item[1] if item else ""
        mapping["index_trading_days"] = len(item[0]) if item else 0

    columns = sorted({key for row in merged for key in row})
    with (LOCAL / "direction_longterm_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader(); writer.writerows(merged)
    mapping_columns = sorted({key for row in mapping_rows for key in row})
    with (LOCAL / "direction_index_mapping.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=mapping_columns)
        writer.writeheader(); writer.writerows(mapping_rows)
    summary = {
        "total_directions": len(merged), "short_etf_directions": len(mapping_rows), "unique_exact_index_matches": len(eligible),
        "index_history_used": sum(row["source_type"] == "public_index" for row in merged),
        "near_10y_after_supplement": sum(float(row.get("history_years") or 0) >= HISTORY_HORIZON_YEARS for row in merged),
        "remaining_short_or_unavailable": sum(float(row.get("history_years") or 0) < HISTORY_HORIZON_YEARS for row in merged),
        "return_basis": "price_return only; ETF and index series remain source-labeled",
    }
    (LOCAL / "direction_longterm_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
