"""Validated daily-market-data input kept separate from source-specific clients."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .catalog import CatalogValidationError, _now, _optional
from .storage import Database


DAILY_COLUMNS = (
    "exchange", "code", "date", "open", "high", "low", "close", "volume", "amount",
    "adjustment", "source_name", "source_url", "source_as_of",
)
REQUIRED_DAILY_COLUMNS = ("exchange", "code", "date", "open", "high", "low", "close", "adjustment", "source_name", "source_as_of")
ADJUSTMENTS = {"none", "forward", "backward", "total_return"}


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    amount: float | None
    adjustment: str


class MarketDataService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def import_csv(self, path: str | Path) -> int:
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            missing = [column for column in REQUIRED_DAILY_COLUMNS if column not in headers]
            if missing:
                raise CatalogValidationError(f"日线文件缺少必填列: {', '.join(missing)}")
            rows = [self._normalize(row, number) for number, row in enumerate(reader, start=2)]
        if not rows:
            raise CatalogValidationError("日线文件没有数据行")
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            key = (row["exchange"], row["code"], row["trade_date"], row["adjustment"])
            if key in seen:
                raise CatalogValidationError(f"日线文件存在重复记录: {' '.join(key)}")
            seen.add(key)
        self.database.initialize()
        with self.database.session() as connection:
            connection.executemany(
                """
                INSERT INTO market_daily (
                    exchange, code, trade_date, open, high, low, close, volume, amount,
                    adjustment, source_name, source_url, source_as_of, imported_at
                ) VALUES (
                    :exchange, :code, :trade_date, :open, :high, :low, :close, :volume, :amount,
                    :adjustment, :source_name, :source_url, :source_as_of, :imported_at
                )
                ON CONFLICT(exchange, code, trade_date, adjustment) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                    volume=excluded.volume, amount=excluded.amount, source_name=excluded.source_name,
                    source_url=excluded.source_url, source_as_of=excluded.source_as_of,
                    imported_at=excluded.imported_at
                """,
                rows,
            )
        return len(rows)

    def series(self, exchange: str, code: str, adjustment: str = "none") -> list[DailyBar]:
        self.database.initialize()
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT trade_date, open, high, low, close, volume, amount, adjustment
                FROM market_daily
                WHERE exchange = ? AND code = ? AND adjustment = ?
                ORDER BY trade_date
                """,
                (exchange, code, adjustment),
            ).fetchall()
        return [
            DailyBar(
                trade_date=date.fromisoformat(row["trade_date"]), open=row["open"], high=row["high"],
                low=row["low"], close=row["close"], volume=row["volume"], amount=row["amount"],
                adjustment=row["adjustment"],
            )
            for row in rows
        ]

    @staticmethod
    def _normalize(source: dict[str, str | None], number: int) -> dict[str, object]:
        exchange = _optional(source.get("exchange"))
        code = _optional(source.get("code"))
        if exchange not in {"SSE", "SZSE"}:
            raise CatalogValidationError(f"第 {number} 行 exchange 必须为 SSE 或 SZSE")
        if code is None or len(code) != 6 or not code.isdigit():
            raise CatalogValidationError(f"第 {number} 行 code 必须为 6 位数字")
        trade_date = _optional(source.get("date"))
        try:
            date.fromisoformat(trade_date or "")
        except ValueError as error:
            raise CatalogValidationError(f"第 {number} 行 date 必须为 YYYY-MM-DD") from error
        prices: dict[str, float] = {}
        for field in ("open", "high", "low", "close"):
            try:
                prices[field] = float(_optional(source.get(field)) or "")
            except ValueError as error:
                raise CatalogValidationError(f"第 {number} 行 {field} 必须为数值") from error
            if prices[field] <= 0:
                raise CatalogValidationError(f"第 {number} 行 {field} 必须大于 0")
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
            raise CatalogValidationError(f"第 {number} 行 OHLC 不满足 low ≤ open/close ≤ high")
        optional_numbers: dict[str, float | None] = {}
        for field in ("volume", "amount"):
            raw = _optional(source.get(field))
            try:
                optional_numbers[field] = float(raw) if raw is not None else None
            except ValueError as error:
                raise CatalogValidationError(f"第 {number} 行 {field} 必须为数值或空") from error
            if optional_numbers[field] is not None and optional_numbers[field] < 0:
                raise CatalogValidationError(f"第 {number} 行 {field} 不能为负数")
        adjustment = _optional(source.get("adjustment"))
        if adjustment not in ADJUSTMENTS:
            raise CatalogValidationError(f"第 {number} 行 adjustment 必须为: {', '.join(sorted(ADJUSTMENTS))}")
        source_name = _optional(source.get("source_name"))
        source_as_of = _optional(source.get("source_as_of"))
        if source_name is None or source_as_of is None:
            raise CatalogValidationError(f"第 {number} 行 source_name 和 source_as_of 不能为空")
        return {
            "exchange": exchange, "code": code, "trade_date": trade_date,
            **prices, **optional_numbers, "adjustment": adjustment,
            "source_name": source_name, "source_url": _optional(source.get("source_url")),
            "source_as_of": source_as_of, "imported_at": _now(),
        }

