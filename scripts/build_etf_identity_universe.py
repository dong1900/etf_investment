"""Build a traceable ETF identity universe from verified local and public inputs.

This is deliberately an acquisition script, not a screening rule.  It reads
only a single latest-day local record per candidate from free-stockdb and
extracts product identity fields from each public fund profile page.  No market
history is downloaded and no investment threshold is applied.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "data" / "local"
STOCKDB_PYTHON = Path(r"C:\tools\free-stockdb\app\stockdb\pybao")
DATA_DATE = "20260828"
AS_OF = "2026-08-28"
PROFILE = "https://fundf10.eastmoney.com/jbgk_{code}.html"
USER_AGENT = "ETF-investment-research/0.1 (local personal research)"


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.values.append(value)


def profile_fields(code: str) -> dict[str, str | None]:
    """Fetch a single public profile with bounded retries and extract label values."""
    last_error: str | None = None
    for attempt in range(3):
        try:
            request = Request(PROFILE.format(code=code), headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=20) as response:
                parser = TextParser()
                parser.feed(response.read().decode("utf-8", errors="replace"))
            labels = {"基金类型", "跟踪标的", "业绩比较基准"}
            result: dict[str, str | None] = {"fund_type": None, "tracking_target": None, "benchmark": None}
            names = {"基金类型": "fund_type", "跟踪标的": "tracking_target", "业绩比较基准": "benchmark"}
            for index, value in enumerate(parser.values[:-1]):
                if value in labels:
                    result[names[value]] = parser.values[index + 1]
            return {**result, "error": None}
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = f"{type(error).__name__}: {error}"
            time.sleep(0.5 * (attempt + 1))
    return {"fund_type": None, "tracking_target": None, "benchmark": None, "error": last_error}


def classify(name: str, fund_type: str | None, target: str | None) -> tuple[str, bool, str]:
    """Classify only facts stated by the source; uncertain records are not promoted."""
    if fund_type and "货币" in fund_type:
        return "excluded_money_market", False, "公开概况页的基金类型为货币型，属于正式需求的可直接排除范围。"
    if fund_type and "指数型" in fund_type and target:
        return "included_passive_index", True, "基金类型明确为指数型，且公开概况页列有跟踪标的。"
    if target and any(term in target for term in ("黄金", "Au99.99", "原油", "商品", "白银")):
        return "included_objective_asset", True, "公开概况页列有可识别的客观资产跟踪标的。"
    if fund_type and "指数" not in fund_type:
        return "excluded_non_index", False, "基金类型未标明指数型，不能作为具有明确被动规则的正式策略研究对象。"
    return "mapping_uncertain", False, "公开概况页未能同时确认指数型基金类型和可用跟踪标的；不以名称推测。"


def main() -> None:
    if not STOCKDB_PYTHON.exists():
        raise SystemExit(f"未找到 free-stockdb SDK: {STOCKDB_PYTHON}")
    sys.path.insert(0, str(STOCKDB_PYTHON))
    from stock_sdk import rd  # type: ignore[import-not-found]

    # Two server-side prefix queries, then client-side name filtering.  This is
    # intentionally not a per-security database scan.
    rows: list[dict[str, object]] = []
    for prefix in ("1*", "5*"):
        rows.extend(rd.vals("日k", prefix, DATA_DATE).do())
    candidates = sorted(
        (row for row in rows if "ETF" in str(row.get("name", "")).upper()),
        key=lambda row: str(row["code"]),
    )

    previous: dict[str, dict[str, str]] = {}
    previous_path = OUTPUT / "etf_universe_decisions.csv"
    if previous_path.exists():
        with previous_path.open("r", encoding="utf-8-sig", newline="") as handle:
            previous = {row["code"]: row for row in csv.DictReader(handle)}
    fetched: dict[str, dict[str, str | None]] = {
        str(row["code"]): {
            "fund_type": previous[str(row["code"])]["fund_type"] or None,
            "tracking_target": previous[str(row["code"])]["tracking_target"] or None,
            "benchmark": previous[str(row["code"])]["benchmark"] or None,
            "error": None,
        }
        for row in candidates
        if str(row["code"]) in previous and not previous[str(row["code"])]["fetch_error"]
    }
    retry_candidates = [row for row in candidates if str(row["code"]) not in fetched]
    with ThreadPoolExecutor(max_workers=1) as executor:
        tasks = {executor.submit(profile_fields, str(row["code"])): str(row["code"]) for row in retry_candidates}
        for number, task in enumerate(as_completed(tasks), start=1):
            code = tasks[task]
            fetched[code] = task.result()
            print(f"已重试 {number}/{len(retry_candidates)}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    decisions: list[dict[str, object]] = []
    for row in candidates:
        code, name = str(row["code"]), str(row["name"])
        profile = fetched[code]
        classification, passive, basis = classify(name, profile["fund_type"], profile["tracking_target"])
        exchange = "SSE" if code.startswith("5") else "SZSE"
        direction = profile["tracking_target"] or "映射待核实"
        decisions.append({
            "exchange": exchange, "code": code, "name": name,
            "fund_type": profile["fund_type"], "tracking_target": profile["tracking_target"],
            "benchmark": profile["benchmark"], "investment_direction": direction,
            "classification": classification, "passive_tracking": passive,
            "basis": basis, "source_name": "天天基金网基金基本概况（页面标注数据来源：东方财富Choice）",
            "source_url": PROFILE.format(code=code), "source_as_of": AS_OF,
            "fetch_error": profile["error"], "generated_at": now,
        })

    all_columns = list(decisions[0])
    with (OUTPUT / "etf_universe_decisions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_columns)
        writer.writeheader()
        writer.writerows(decisions)
    included = [row for row in decisions if row["passive_tracking"]]
    identity_columns = [
        "exchange", "code", "name", "tracking_target", "asset_type", "passive_tracking", "listing_date",
        "source_name", "source_url", "source_as_of", "source_record_id",
    ]
    with (OUTPUT / "etf_passive_identities.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=identity_columns)
        writer.writeheader()
        for row in included:
            writer.writerow({
                "exchange": row["exchange"], "code": row["code"], "name": row["name"],
                "tracking_target": row["tracking_target"], "asset_type": row["fund_type"] or "客观资产跟踪",
                "passive_tracking": "true", "listing_date": "", "source_name": row["source_name"],
                "source_url": row["source_url"], "source_as_of": row["source_as_of"], "source_record_id": row["code"],
            })
    summary = {
        "as_of": AS_OF, "candidate_count": len(decisions), "included_count": len(included),
        "classification_counts": {key: sum(row["classification"] == key for row in decisions) for key in sorted({str(row["classification"]) for row in decisions})},
        "profile_fetch_failures": sum(row["fetch_error"] is not None for row in decisions),
        "direction_count": len({row["investment_direction"] for row in included}),
        "source": "free-stockdb local latest daily records + 天天基金网基金基本概况",
    }
    (OUTPUT / "etf_universe_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
