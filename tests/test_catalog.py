from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from etf_investment.catalog import CatalogService, CatalogValidationError
from etf_investment.market_data import DailyBar
from etf_investment.metrics import summarize
from etf_investment.reporting import render_trace_markdown
from etf_investment.backtest import fixed_dca
from etf_investment.execution import ExecutionService
from etf_investment.storage import Database


class CatalogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.service = CatalogService(Database(self.path / "research.sqlite3"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_csv(self, rows: list[dict[str, str]]) -> Path:
        path = self.path / "identities.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_import_keeps_exchange_and_tracking_target(self) -> None:
        path = self._write_csv([
            {
                "exchange": "SSE", "code": "510300", "name": "沪深300ETF",
                "tracking_target": "沪深300", "asset_type": "宽基", "passive_tracking": "true",
                "listing_date": "2012-05-28", "source_name": "人工核实样本",
                "source_url": "", "source_as_of": "2026-08-29", "source_record_id": "sample-1",
            },
            {
                "exchange": "SZSE", "code": "159915", "name": "创业板ETF",
                "tracking_target": "创业板指", "asset_type": "宽基", "passive_tracking": "1",
                "listing_date": "2011-12-09", "source_name": "人工核实样本",
                "source_url": "", "source_as_of": "2026-08-29", "source_record_id": "sample-2",
            },
        ])
        self.assertEqual(self.service.import_csv(path), 2)
        identities = self.service.list_identities()
        self.assertEqual([(row["exchange"], row["code"]) for row in identities], [("SZSE", "159915"), ("SSE", "510300")])
        self.assertEqual(identities[1]["tracking_target"], "沪深300")

    def test_rejects_duplicate_exchange_and_code(self) -> None:
        row = {
            "exchange": "SSE", "code": "510300", "name": "沪深300ETF",
            "tracking_target": "沪深300", "asset_type": "宽基", "passive_tracking": "true",
            "source_name": "测试", "source_as_of": "2026-08-29",
        }
        with self.assertRaisesRegex(CatalogValidationError, "重复证券"):
            self.service.import_csv(self._write_csv([row, row.copy()]))

    def test_events_are_append_only_and_require_evidence(self) -> None:
        event = self.service.record_event(
            subject_type="ETF", subject_key="SSE:510300", stage="研究范围识别",
            status="通过", rule_version="scope-v1", summary="具有明确指数跟踪规则。",
            evidence={
                "data_period": "截至 2026-08-29 的产品身份资料",
                "metrics": [{"name": "被动跟踪", "actual": True, "unit": "布尔"}],
                "decision_basis": "明确指数跟踪规则",
                "impact": "进入投资方向识别",
            },
        )
        trace = self.service.trace("ETF", "SSE:510300")
        self.assertEqual(trace[0]["event_id"], event)
        self.assertEqual(trace[0]["evidence"]["impact"], "进入投资方向识别")
        self.assertIn("进入投资方向识别", render_trace_markdown(self.service, "ETF", "SSE:510300"))
        with self.assertRaisesRegex(CatalogValidationError, "缺少字段"):
            self.service.record_event(
                subject_type="ETF", subject_key="SSE:510300", stage="测试", status="通过",
                summary="缺少证据", evidence={},
            )

    def test_daily_data_metrics_labels_price_return_and_drawdown(self) -> None:
        bars = [
            DailyBar(date(2020, 1, 1), 10, 10, 10, 10, None, None, "none"),
            DailyBar(date(2021, 1, 1), 12, 12, 12, 12, None, None, "none"),
            DailyBar(date(2022, 1, 1), 9, 9, 9, 9, None, None, "none"),
            DailyBar(date(2023, 1, 2), 11, 11, 11, 11, None, None, "none"),
        ]
        results = summarize(bars)
        self.assertEqual(results["return_basis"], "price_return")
        self.assertAlmostEqual(results["max_drawdown"], -0.25)
        self.assertEqual(results["trading_days"], 4)

    def test_fixed_dca_uses_explicit_monthly_cash_flows(self) -> None:
        bars = [
            DailyBar(date(2020, 1, 2), 10, 10, 10, 10, None, None, "none"),
            DailyBar(date(2020, 1, 31), 11, 11, 11, 11, None, None, "none"),
            DailyBar(date(2020, 2, 3), 8, 8, 8, 8, None, None, "none"),
            DailyBar(date(2020, 2, 28), 10, 10, 10, 10, None, None, "none"),
        ]
        result = fixed_dca(bars, amount=100, frequency="monthly", cash_reserve=50)
        self.assertEqual(result.operations, 2)
        self.assertEqual(result.total_invested, 200)
        self.assertAlmostEqual(result.final_assets, 225)
        self.assertEqual(result.cash_reserve, 50)

    def test_daily_action_only_uses_confirmed_active_plan(self) -> None:
        self.service.import_csv(self._write_csv([{
            "exchange": "SSE", "code": "510300", "name": "沪深300ETF",
            "tracking_target": "沪深300", "asset_type": "宽基", "passive_tracking": "true",
            "source_name": "测试", "source_as_of": "2026-08-29",
        }]))
        execution = ExecutionService(self.service.database)
        execution.save_plan({
            "direction_key": "沪深300", "exchange": "SSE", "code": "510300", "strategy": "DCA",
            "status": "ACTIVE", "base_amount": 1000, "frequency": "monthly",
            "next_execution_date": "2026-08-28", "rule_version": "plan-v1",
        })
        actions = execution.daily_actions(date(2026, 8, 29))
        self.assertEqual(actions[0]["action"], "BUY")
        self.assertEqual(actions[0]["amount"], 1000)
        execution.record_execution({
            "plan_direction_key": "沪深300", "account": "模拟账户", "exchange": "SSE", "code": "510300",
            "executed_date": "2026-08-29", "side": "BUY", "amount": 1000,
        })
        self.assertEqual(execution.daily_actions(date(2026, 8, 29)), [])
