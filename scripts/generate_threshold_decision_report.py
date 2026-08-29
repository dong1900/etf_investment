"""Render the data-distribution report used for the later threshold decision."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import median


PROJECT = Path(__file__).resolve().parents[1]
LOCAL = PROJECT / "data" / "local"
OUTPUT = PROJECT / "docs" / "阈值决策报告.md"
NEAR_TEN_YEARS = 9.95  # 2016-08-29 to 2026-08-28 is one calendar day short of 10 years.


def number(row: dict[str, str], field: str) -> float | None:
    try:
        value = float(row.get(field, ""))
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def percentile(values: list[float], point: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * point
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def pct(value: float | None) -> str:
    return "样本不足" if value is None else f"{value:.2%}"


def distribution(rows: list[dict[str, str]], field: str) -> dict[str, float] | None:
    values = [value for row in rows if (value := number(row, field)) is not None]
    if not values:
        return None
    return {"n": len(values), "min": min(values), "p10": percentile(values, .10), "p25": percentile(values, .25), "median": median(values), "p75": percentile(values, .75), "p90": percentile(values, .90), "max": max(values)}


def report_distribution(name: str, result: dict[str, float] | None) -> list[str]:
    if result is None:
        return [f"| {name} | 0 | — | — | — | — | — | — | — |"]
    return [
        "| {name} | {n} | {minimum} | {p10} | {p25} | {median} | {p75} | {p90} | {maximum} |".format(
            name=name, n=int(result["n"]), minimum=pct(result["min"]), p10=pct(result["p10"]),
            p25=pct(result["p25"]), median=pct(result["median"]), p75=pct(result["p75"]),
            p90=pct(result["p90"]), maximum=pct(result["max"]),
        )
    ]


def closest(rows: list[dict[str, str]], field: str, threshold: float, higher_is_better: bool) -> list[dict[str, str]]:
    valid = [row for row in rows if number(row, field) is not None]
    return sorted(valid, key=lambda row: (abs(number(row, field) - threshold), row["investment_direction"]))[:8]


def main() -> None:
    with (LOCAL / "etf_universe_decisions.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        universe = list(csv.DictReader(handle))
    with (LOCAL / "direction_metrics.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        directions = [row for row in csv.DictReader(handle) if row["status"] == "available"]
    near_ten = [row for row in directions if (number(row, "history_years") or 0) >= NEAR_TEN_YEARS]
    distributions = {
        "全历史 CAGR": distribution(near_ten, "cagr"),
        "最大回撤": distribution(near_ten, "max_drawdown"),
        "3 年滚动正收益比例": distribution(near_ten, "rolling_3y_positive_ratio"),
        "5 年滚动正收益比例": distribution(near_ten, "rolling_5y_positive_ratio"),
        "年化波动率": distribution(near_ten, "annualized_volatility"),
    }
    lines = [
        "# 阈值决策报告", "",
        "> 文档状态：供用户确认正式阈值使用；本文不形成正式投资池，不采用或推荐任何阈值。", "",
        "## 研究范围与证据", "",
        "| 项目 | 数量 | 依据 |",
        "| --- | ---: | --- |",
        f"| 最新日线中证券简称含 ETF 的沪深候选 | {len(universe)} | free-stockdb 本地 2026-08-28 日线，代码与证券简称 |",
        f"| 明确指数型、纳入正式策略研究范围 | {sum(row['classification'] == 'included_passive_index' for row in universe)} | 天天基金网基金基本概况的基金类型为指数型且有跟踪标的 |",
        f"| 货币型 ETF，直接排除 | {sum(row['classification'] == 'excluded_money_market' for row in universe)} | 同一概况页的基金类型为货币型 |",
        f"| 映射失败／待核实 | {sum(row['classification'] == 'mapping_uncertain' for row in universe)} | 本次为 0；逐只原始结果仍保留在本地明细 |",
        f"| 形成的初始投资方向 | {len(directions)} | 以公开披露的“跟踪标的”原文作为方向键，尚未进行相似方向归并 |",
        "", "逐只 ETF 的代码、名称、基金类型、跟踪标的、纳入／排除状态、来源 URL 和判定依据保存在 `data/local/etf_universe_decisions.csv`；该数据快照不提交 Git。", "",
        "## 日线与代理口径", "",
        f"- 所有 {len(directions)} 个方向均有本地 ETF 日线代理；其中 {len(near_ten)} 个代理从 2016-08-29 至 2026-08-28，满足“近十年”研究长度（按 {NEAR_TEN_YEARS} 年处理一个日历日的边界差）。",
        "- 每个方向在相同公开跟踪标的的 ETF 中选取本地日线最长者，仅用于长期指标代理；这不是代表 ETF 选择，也未比较流动性、规模、费率或跟踪质量。",
        "- 日线调用 `fq=None`，以下全部收益为价格收益；未将分红再投资或 ETF／指数口径混合。", "",
        "## 近十年方向的真实指标分布", "",
        "| 指标 | 样本数 | 最小值 | P10 | P25 | 中位数 | P75 | P90 | 最大值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, result in distributions.items():
        lines.extend(report_distribution(name, result))

    lines.extend(["", "## 候选阈值影响（仅作分位数情景，不是正式规则）", "", "下表的候选值完全由近十年样本的 P25／中位数／P75 导出，目的仅是展示不同严格程度会留下多少方向。正式阈值尚未确认。", "", "| 情景 | 历史条件 | CAGR 条件 | 最大回撤条件 | 5 年滚动正收益条件 | 留下方向数 |", "| --- | --- | --- | --- | --- | ---: |"])
    cagr, drawdown, rolling = distributions["全历史 CAGR"], distributions["最大回撤"], distributions["5 年滚动正收益比例"]
    if cagr and drawdown and rolling:
        for label, quantile in (("分位数 P25", "p25"), ("分位数中位数", "median"), ("分位数 P75", "p75")):
            selected = [
                row for row in near_ten
                if number(row, "cagr") >= cagr[quantile]
                and number(row, "max_drawdown") >= drawdown[quantile]
                and number(row, "rolling_5y_positive_ratio") >= rolling[quantile]
            ]
            lines.append(f"| {label} | ≥ {NEAR_TEN_YEARS:.2f} 年 | ≥ {pct(cagr[quantile])} | ≥ {pct(drawdown[quantile])} | ≥ {pct(rolling[quantile])} | {len(selected)} |")
        lines.extend(["", "### 边界附近方向", "", "以下列出最接近每个‘中位数情景’单项候选值的 8 个方向，便于确认阈值微调的实际影响。", ""])
        for title, field, threshold, higher in (
            ("CAGR", "cagr", cagr["median"], True),
            ("最大回撤", "max_drawdown", drawdown["median"], True),
            ("5 年滚动正收益比例", "rolling_5y_positive_ratio", rolling["median"], True),
        ):
            lines.extend([f"#### {title}（候选值 {pct(threshold)}）", "", "| 投资方向 | 代理 ETF | 实际值 | 数据区间 |", "| --- | --- | ---: | --- |"])
            for row in closest(near_ten, field, threshold, higher):
                lines.append(f"| {row['investment_direction']} | {row['proxy_code']} {row['proxy_name']} | {pct(number(row, field))} | {row['data_start']} 至 {row['data_end']} |")
            lines.append("")
    lines.extend([
        "## 数据限制与正式决策点", "",
        "- 414 个方向的 ETF 代理不足近十年；这不是淘汰结论。后续如该方向进入重点研究，优先使用同方向可获得的指数或客观资产长期历史，再决定是否需要补数。",
        "- 478 个方向当前按跟踪标的原文拆分，名称近似或资产暴露相似的方向尚未去重；去重需保留独立比较证据，不能仅按相关性或名称自动合并。",
        "- 本报告只展示价格收益。若后续获得可核实的总收益／复权口径，应独立重算并明确不可与本报告直接混比。",
        "", "正式阈值确认前，系统不得据本报告将任何方向纳入、淘汰或降级为正式投资池。", "",
        "## 执行原则复核", "",
        "本次完成了‘买什么’之前的研究对象识别和数据分布展示，仍直接服务项目主线；未扩展为全市场数据治理，也未继续调查少数 free-stockdb 缺失。下一步最小必要动作是由用户基于本报告确认正式筛选阈值与判定规则版本。",
    ])
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成: {OUTPUT}")


if __name__ == "__main__":
    main()
