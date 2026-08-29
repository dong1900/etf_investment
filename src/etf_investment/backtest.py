"""Small, deterministic cash-flow backtests for comparing explicitly supplied rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Iterable, Sequence

from .market_data import DailyBar
from .metrics import maximum_drawdown


@dataclass(frozen=True)
class CashFlow:
    when: date
    amount: float  # Investor perspective: investment is negative; terminal value is positive.


@dataclass(frozen=True)
class BacktestResult:
    strategy: str
    total_invested: float
    final_assets: float
    total_return: float | None
    xirr: float | None
    maximum_drawdown: float | None
    operations: int
    max_capital_occupied: float
    cash_reserve: float
    idle_cash: float
    capital_utilization: float | None


def xirr(cashflows: Iterable[CashFlow]) -> float | None:
    """Solve annualized IRR from dated cash flows without third-party libraries."""
    flows = sorted(cashflows, key=lambda item: item.when)
    if len(flows) < 2 or not any(flow.amount < 0 for flow in flows) or not any(flow.amount > 0 for flow in flows):
        return None
    origin = flows[0].when

    def npv(rate: float) -> float:
        return sum(flow.amount / (1 + rate) ** ((flow.when - origin).days / 365.2425) for flow in flows)

    low, high = -0.9999, 1.0
    low_value, high_value = npv(low), npv(high)
    while low_value * high_value > 0 and high < 1_000_000:
        high *= 2
        high_value = npv(high)
    if not isfinite(low_value) or not isfinite(high_value) or low_value * high_value > 0:
        return None
    for _ in range(120):
        middle = (low + high) / 2
        value = npv(middle)
        if abs(value) < 1e-10:
            return middle
        if low_value * value <= 0:
            high, high_value = middle, value
        else:
            low, low_value = middle, value
    return (low + high) / 2


def fixed_dca(
    bars: Sequence[DailyBar],
    *,
    amount: float,
    frequency: str = "monthly",
    cash_reserve: float = 0.0,
) -> BacktestResult:
    """Buy at each selected trading day's close; frequency is part of input evidence."""
    if amount <= 0:
        raise ValueError("定投金额必须大于 0")
    if cash_reserve < 0:
        raise ValueError("现金预留不能为负数")
    if frequency not in {"monthly", "weekly", "daily"}:
        raise ValueError("frequency 必须为 monthly、weekly 或 daily")
    if not bars:
        raise ValueError("无法回测空日线序列")

    units = 0.0
    total_invested = 0.0
    cashflows: list[CashFlow] = []
    previous_period: tuple[int, int] | int | None = None
    for bar in bars:
        if frequency == "monthly":
            period: tuple[int, int] | int = (bar.trade_date.year, bar.trade_date.month)
        elif frequency == "weekly":
            iso = bar.trade_date.isocalendar()
            period = (iso.year, iso.week)
        else:
            period = bar.trade_date.toordinal()
        if period == previous_period:
            continue
        previous_period = period
        units += amount / bar.close
        total_invested += amount
        cashflows.append(CashFlow(bar.trade_date, -amount))
    final_assets = units * bars[-1].close
    cashflows.append(CashFlow(bars[-1].trade_date, final_assets))
    normalized = [
        DailyBar(bar.trade_date, 1, 1, 1, units * bar.close, None, None, bar.adjustment)
        for bar in bars
    ]
    drawdown = maximum_drawdown(normalized)
    occupied = total_invested + cash_reserve
    return BacktestResult(
        strategy="固定定投", total_invested=total_invested, final_assets=final_assets,
        total_return=final_assets / total_invested - 1 if total_invested else None,
        xirr=xirr(cashflows), maximum_drawdown=drawdown.maximum if drawdown else None,
        operations=len(cashflows) - 1, max_capital_occupied=occupied, cash_reserve=cash_reserve,
        idle_cash=cash_reserve, capital_utilization=total_invested / occupied if occupied else None,
    )

