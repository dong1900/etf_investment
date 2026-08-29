"""Versioned rule-set registry; it intentionally ships without investment thresholds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import CatalogValidationError, _now
from .storage import Database


class RuleRegistry:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register_json(self, path: str | Path) -> str:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload: dict[str, Any] = json.load(handle)
        for field in ("version", "name", "description", "rules"):
            if field not in payload:
                raise CatalogValidationError(f"规则集缺少字段: {field}")
        if not isinstance(payload["rules"], list):
            raise CatalogValidationError("rules 必须为数组")
        for index, rule in enumerate(payload["rules"], start=1):
            self._validate_rule(rule, index)
        self.database.initialize()
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO rule_set(version, name, description, rules_json, registered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(version) DO UPDATE SET
                    name=excluded.name, description=excluded.description,
                    rules_json=excluded.rules_json, registered_at=excluded.registered_at
                """,
                (payload["version"], payload["name"], payload["description"], json.dumps(payload["rules"], ensure_ascii=False, sort_keys=True), _now()),
            )
        return str(payload["version"])

    @staticmethod
    def _validate_rule(rule: object, index: int) -> None:
        if not isinstance(rule, dict):
            raise CatalogValidationError(f"第 {index} 条规则必须为对象")
        for field in ("id", "name", "unit", "calculation", "decision_rule"):
            if not isinstance(rule.get(field), str) or not rule[field].strip():
                raise CatalogValidationError(f"第 {index} 条规则缺少非空字段: {field}")
        if "threshold" not in rule:
            raise CatalogValidationError(f"第 {index} 条规则缺少 threshold；无硬阈值请写 null")

