"""Generate a decision report for *candidate* basic-veto rules.

This script intentionally does not write a formal rule set or an investment
pool.  It turns the verified direction-level metrics into a review document so
that the product owner can choose (or reject) a simple V1 veto rule.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
INPUT = PROJECT / "data" / "local" / "direction_longterm_metrics.csv"
OUTPUT = PROJECT / "docs" / "基础否决规则候选报告.md"
HORIZON_YEARS = 9.95


def number(row: dict[str, str], field: str) -> float | None:
    value = row.get(field, "")
    try:
        return float(value) if value not in ("", None) else None
    except ValueError:
        return None


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def text(value: str | None) -> str:
    return (value or "—").replace("|", "\\|")


def quantile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def direction(row: dict[str, str]) -> str:
    return row.get("investment_direction", "")


def metrics_table(rows: list[dict[str, str]], decisive: str) -> list[str]:
    lines = [
        "| 投资方向 | 数据代理 / 代码 | 数据来源 | 区间 | CAGR | 最大回撤 | 3年滚动正收益 | 5年滚动正收益 | 波动率 | 年度正收益比例 | 决定性条件 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in sorted(rows, key=lambda item: number(item, "cagr") or 0):
        lines.append(
            "| {direction} | {proxy} / {code} | {source} | {start} 至 {end} | {cagr} | {mdd} | {r3} | {r5} | {vol} | {annual} | {decisive} |".format(
                direction=text(direction(row)), proxy=text(row.get("proxy_name")), code=text(row.get("source_code")),
                source=text(row.get("source_type")), start=text(row.get("data_start")), end=text(row.get("data_end")),
                cagr=pct(number(row, "cagr")), mdd=pct(number(row, "max_drawdown")),
                r3=pct(number(row, "rolling_3y_positive_ratio")), r5=pct(number(row, "rolling_5y_positive_ratio")),
                vol=pct(number(row, "annualized_volatility")), annual=pct(number(row, "positive_year_ratio")), decisive=decisive,
            )
        )
    return lines


def candidate_count(rows: list[dict[str, str]], cagr_limit: float, five_year_limit: float | None = None, drawdown_limit: float | None = None) -> list[dict[str, str]]:
    chosen = [row for row in rows if (number(row, "cagr") or 0) <= cagr_limit]
    if five_year_limit is not None:
        chosen = [row for row in chosen if (number(row, "rolling_5y_positive_ratio") or 0) <= five_year_limit]
    if drawdown_limit is not None:
        chosen = [row for row in chosen if (number(row, "max_drawdown") or 0) <= drawdown_limit]
    return chosen


def main() -> None:
    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        all_rows = list(csv.DictReader(handle))
    research_rows = [row for row in all_rows if (number(row, "history_years") or 0) >= HORIZON_YEARS]
    etf_rows = [row for row in research_rows if row.get("source_type") == "etf_proxy"]
    index_rows = [row for row in research_rows if row.get("source_type") == "public_index"]
    short_rows = [row for row in all_rows if row not in research_rows]

    cagr_non_positive = candidate_count(research_rows, 0.0)
    recurring_loss = candidate_count(research_rows, 0.0, 0.20)
    uncompensated_extreme_risk = candidate_count(research_rows, 0.0, drawdown_limit=-0.80)
    near_cagr_zero = [row for row in research_rows if -0.02 < (number(row, "cagr") or 0) <= 0.02]

    cagr = [number(row, "cagr") for row in research_rows if number(row, "cagr") is not None]
    mdd = [number(row, "max_drawdown") for row in research_rows if number(row, "max_drawdown") is not None]
    r3 = [number(row, "rolling_3y_positive_ratio") for row in research_rows if number(row, "rolling_3y_positive_ratio") is not None]
    r5 = [number(row, "rolling_5y_positive_ratio") for row in research_rows if number(row, "rolling_5y_positive_ratio") is not None]
    vol = [number(row, "annualized_volatility") for row in research_rows if number(row, "annualized_volatility") is not None]
    source_counts = Counter(row.get("source_type") or "unknown" for row in research_rows)

    lines = [
        "# 基础否决规则候选报告",
        "",
        f"> 生成日期：{date.today().isoformat()}。本报告只提出候选规则和实际影响，**未采用任何正式阈值、未执行正式淘汰、未形成投资池**。",
        "",
        "## 决策边界与口径",
        "",
        "已确认的筛选框架为“基础否决 → 横向比较 → 同类去重”。本报告只覆盖第一层；第二、三层尚未开始。候选规则的目的仅是排除有明确、长期且多项不合格证据的方向，不能把普通指标低于样本中位数当作淘汰理由。",
        "",
        "所有收益均为日线**价格收益**（非总收益）；ETF 价格序列未计入分红再投资，公开指数也可能与全收益指数不同。因此不同收益口径不能拿来作精确排名。本报告的 0% CAGR 仅是一个保守的候选边界，仍需产品确认后才可能成为规则。",
        "",
        "## 长期数据覆盖",
        "",
        f"- 原始投资方向：{len(all_rows)} 个。",
        f"- 可用于近十年长期研究（历史 ≥ {HORIZON_YEARS:.2f} 年）：{len(research_rows)} 个；其中 ETF 价格代理 {len(etf_rows)} 个，严格唯一名称匹配的公开指数补数 {len(index_rows)} 个。",
        f"- 历史不足或尚无可核实严格补数：{len(short_rows)} 个；**不因历史不足本身执行基础否决**。",
        "- 指数补数只接受公开目录中去除通用“指数”后唯一相同的跟踪标的名称；本轮仅补到“中证800指数→000906 中证800”和“中证红利指数→000922 中证红利”。未做模糊匹配、未猜测指数代码。",
        f"- 近十年样本来源：{', '.join(f'{key} {value}' for key, value in sorted(source_counts.items()))}。",
        "",
        "## 扩大后近十年样本的原始分布（仅展示，不构成阈值）",
        "",
        "| 指标 | 最小值 | P25 | 中位数 | P75 | 最大值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| CAGR | {pct(min(cagr))} | {pct(quantile(cagr, .25))} | {pct(quantile(cagr, .5))} | {pct(quantile(cagr, .75))} | {pct(max(cagr))} |",
        f"| 最大回撤 | {pct(min(mdd))} | {pct(quantile(mdd, .25))} | {pct(quantile(mdd, .5))} | {pct(quantile(mdd, .75))} | {pct(max(mdd))} |",
        f"| 3年滚动正收益比例 | {pct(min(r3))} | {pct(quantile(r3, .25))} | {pct(quantile(r3, .5))} | {pct(quantile(r3, .75))} | {pct(max(r3))} |",
        f"| 5年滚动正收益比例 | {pct(min(r5))} | {pct(quantile(r5, .25))} | {pct(quantile(r5, .5))} | {pct(quantile(r5, .75))} | {pct(max(r5))} |",
        f"| 年化波动率 | {pct(min(vol))} | {pct(quantile(vol, .25))} | {pct(quantile(vol, .5))} | {pct(quantile(vol, .75))} | {pct(max(vol))} |",
        "",
        "这些统计量用于理解样本，不是 P25／中位数／P75 阈值。由于只有 66 个方向有近十年价格历史，不能据此为全部 478 个方向制定全体正式标准。",
        "",
        "## 候选规则与实际影响",
        "",
        "### 候选 A：长期价格 CAGR ≤ 0",
        "",
        "规则表达：历史不少于 9.95 年，且全期价格 CAGR ≤ 0。它只识别“长期价格没有正增长”的方向；不以回撤、波动率单独否决。受价格收益口径限制，候选 A 必须在确认时评估是否改为总收益口径或加入明确例外。",
        "",
        f"- 候选淘汰：{len(cagr_non_positive)} / {len(research_rows)} 个近十年方向。",
        f"- 不触及：{len(short_rows)} 个历史不足方向。",
        "",
        *metrics_table(cagr_non_positive, "CAGR ≤ 0"),
        "",
        "### 候选 B：长期不增长，且 5 年滚动正收益比例 ≤ 20%",
        "",
        "规则表达：同时满足候选 A，且可计算的 5 年滚动窗口中正收益比例不超过 20%。这不是“5 年正收益低于中位数即淘汰”，而是要求长期不增长之外，还出现极少数 5 年正收益窗口的双重证据。",
        "",
        f"- 候选淘汰：{len(recurring_loss)} / {len(research_rows)} 个近十年方向。",
        "",
        *metrics_table(recurring_loss, "CAGR ≤ 0 且 5年正收益比例 ≤ 20%"),
        "",
        "### 候选 C：长期不增长，且最大回撤 ≥ 80%（以绝对跌幅表述）",
        "",
        "规则表达：同时满足候选 A，且最大回撤 ≤ -80%。这是风险与收益联合的候选规则：不是因为回撤大就淘汰，而是极端回撤又没有长期价格增长作为补偿时才触发。未提出任何单独波动率或单独回撤硬门槛。",
        "",
        f"- 候选淘汰：{len(uncompensated_extreme_risk)} / {len(research_rows)} 个近十年方向。",
        "",
        *metrics_table(uncompensated_extreme_risk, "CAGR ≤ 0 且最大回撤 ≤ -80%"),
        "",
        "## 边界敏感性（只显示影响，不选择数值）",
        "",
        "| 候选条件变化 | 受影响方向数 | 说明 |",
        "| --- | ---: | --- |",
        f"| CAGR ≤ -2% | {len(candidate_count(research_rows, -.02))} | 比候选 A 少 {len(cagr_non_positive) - len(candidate_count(research_rows, -.02))} 个；仅接受明显长期负增长。 |",
        f"| CAGR ≤ 0% | {len(cagr_non_positive)} | 候选 A。 |",
        f"| CAGR ≤ 2% | {len(candidate_count(research_rows, .02))} | 比候选 A 多 {len(candidate_count(research_rows, .02)) - len(cagr_non_positive)} 个；会开始触及低正增长方向。 |",
        f"| 候选 A + 5年正收益 ≤ 10% | {len(candidate_count(research_rows, 0, .10))} | 比候选 B 更严格。 |",
        f"| 候选 A + 5年正收益 ≤ 20% | {len(recurring_loss)} | 候选 B。 |",
        f"| 候选 A + 5年正收益 ≤ 30% | {len(candidate_count(research_rows, 0, .30))} | 比候选 B 多 {len(candidate_count(research_rows, 0, .30)) - len(recurring_loss)} 个。 |",
        f"| 候选 A + 最大回撤 ≤ -70% | {len(candidate_count(research_rows, 0, drawdown_limit=-.70))} | 联合风险收益证据。 |",
        f"| 候选 A + 最大回撤 ≤ -80% | {len(uncompensated_extreme_risk)} | 候选 C。 |",
        f"| 候选 A + 最大回撤 ≤ -90% | {len(candidate_count(research_rows, 0, drawdown_limit=-.90))} | 只留下最极端回撤。 |",
        "",
        "CAGR 靠近零的边界方向如下。它们说明 0% 改为 2% 会开始排除仍然正增长的对象，因此不应在本报告中自动采用。",
        "",
        *metrics_table(near_cagr_zero, "CAGR 位于 -2% 至 2% 边界区"),
        "",
        "## 年度稳定性与数据限制",
        "",
        "年度收益及年度正收益比例已保留在机器可读明细中。ETF 代理行可复现年度收益；两条公开指数补数的首次采集只保留了核心长期指标，年度序列尚未补采，因此表中为“—”，不应据此作年度稳定性比较。",
        "",
        "机器可读明细：`data/local/direction_longterm_metrics.csv`（本地数据，不提交 Git）；严格映射审计：`data/local/direction_index_mapping.csv`。字段保留数据来源、代码、区间、价格收益口径、ETF 代理／公开指数标识，以及所有原始指标。",
        "",
        "## 本轮结论与暂停点",
        "",
        "- 本轮没有把 ETF 历史不足等同于投资方向历史不足；在可公开、可核实且严格匹配的范围内，近十年覆盖从 64 提升到 66。",
        "- 不为补齐覆盖率进行全市场数据治理，不开展 free-stockdb 全市场完整性扫描；其余对象如后续确实阻塞研究，再按方向逐项补充或标注数据不足。",
        "- 候选 A/B/C 均未成为正式规则，也没有执行淘汰或形成正式投资池。",
        "- **暂停等待产品决策：确认、调整或否决“基础否决规则 V1”。**确认后才可执行基础否决，并继续横向比较、同类去重与代表 ETF 选择。",
        "",
        "## 执行原则复核",
        "",
        "- 本次解决了什么：扩大可核实的投资方向长期历史覆盖，并把基础否决的候选规则及实际影响呈现为可复现证据。",
        "- 是否仍直接服务主线：是，直接服务“买什么”的长期价值筛选前置决策。",
        "- 新的非阻塞问题：412 个方向尚无近十年可核实严格补数；已记录，不扩展为数据治理。",
        "- 已可停止深入的事项：不继续扩展指数映射、不自动设定正式阈值、不形成投资池。",
        "- 下一步最小必要动作：由用户确认“基础否决规则 V1”。",
    ]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print({"research_directions": len(research_rows), "candidate_A": len(cagr_non_positive), "candidate_B": len(recurring_loss), "candidate_C": len(uncompensated_extreme_risk)})


if __name__ == "__main__":
    main()
