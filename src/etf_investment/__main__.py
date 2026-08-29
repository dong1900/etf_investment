"""Command-line entry point for the local V1 research store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import CatalogService, identities_to_csv, write_identity_template
from .market_data import MarketDataService
from .metrics import summarize
from .reporting import write_trace_report
from .rules import RuleRegistry
from .backtest import fixed_dca
from dataclasses import asdict
from .storage import Database


def _database_path(value: str) -> Database:
    return Database(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF 投资辅助工具 V1")
    parser.add_argument("--database", default="data/local/etf_investment.sqlite3", help="本地 SQLite 文件路径")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="初始化本地研究数据库")
    template = commands.add_parser("identity-template", help="创建 ETF 身份清单 CSV 表头")
    template.add_argument("path")
    importer = commands.add_parser("import-identities", help="导入已核实来源的 ETF 身份清单")
    importer.add_argument("path")
    commands.add_parser("list-identities", help="导出当前 ETF 身份清单 CSV")
    daily = commands.add_parser("import-daily", help="导入已核实来源的 ETF 日线 CSV")
    daily.add_argument("path")
    metrics = commands.add_parser("metrics", help="计算 ETF 日线长期指标 JSON")
    metrics.add_argument("exchange", choices=("SSE", "SZSE"))
    metrics.add_argument("code")
    metrics.add_argument("--adjustment", default="none", choices=("none", "forward", "backward", "total_return"))
    backtest = commands.add_parser("backtest-fixed-dca", help="执行固定定投基准回测 JSON")
    backtest.add_argument("exchange", choices=("SSE", "SZSE"))
    backtest.add_argument("code")
    backtest.add_argument("--amount", type=float, required=True)
    backtest.add_argument("--frequency", default="monthly", choices=("monthly", "weekly", "daily"))
    backtest.add_argument("--cash-reserve", type=float, default=0.0)
    backtest.add_argument("--adjustment", default="none", choices=("none", "forward", "backward", "total_return"))
    trace = commands.add_parser("trace", help="输出对象的筛选证据链 JSON")
    trace.add_argument("subject_type", choices=("ETF", "DIRECTION", "STRATEGY"))
    trace.add_argument("subject_key")
    trace_report = commands.add_parser("trace-report", help="生成对象筛选证据链 Markdown")
    trace_report.add_argument("subject_type", choices=("ETF", "DIRECTION", "STRATEGY"))
    trace_report.add_argument("subject_key")
    trace_report.add_argument("path")
    rule_set = commands.add_parser("register-rules", help="登记一个版本化规则集 JSON")
    rule_set.add_argument("path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database = _database_path(args.database)
    catalog = CatalogService(database)
    market_data = MarketDataService(database)
    rules = RuleRegistry(database)
    if args.command == "init-db":
        database.initialize()
        print(f"已初始化: {database.path}")
    elif args.command == "identity-template":
        write_identity_template(args.path)
        print(f"已创建模板: {Path(args.path)}")
    elif args.command == "import-identities":
        print(f"已导入 {catalog.import_csv(args.path)} 条 ETF 身份记录")
    elif args.command == "list-identities":
        print(identities_to_csv(catalog.list_identities()), end="")
    elif args.command == "import-daily":
        print(f"已导入 {market_data.import_csv(args.path)} 条日线记录")
    elif args.command == "metrics":
        print(json.dumps(summarize(market_data.series(args.exchange, args.code, args.adjustment)), ensure_ascii=False, indent=2))
    elif args.command == "backtest-fixed-dca":
        result = fixed_dca(
            market_data.series(args.exchange, args.code, args.adjustment), amount=args.amount,
            frequency=args.frequency, cash_reserve=args.cash_reserve,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.command == "trace":
        print(json.dumps(catalog.trace(args.subject_type, args.subject_key), ensure_ascii=False, indent=2))
    elif args.command == "trace-report":
        write_trace_report(catalog, args.subject_type, args.subject_key, args.path)
        print(f"已生成证据报告: {Path(args.path)}")
    elif args.command == "register-rules":
        print(f"已登记规则版本: {rules.register_json(args.path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
