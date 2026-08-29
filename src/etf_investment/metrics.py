"""Deterministic long-term metrics with explicit price/total-return labeling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from calendar import monthrange
from bisect import bisect_left
from math import sqrt
from statistics import median, stdev
from typing import Sequence

from .market_data import DailyBar


@dataclass(frozen=True)
class Drawdown:
    maximum: float
    peak_date: date
    trough_date: date
    recovery_date: date | None
    current: float


def annualized_return(start: float, end: float, years: float) -> float | None:
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def period_return(bars: Sequence[DailyBar]) -> float | None:
    if len(bars) < 2:
        return None
    return bars[-1].close / bars[0].close - 1


def maximum_drawdown(bars: Sequence[DailyBar]) -> Drawdown | None:
    if not bars:
        return None
    peak = bars[0]
    max_drawdown = 0.0
    trough = bars[0]
    drawdowns: list[tuple[DailyBar, float, DailyBar]] = []
    for bar in bars:
        if bar.close > peak.close:
            peak = bar
        drawdown = bar.close / peak.close - 1
        drawdowns.append((bar, drawdown, peak))
        if drawdown < max_drawdown:
            max_drawdown, trough = drawdown, bar
            peak_at_trough = peak
    if max_drawdown == 0:
        peak_at_trough = bars[0]
    recovery = next((bar.trade_date for bar, _, _ in drawdowns if bar.trade_date > trough.trade_date and bar.close >= peak_at_trough.close), None)
    current_peak = max(bar.close for bar in bars)
    return Drawdown(max_drawdown, peak_at_trough.trade_date, trough.trade_date, recovery, bars[-1].close / current_peak - 1)


def annualized_volatility(bars: Sequence[DailyBar], trading_days: int = 252) -> float | None:
    if len(bars) < 3:
        return None
    returns = [bars[index].close / bars[index - 1].close - 1 for index in range(1, len(bars))]
    return stdev(returns) * sqrt(trading_days)


def rolling_returns(bars: Sequence[DailyBar], years: int) -> list[float]:
    if years <= 0:
        raise ValueError("years 必须大于 0")
    result: list[float] = []
    dates = [bar.trade_date for bar in bars]
    for start_index, start_bar in enumerate(bars):
        target_year = start_bar.trade_date.year + years
        target = date(
            target_year,
            start_bar.trade_date.month,
            min(start_bar.trade_date.day, monthrange(target_year, start_bar.trade_date.month)[1]),
        )
        end_index = bisect_left(dates, target, lo=start_index + 1)
        if end_index < len(bars):
            result.append(bars[end_index].close / start_bar.close - 1)
    return result


def summarize(bars: Sequence[DailyBar]) -> dict[str, object]:
    """Return only values justified by supplied data; insufficient periods are null."""
    if not bars:
        raise ValueError("无法计算空日线序列")
    years = (bars[-1].trade_date - bars[0].trade_date).days / 365.2425
    annual = {}
    for bar in bars:
        annual.setdefault(bar.trade_date.year, [bar.close, bar.close])
        annual[bar.trade_date.year][1] = bar.close
    annual_returns = {str(year): end / start - 1 for year, (start, end) in annual.items() if start > 0 and year != bars[0].trade_date.year}
    rolls = {window: rolling_returns(bars, window) for window in (3, 5)}
    drawdown = maximum_drawdown(bars)
    return {
        "data_start": bars[0].trade_date.isoformat(), "data_end": bars[-1].trade_date.isoformat(),
        "trading_days": len(bars), "history_years": years,
        "return_basis": "total_return" if bars[0].adjustment == "total_return" else "price_return",
        "cumulative_return": period_return(bars),
        "cagr": annualized_return(bars[0].close, bars[-1].close, years),
        "annual_returns": annual_returns,
        "annual_return_mean": sum(annual_returns.values()) / len(annual_returns) if annual_returns else None,
        "annual_return_median": median(annual_returns.values()) if annual_returns else None,
        "positive_year_ratio": sum(value > 0 for value in annual_returns.values()) / len(annual_returns) if annual_returns else None,
        "max_drawdown": drawdown.maximum if drawdown else None,
        "max_drawdown_peak": drawdown.peak_date.isoformat() if drawdown else None,
        "max_drawdown_trough": drawdown.trough_date.isoformat() if drawdown else None,
        "max_drawdown_recovery": drawdown.recovery_date.isoformat() if drawdown and drawdown.recovery_date else None,
        "current_drawdown": drawdown.current if drawdown else None,
        "annualized_volatility": annualized_volatility(bars),
        "rolling": {
            str(window): {
                "sample_count": len(values), "median": median(values) if values else None,
                "worst": min(values) if values else None, "best": max(values) if values else None,
                "positive_ratio": sum(value > 0 for value in values) / len(values) if values else None,
            }
            for window, values in rolls.items()
        },
    }
