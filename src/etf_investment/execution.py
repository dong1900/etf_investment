"""Confirmed plans, holdings and deterministic daily action suggestions."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from .catalog import CatalogValidationError, _now
from .storage import Database


class ExecutionService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_plan(self, plan: dict[str, Any]) -> None:
        required = {"direction_key", "exchange", "code", "strategy", "status"}
        missing = sorted(required - set(plan))
        if missing:
            raise CatalogValidationError(f"投资计划缺少字段: {', '.join(missing)}")
        if plan["strategy"] not in {"DCA", "DCA_GRID", "OBSERVE"}:
            raise CatalogValidationError("strategy 必须为 DCA、DCA_GRID 或 OBSERVE")
        if plan["status"] not in {"ACTIVE", "OBSERVE", "STOP_ADDING"}:
            raise CatalogValidationError("status 必须为 ACTIVE、OBSERVE 或 STOP_ADDING")
        amount = plan.get("base_amount")
        if plan["status"] == "ACTIVE" and (not isinstance(amount, (int, float)) or amount <= 0):
            raise CatalogValidationError("ACTIVE 计划必须提供大于 0 的 base_amount")
        next_date = plan.get("next_execution_date")
        if next_date:
            try:
                date.fromisoformat(next_date)
            except ValueError as error:
                raise CatalogValidationError("next_execution_date 必须为 YYYY-MM-DD") from error
        self.database.initialize()
        with self.database.session() as connection:
            exists = connection.execute(
                "SELECT 1 FROM etf_identity WHERE exchange = ? AND code = ?", (plan["exchange"], plan["code"])
            ).fetchone()
            if exists is None:
                raise CatalogValidationError("投资计划的 ETF 必须先存在于已核实身份清单")
            connection.execute(
                """
                INSERT INTO investment_plan(
                    direction_key, exchange, code, strategy, status, base_amount, frequency,
                    next_execution_date, cash_reserve, rule_version, note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(direction_key) DO UPDATE SET
                    exchange=excluded.exchange, code=excluded.code, strategy=excluded.strategy,
                    status=excluded.status, base_amount=excluded.base_amount, frequency=excluded.frequency,
                    next_execution_date=excluded.next_execution_date, cash_reserve=excluded.cash_reserve,
                    rule_version=excluded.rule_version, note=excluded.note, updated_at=excluded.updated_at
                """,
                (
                    plan["direction_key"], plan["exchange"], plan["code"], plan["strategy"], plan["status"],
                    amount, plan.get("frequency"), next_date, plan.get("cash_reserve", 0),
                    plan.get("rule_version"), plan.get("note"), _now(),
                ),
            )

    def save_holding(self, holding: dict[str, Any]) -> None:
        for field in ("account", "exchange", "code", "quantity"):
            if field not in holding:
                raise CatalogValidationError(f"持仓缺少字段: {field}")
        if holding["quantity"] < 0:
            raise CatalogValidationError("持仓数量不能为负数")
        self.database.initialize()
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO holding(account, exchange, code, quantity, average_cost, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account, exchange, code) DO UPDATE SET
                    quantity=excluded.quantity, average_cost=excluded.average_cost, updated_at=excluded.updated_at
                """,
                (holding["account"], holding["exchange"], holding["code"], holding["quantity"], holding.get("average_cost"), _now()),
            )

    def daily_actions(self, as_of: date) -> list[dict[str, Any]]:
        """Only confirmed active plans can produce an action; market moves cannot alter a plan."""
        self.database.initialize()
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT p.*, i.name, i.tracking_target
                FROM investment_plan p
                JOIN etf_identity i ON i.exchange=p.exchange AND i.code=p.code
                WHERE p.status = 'ACTIVE' AND p.next_execution_date IS NOT NULL
                  AND p.next_execution_date <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM execution_record e
                      WHERE e.plan_direction_key = p.direction_key
                        AND e.side = 'BUY'
                        AND e.executed_date >= p.next_execution_date
                  )
                ORDER BY p.next_execution_date, p.direction_key
                """,
                (as_of.isoformat(),),
            ).fetchall()
        return [
            {
                "exchange": row["exchange"], "code": row["code"], "name": row["name"],
                "direction": row["direction_key"], "action": "BUY",
                "amount": row["base_amount"], "strategy": row["strategy"],
                "rule_version": row["rule_version"], "data_date": as_of.isoformat(),
                "reason": f"已确认计划的执行日期为 {row['next_execution_date']}；尚未记录完成。",
            }
            for row in rows
        ]

    def record_execution(self, execution: dict[str, Any]) -> str:
        required = {"account", "exchange", "code", "executed_date", "side"}
        missing = sorted(required - set(execution))
        if missing:
            raise CatalogValidationError(f"执行记录缺少字段: {', '.join(missing)}")
        if execution["side"] not in {"BUY", "SELL"}:
            raise CatalogValidationError("side 必须为 BUY 或 SELL")
        date.fromisoformat(execution["executed_date"])
        execution_id = str(uuid.uuid4())
        self.database.initialize()
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO execution_record(
                    execution_id, plan_direction_key, account, exchange, code, executed_date,
                    side, quantity, amount, price, note, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (execution_id, execution.get("plan_direction_key"), execution["account"], execution["exchange"],
                 execution["code"], execution["executed_date"], execution["side"], execution.get("quantity"),
                 execution.get("amount"), execution.get("price"), execution.get("note"), _now()),
            )
        return execution_id
