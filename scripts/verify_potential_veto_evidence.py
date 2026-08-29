"""Verify only the directions touched by the previous A/B/C candidates.

The source ETF metrics are deliberately retained, but raw ``fq=None`` ETF
prices never decide a veto here.  Where the tracking index code has been
confirmed from its compiler/exchange material, this script retrieves a public
daily *index price* series and calculates a separate evidence record.  A
missing or non-verifiable index is an explicit ``insufficient`` result, not an
invitation to expand into a market-wide data project.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import sys

PROJECT = Path(__file__).resolve().parents[1]
LOCAL = PROJECT / "data" / "local"
INPUT = LOCAL / "direction_longterm_metrics.csv"
OUTPUT = LOCAL / "potential_veto_evidence.csv"
HORIZON_YEARS = 9.95
KLINE_ENDPOINT = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart"
USER_AGENT = "ETF-investment-research/0.1 (bounded pre-veto verification)"

sys.path.insert(0, str(PROJECT / "src"))
from etf_investment.market_data import DailyBar  # noqa: E402
from etf_investment.metrics import summarize  # noqa: E402


# Codes below were checked against the named compiler/exchange source.  The
# public daily values are a separate delivery source, so both are recorded.
OFFICIAL_INDEX: dict[str, dict[str, str]] = {
    "上证180价值指数": {"market": "1", "code": "000029", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000029factsheet.pdf"},
    "上证180金融股指数": {"market": "1", "code": "000018", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000018factsheet.pdf"},
    "上证主要消费行业指数": {"market": "1", "code": "000036", "compiler": "上海证券交易所 / 中证指数", "proof": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-05-29/510630_20260529_1I0X.pdf"},
    "上证商品": {"market": "1", "code": "000066", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000066factsheet.pdf"},
    "上证综合指数": {"market": "1", "code": "000001", "compiler": "上海证券交易所", "proof": "https://www.sse.com.cn/market/sseindex/indexlist/s/i000001/const_list.shtml"},
    "中证主要消费指数": {"market": "1", "code": "000932", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000932factsheet.pdf"},
    "中证全指信息技术指数": {"market": "1", "code": "000993", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000993factsheet.pdf"},
    "中证全指医药卫生指数": {"market": "1", "code": "000991", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000991factsheet.pdf"},
    "中证军工指数": {"market": "0", "code": "399967", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/399967factsheet.pdf"},
    "中证医药卫生指数": {"market": "1", "code": "000933", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000933factsheet.pdf"},
    "沪深300医药卫生指数": {"market": "1", "code": "000913", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000913factsheet.pdf"},
    "沪深300非银行金融指数": {"market": "1", "code": "000849", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H30035factsheet.pdf"},
    "消费80": {"market": "1", "code": "000069", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000069factsheet.pdf"},
    "深证100指数(价格)": {"market": "0", "code": "399330", "compiler": "深证证券信息有限公司", "proof": "https://www.cnindex.com.cn/zh_information/research_reports/2021/202107/P020210713404509507837.pdf"},
    "深证成份指数(价格)": {"market": "0", "code": "399001", "compiler": "深证证券信息有限公司", "proof": "https://www.cnindex.com.cn/zh_information/notices_news/2015/201503/P020191213391353649687.pdf"},
    "深证电子信息传媒产业50指数": {"market": "0", "code": "399610", "compiler": "深证证券信息有限公司", "proof": "https://www.cnindex.com.cn/html2pdf/preview/jj_399610.pdf"},
    "细分医药": {"market": "1", "code": "000814", "compiler": "中证指数", "proof": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000814factsheet.pdf"},
    "恒生指数": {"market": "", "code": "HSI", "yahoo_symbol": "^HSI", "compiler": "恒生指数有限公司", "proof": "https://www.hsi.com.hk/eng/indexes/all-indexes/hsi"},
}

# These are deliberately not guessed from similarly named indices.  The first
# is also accompanied by an accumulated-NAV observation in the report, but it
# is not a total-return index substitute.
UNVERIFIED: dict[str, str] = {
    "上证城投债指数": "已确认跟踪标的名称，但未低成本取得可复现的长期指数序列；不以基金累计净值替代总收益指数。",
    "中证上海国企指数": "已发现相关指数线索，但本轮未取得可复现且代码响应一致的长期日线；不猜测替代代码。",
    "中证2000指数": "已确认指数代码为932000，但本轮公开日线接口返回代码不一致；不以错误响应继续计算。",
}


def decimal(row: dict[str, str], field: str) -> float | None:
    value = row.get(field, "")
    try:
        return float(value) if value != "" else None
    except ValueError:
        return None


def request_json(url: str) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            last = error
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def fetch_index(spec: dict[str, str]) -> tuple[list[DailyBar], str]:
    """Fetch a bounded index series and reject non-index code collisions.

    Eastmoney's public endpoint intermittently closes long requests. Yahoo's
    chart endpoint is used as delivery fallback, while the mapping itself is
    still independently evidenced by the compiler/exchange URL above.
    """
    suffix = "SS" if spec["market"] == "1" else "SZ"
    symbol = spec.get("yahoo_symbol") or f"{spec['code']}.{suffix}"
    url = f"{YAHOO_CHART_ENDPOINT}/{symbol}?period1=1262304000&period2=1788048000&interval=1d&events=history"
    payload = request_json(url)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"Yahoo chart 无结果：{(payload.get('chart') or {}).get('error')}")
    data = result[0]
    meta = data.get("meta") or {}
    if meta.get("instrumentType") != "INDEX" or str(meta.get("symbol")) != symbol:
        raise RuntimeError(f"响应不是目标指数：symbol={meta.get('symbol')} type={meta.get('instrumentType')}")
    timestamps = data.get("timestamp") or []
    quote = ((data.get("indicators") or {}).get("quote") or [{}])[0]
    bars: list[DailyBar] = []
    for index, timestamp in enumerate(timestamps):
        try:
            close = quote.get("close", [])[index]
            open_ = quote.get("open", [])[index]
            high = quote.get("high", [])[index]
            low = quote.get("low", [])[index]
            volume = quote.get("volume", [])[index]
            if None in (close, open_, high, low):
                continue
            bars.append(DailyBar(date.fromtimestamp(timestamp), float(open_), float(high), float(low), float(close), float(volume) if volume is not None else None, None, "none"))
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
    if len(bars) < 2:
        raise RuntimeError("日线数量不足")
    return bars, url


def common_window(bars: list[DailyBar], source_row: dict[str, str]) -> list[DailyBar]:
    start, end = date.fromisoformat(source_row["data_start"]), date.fromisoformat(source_row["data_end"])
    return [bar for bar in bars if start <= bar.trade_date <= end]


def metrics(prefix: str, values: dict[str, object]) -> dict[str, object]:
    return {
        f"{prefix}_start": values["data_start"], f"{prefix}_end": values["data_end"],
        f"{prefix}_days": values["trading_days"], f"{prefix}_years": values["history_years"],
        f"{prefix}_cagr": values["cagr"], f"{prefix}_max_drawdown": values["max_drawdown"],
        f"{prefix}_rolling_3y_positive_ratio": values["rolling"]["3"]["positive_ratio"],
        f"{prefix}_rolling_5y_positive_ratio": values["rolling"]["5"]["positive_ratio"],
        f"{prefix}_rolling_3y_sample_count": values["rolling"]["3"]["sample_count"],
        f"{prefix}_rolling_5y_sample_count": values["rolling"]["5"]["sample_count"],
    }


def candidate_group(row: dict[str, str]) -> str:
    cagr, r5, mdd = decimal(row, "cagr"), decimal(row, "rolling_5y_positive_ratio"), decimal(row, "max_drawdown")
    parts = ["A"] if cagr is not None and cagr <= 0 else []
    if cagr is not None and cagr <= 0 and r5 is not None and r5 <= .20:
        parts.append("B")
    if cagr is not None and cagr <= 0 and mdd is not None and mdd <= -.80:
        parts.append("C")
    return "+".join(parts)


def main() -> None:
    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle))
    candidates = [row for row in source if (decimal(row, "history_years") or 0) >= HORIZON_YEARS and (decimal(row, "cagr") or 0) <= 0]
    evidence: list[dict[str, object]] = []
    for number, row in enumerate(candidates, start=1):
        direction = row["investment_direction"]
        base: dict[str, object] = {
            "investment_direction": direction, "prior_candidate_group": candidate_group(row),
            "etf_proxy_code": row["proxy_code"], "etf_proxy_name": row["proxy_name"],
            "etf_return_basis": row["return_basis"], "etf_source": row["source_name"],
            "etf_data_start": row["data_start"], "etf_data_end": row["data_end"], "etf_history_years": row["history_years"],
            "etf_cagr": row["cagr"], "etf_max_drawdown": row["max_drawdown"],
            "etf_rolling_3y_positive_ratio": row["rolling_3y_positive_ratio"], "etf_rolling_5y_positive_ratio": row["rolling_5y_positive_ratio"],
        }
        spec = OFFICIAL_INDEX.get(direction)
        if spec is None:
            base.update({
                "verification_status": "evidence_insufficient", "verified_return_basis": "", "verified_source": "",
                "verified_code": "", "compiler": "", "mapping_proof_url": "", "data_url": "",
                "verification_note": UNVERIFIED.get(direction, "未找到本轮已核实映射。"),
                "formal_veto_evidence": "否：不得仅根据 ETF fq=None 原始价格收益执行基础否决。",
            })
            evidence.append(base)
            continue
        try:
            bars, data_url = fetch_index(spec)
            all_metrics = summarize(bars)
            overlap = common_window(bars, row)
            if len(overlap) < 2:
                raise RuntimeError("指数日线与 ETF 代理区间没有足够重叠")
            overlap_metrics = summarize(overlap)
            full_cagr, full_r5 = all_metrics["cagr"], all_metrics["rolling"]["5"]["positive_ratio"]
            supports_b = full_cagr is not None and full_cagr <= 0 and full_r5 is not None and full_r5 <= .20
            base.update({
                "verification_status": "verified_index_price", "verified_return_basis": "price_return_index",
                "verified_source": "Yahoo Finance 公开指数历史日线（代码由指数编制方/交易所材料独立核实）",
                "verified_code": spec["code"], "compiler": spec["compiler"], "mapping_proof_url": spec["proof"], "data_url": data_url,
                "verification_note": "响应已验证为 INDEX 且代码一致；不是 ETF fq=None 交易价格。价格指数仍不含分红再投资。",
                "formal_veto_evidence": "可作为候选规则的指数长期收益证据；正式淘汰仍须在规则 V1 确认后执行。" if supports_b else "不支持候选 B：核实后的指数长期收益未同时满足 CAGR ≤ 0 与 5年滚动正收益比例 ≤ 20%。",
                **metrics("verified_full", all_metrics), **metrics("verified_overlap", overlap_metrics),
                "overlap_cagr_difference_etf_minus_index": (decimal(row, "cagr") or 0) - (overlap_metrics["cagr"] or 0),
                "overlap_max_drawdown_difference_etf_minus_index": (decimal(row, "max_drawdown") or 0) - (overlap_metrics["max_drawdown"] or 0),
                "overlap_5y_positive_ratio_difference_etf_minus_index": (decimal(row, "rolling_5y_positive_ratio") or 0) - (overlap_metrics["rolling"]["5"]["positive_ratio"] or 0),
            })
        except Exception as error:
            base.update({
                "verification_status": "evidence_insufficient", "verified_return_basis": "", "verified_source": "", "verified_code": spec["code"],
                "compiler": spec["compiler"], "mapping_proof_url": spec["proof"], "data_url": "",
                "verification_note": f"已核实指数代码，但本轮日线获取失败：{type(error).__name__}: {error}",
                "formal_veto_evidence": "否：未取得可复现长期序列，不得仅根据 ETF fq=None 原始价格收益执行基础否决。",
            })
        evidence.append(base)
        print(f"核验 {number}/{len(candidates)}：{direction}")

    columns = sorted({key for row in evidence for key in row})
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader(); writer.writerows(evidence)
    summary = {
        "candidate_directions": len(evidence),
        "verified_index_price": sum(row["verification_status"] == "verified_index_price" for row in evidence),
        "evidence_insufficient": sum(row["verification_status"] == "evidence_insufficient" for row in evidence),
        "candidate_b_supported_by_verified_index": sum("可作为候选规则" in str(row.get("formal_veto_evidence")) for row in evidence),
    }
    (LOCAL / "potential_veto_evidence_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
