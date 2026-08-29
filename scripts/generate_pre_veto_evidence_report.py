"""Render the bounded pre-veto evidence verification report."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
INPUT = PROJECT / "data" / "local" / "potential_veto_evidence.csv"
OUTPUT = PROJECT / "docs" / "淘汰前证据核验报告.md"


def value(row: dict[str, str], field: str) -> float | None:
    try:
        return float(row[field]) if row.get(field, "") != "" else None
    except ValueError:
        return None


def pct(number: float | None) -> str:
    return "—" if number is None else f"{number * 100:.2f}%"


def clean(item: str | None) -> str:
    return (item or "—").replace("|", "\\|")


def row_table(rows: list[dict[str, str]]) -> list[str]:
    lines = [
        "| 投资方向 | 原 ETF 代理 | ETF CAGR | ETF 最大回撤 | ETF 5年正收益 | 核验来源 / 代码 | 核验 CAGR | 核验最大回撤 | 核验5年正收益 | 证据状态 | 可否作为正式淘汰证据 |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for item in rows:
        source = f"{item.get('compiler') or '—'} / {item.get('verified_code') or '—'}"
        lines.append(
            "| {direction} | {proxy} ({code}) | {etf_cagr} | {etf_mdd} | {etf_r5} | {source} | {index_cagr} | {index_mdd} | {index_r5} | {status} | {decision} |".format(
                direction=clean(item.get("investment_direction")), proxy=clean(item.get("etf_proxy_name")), code=clean(item.get("etf_proxy_code")),
                etf_cagr=pct(value(item, "etf_cagr")), etf_mdd=pct(value(item, "etf_max_drawdown")), etf_r5=pct(value(item, "etf_rolling_5y_positive_ratio")),
                source=clean(source), index_cagr=pct(value(item, "verified_full_cagr")), index_mdd=pct(value(item, "verified_full_max_drawdown")),
                index_r5=pct(value(item, "verified_full_rolling_5y_positive_ratio")), status=clean(item.get("verification_status")),
                decision=clean(item.get("formal_veto_evidence")),
            )
        )
    return lines


def main() -> None:
    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    verified = [row for row in rows if row["verification_status"] == "verified_index_price"]
    insufficient = [row for row in rows if row["verification_status"] != "verified_index_price"]
    b_supported = [row for row in verified if "可作为候选规则" in row.get("formal_veto_evidence", "")]

    lines = [
        "# 淘汰前证据核验报告",
        "",
        f"> 生成日期：{date.today().isoformat()}。范围严格限于此前候选 A/B/C 实际涉及的 {len(rows)} 个方向；本报告**不采用正式基础否决规则、不淘汰任何方向、不形成投资池**。",
        "",
        "## 核验结论",
        "",
        f"- 已获得独立、代码一致的长期指数价格序列：{len(verified)} 个方向。",
        f"- 证据不足、暂不执行基础否决：{len(insufficient)} 个方向。",
        f"- 以“已核实长期序列 CAGR ≤ 0 且 5年滚动正收益比例 ≤ 20%”检查：{len(b_supported)} 个方向同时满足；当前没有任何对象可据此进入正式淘汰。",
        "- 原先候选 A/B/C 使用 ETF `fq=None` 原始交易价格，现全部撤回为正式候选的依据；这些原始数值只保留为“待核实信号”。",
        "",
        "## 数据口径与判断规则",
        "",
        "1. ETF 原始结果来自 free-stockdb 本地日线 `fq=None`，口径为价格收益，可能受分红、份额折算及复权语义影响；它不能单独触发基础否决。",
        "2. 核验序列的指数代码先由指数编制方／交易所公开材料确认，再由 Yahoo Finance 公开历史接口交付日线；响应必须同时满足 `instrumentType=INDEX` 和代码／符号一致，才标为 `verified_index_price`。",
        "3. 当前取得的是**价格指数**，而非总收益指数，仍不计分红再投资；但它是与 ETF 交易价格独立的、可验证的指数长期序列。总收益指数仍优先于此口径。",
        "4. 公开交付接口若返回代码碰撞（例如同六码股票）、非 INDEX 响应、没有序列或无法稳定复现，即标为 `evidence_insufficient`；不猜测代码、不改用相似指数、不开展全市场补数。",
        "",
        "## 全部 21 个潜在淘汰方向",
        "",
        *row_table(rows),
        "",
        "## 已核实序列：ETF 原始价格与指数结果的差异",
        "",
        "下表的“同区间指数”使用 ETF 原始代理的同一开始／结束日期，以隔离时间区间差异；“全历史指数”使用指数可得的完整日线。差异为 ETF 原始值减同区间指数值。",
        "",
        "| 投资方向 | ETF 原始区间 | 同区间指数 CAGR | ETF－指数 CAGR 差异 | 同区间指数最大回撤 | ETF－指数回撤差异 | 同区间指数5年正收益 | ETF－指数5年正收益差异 | 全历史指数区间 / CAGR / 5年正收益 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in verified:
        full = f"{row['verified_full_start']} 至 {row['verified_full_end']} / {pct(value(row, 'verified_full_cagr'))} / {pct(value(row, 'verified_full_rolling_5y_positive_ratio'))}"
        lines.append(
            "| {direction} | {start} 至 {end} | {ocagr} | {dcagr} | {omdd} | {dmdd} | {or5} | {dr5} | {full} |".format(
                direction=clean(row["investment_direction"]), start=row["etf_data_start"], end=row["etf_data_end"],
                ocagr=pct(value(row, "verified_overlap_cagr")), dcagr=pct(value(row, "overlap_cagr_difference_etf_minus_index")),
                omdd=pct(value(row, "verified_overlap_max_drawdown")), dmdd=pct(value(row, "overlap_max_drawdown_difference_etf_minus_index")),
                or5=pct(value(row, "verified_overlap_rolling_5y_positive_ratio")), dr5=pct(value(row, "overlap_5y_positive_ratio_difference_etf_minus_index")), full=clean(full),
            )
        )
    lines += [
        "",
        "上证综合与深证成份均出现 ETF 原始价格显著为负、而同区间独立指数为正且滚动正收益比例显著更高的情况。这直接证明原 ETF `fq=None` 结果不足以支持淘汰。恒生指数的独立序列同样为正 CAGR；其同区间 5 年滚动结果较低，但未同时满足双重负向证据。",
        "",
        "## 证据不足对象与停止边界",
        "",
        "| 投资方向 | 已核实的跟踪标的线索 | 停止原因 | 当前状态 |",
        "| --- | --- | --- | --- |",
    ]
    for row in insufficient:
        proof = row.get("mapping_proof_url") or "—"
        lines.append(f"| {clean(row['investment_direction'])} | {clean(row.get('verified_code') or proof)} | {clean(row.get('verification_note'))} | 证据不足，暂不执行基础否决 |")
    lines += [
        "",
        "特别说明：上证城投债、上证综合、深证成份、消费80均已纳入本轮。上证综合、深证成份已经完成独立指数核验；上证城投债和消费80因未取得低成本、可复现且无代码碰撞的长期交付序列而保留证据不足。基金页面的累计净值可观察到拆分／派送字段，但累计净值并不自动等同于已验证的复利总收益指数，因此未用来替代决定性指数证据。",
        "",
        "## 重新提出的基础否决候选（未采用）",
        "",
        "**候选 B′：证据合格的双重长期不合格。**仅当同一方向存在优先级合格的长期序列（总收益指数、可验证的指数／客观资产长期历史，或已明确处理分红、复权和份额变化的 ETF 历史），且其全历史 CAGR ≤ 0、5 年滚动正收益比例 ≤ 20%，才作为基础否决候选。最大回撤和波动率只保留作横向风险收益解释，不单独硬否决。",
        "",
        f"本轮已核实序列中满足 B′ 的方向数为 {len(b_supported)}。这不是“零淘汰”规则，也不是正式阈值；它只表明当前不能把原 ETF 价格信号转换为正式淘汰。待拥有合格序列的方向增多后，可按同一证据链重新运行。",
        "",
        "机器可读明细：`data/local/potential_veto_evidence.csv`（本地、不提交 Git）。其中每行保留 ETF 原始指标、核验来源、指数代码、数据 URL、完整／同区间指标、差异和正式证据状态。",
        "",
        "## 暂停点与执行原则复核",
        "",
        "- 本次解决了什么：对会被原始 ETF 负收益信号触发的 21 个方向逐项做淘汰前证据核验，验证了 ETF 原始价格不能作为决定性淘汰证据。",
        "- 是否仍直接服务主线：是，直接服务“买什么”的基础否决证据可靠性。",
        "- 新的非阻塞问题：18 个方向尚无本轮可复现的合格长期交付序列；已记录为证据不足，不扩展为全市场数据治理。",
        "- 已可停止深入的事项：不继续寻找更多供应商、不自动补齐 478 个方向、不执行任何淘汰。",
        "- 下一步最小必要动作：用户确认、调整或否决候选 B′（基础否决规则 V1）。",
    ]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
