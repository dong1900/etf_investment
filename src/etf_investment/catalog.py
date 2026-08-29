"""ETF identity catalog and append-only evidence-chain services."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .storage import Database


IDENTITY_COLUMNS = (
    "exchange",
    "code",
    "name",
    "tracking_target",
    "asset_type",
    "passive_tracking",
    "listing_date",
    "source_name",
    "source_url",
    "source_as_of",
    "source_record_id",
)
REQUIRED_IDENTITY_COLUMNS = IDENTITY_COLUMNS[:6] + ("source_name", "source_as_of")


class CatalogValidationError(ValueError):
    """The imported identity data cannot be safely used as a research input."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


class CatalogService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def import_csv(self, path: str | Path) -> int:
        """Replace identities for the exchanges/codes present in a source export.

        The source itself, effective date and row ID remain attached to every
        identity. This makes later corrections traceable instead of silently
        changing the research universe.
        """
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            missing = [column for column in REQUIRED_IDENTITY_COLUMNS if column not in headers]
            if missing:
                raise CatalogValidationError(f"身份清单缺少必填列: {', '.join(missing)}")
            rows = [self._normalize_row(row, number) for number, row in enumerate(reader, start=2)]
        if not rows:
            raise CatalogValidationError("身份清单没有数据行")

        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row["exchange"], row["code"])
            if key in seen:
                raise CatalogValidationError(f"身份清单存在重复证券: {key[0]} {key[1]}")
            seen.add(key)

        self.database.initialize()
        with self.database.session() as connection:
            connection.executemany(
                """
                INSERT INTO etf_identity (
                    exchange, code, name, tracking_target, asset_type,
                    passive_tracking, listing_date, source_name, source_url,
                    source_as_of, source_record_id, imported_at
                ) VALUES (
                    :exchange, :code, :name, :tracking_target, :asset_type,
                    :passive_tracking, :listing_date, :source_name, :source_url,
                    :source_as_of, :source_record_id, :imported_at
                )
                ON CONFLICT(exchange, code) DO UPDATE SET
                    name=excluded.name,
                    tracking_target=excluded.tracking_target,
                    asset_type=excluded.asset_type,
                    passive_tracking=excluded.passive_tracking,
                    listing_date=excluded.listing_date,
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    source_as_of=excluded.source_as_of,
                    source_record_id=excluded.source_record_id,
                    imported_at=excluded.imported_at
                """,
                rows,
            )
        return len(rows)

    def list_identities(self) -> list[dict[str, Any]]:
        self.database.initialize()
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM etf_identity ORDER BY asset_type, tracking_target, exchange, code"
            ).fetchall()
        return [dict(row) for row in rows]

    def record_event(
        self,
        *,
        subject_type: str,
        subject_key: str,
        stage: str,
        status: str,
        summary: str,
        evidence: dict[str, Any],
        rule_version: str | None = None,
    ) -> str:
        """Append a decision event; never mutate an earlier screening outcome."""
        required_evidence = {"data_period", "metrics", "decision_basis", "impact"}
        missing = sorted(required_evidence - set(evidence))
        if missing:
            raise CatalogValidationError(f"筛选证据缺少字段: {', '.join(missing)}")
        if subject_type not in {"ETF", "DIRECTION", "STRATEGY"}:
            raise CatalogValidationError("subject_type 必须为 ETF、DIRECTION 或 STRATEGY")
        if not all((subject_key.strip(), stage.strip(), status.strip(), summary.strip())):
            raise CatalogValidationError("证据事件的对象、阶段、状态和摘要不能为空")
        if not isinstance(evidence["metrics"], list):
            raise CatalogValidationError("筛选证据 metrics 必须为数组")
        for metric in evidence["metrics"]:
            if not isinstance(metric, dict) or not {"name", "actual", "unit"} <= set(metric):
                raise CatalogValidationError("每个指标必须包含 name、actual 和 unit")
            if "threshold" in metric and not {"rule", "passed"} <= set(metric):
                raise CatalogValidationError("使用 threshold 的指标必须同时包含 rule 和 passed")

        event_id = str(uuid.uuid4())
        self.database.initialize()
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO decision_event (
                    event_id, subject_type, subject_key, stage, status,
                    rule_version, evidence_json, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    subject_type,
                    subject_key.strip(),
                    stage.strip(),
                    status.strip(),
                    _optional(rule_version),
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    summary.strip(),
                    _now(),
                ),
            )
        return event_id

    def trace(self, subject_type: str, subject_key: str) -> list[dict[str, Any]]:
        self.database.initialize()
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM decision_event
                WHERE subject_type = ? AND subject_key = ?
                ORDER BY created_at, event_id
                """,
                (subject_type, subject_key),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return result

    @staticmethod
    def _normalize_row(source: dict[str, str | None], number: int) -> dict[str, Any]:
        row = {column: _optional(source.get(column)) for column in IDENTITY_COLUMNS}
        exchange = row["exchange"]
        if exchange not in {"SSE", "SZSE"}:
            raise CatalogValidationError(f"第 {number} 行 exchange 必须为 SSE 或 SZSE")
        code = row["code"]
        if code is None or len(code) != 6 or not code.isdigit():
            raise CatalogValidationError(f"第 {number} 行 code 必须为 6 位数字")
        for column in ("name", "tracking_target", "asset_type", "source_name", "source_as_of"):
            if row[column] is None:
                raise CatalogValidationError(f"第 {number} 行 {column} 不能为空")
        passive = row["passive_tracking"]
        if passive not in {"0", "1", "false", "true", "False", "True"}:
            raise CatalogValidationError(f"第 {number} 行 passive_tracking 必须为 true/false 或 1/0")
        return {
            **row,
            "passive_tracking": int(passive.lower() in {"1", "true"}),
            "imported_at": _now(),
        }


def write_identity_template(path: str | Path) -> None:
    """Create a header-only source template; it contains no invented ETF data."""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(IDENTITY_COLUMNS)


def identities_to_csv(rows: Iterable[dict[str, Any]]) -> str:
    """Render a stable UTF-8 CSV for human inspection or later reports."""
    from io import StringIO

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=("exchange", "code", "name", "tracking_target", "asset_type", "passive_tracking", "listing_date", "source_name", "source_url", "source_as_of", "source_record_id"))
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return output.getvalue()
