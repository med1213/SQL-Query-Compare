from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_SAMPLE_SIZE = 5


@dataclass
class QueryRunResult:
    label: str
    sql_path: str
    duration_ms: float
    success: bool
    columns: list[str]
    row_count: int
    row_signature: Counter[tuple[Any, ...]]
    sample_rows: list[dict[str, Any]]
    error_type: str | None = None
    error_message: str | None = None
    traceback_text: str | None = None


@dataclass
class ConnectionConfig:
    dialect: str = "mysql"
    driver: str | None = "pymysql"
    host: str | None = None
    port: int | None = None
    database: str | None = None
    user: str | None = None
    password: str | None = None
    url: str | None = None


def load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv()


def getenv_int(name: str) -> int | None:
    value = os.getenv(name)
    if value in (None, ""):
        return None
    return int(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two SQL query scripts by result difference, speed, and execution errors.",
    )
    parser.add_argument("query_a", help="Path to the first SQL file.")
    parser.add_argument("query_b", help="Path to the second SQL file.")
    parser.add_argument(
        "--dialect",
        default=os.getenv("DB_DIALECT", "mysql"),
        help="SQLAlchemy dialect name, for example mysql for MariaDB or postgresql.",
    )
    parser.add_argument(
        "--driver",
        default=os.getenv("DB_DRIVER", "pymysql"),
        help="Optional SQLAlchemy driver, for example pymysql for MariaDB or psycopg for PostgreSQL.",
    )
    parser.add_argument("--host", default=os.getenv("DB_HOST"), help="Database host.")
    parser.add_argument("--port", type=int, default=getenv_int("DB_PORT"), help="Database port.")
    parser.add_argument("--database", default=os.getenv("DB_DATABASE"), help="Database name.")
    parser.add_argument("--user", default=os.getenv("DB_USER"), help="Database username.")
    parser.add_argument("--password", default=os.getenv("DB_PASSWORD"), help="Database password.")
    parser.add_argument(
        "--url",
        default=None,
        help="Full SQLAlchemy connection URL. Overrides host, port, database, user, and password.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help="How many differing rows to show in each direction.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Include Python traceback output for execution errors.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args()


def connection_config_from_args(args: argparse.Namespace) -> ConnectionConfig:
    return ConnectionConfig(
        dialect=args.dialect,
        driver=args.driver,
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=args.password,
        url=args.url,
    )


def build_connection_string(config: ConnectionConfig) -> str:
    from sqlalchemy.engine import URL

    if config.url:
        return config.url

    missing = [
        name
        for name, value in (
            ("host", config.host),
            ("port", config.port),
            ("database", config.database),
            ("user", config.user),
            ("password", config.password),
        )
        if value in (None, "")
    ]
    if missing:
        missing_display = ", ".join(missing)
        raise ValueError(
            "Missing connection settings: "
            f"{missing_display}. Provide all fields or use --url instead."
        )

    drivername = config.dialect if not config.driver else f"{config.dialect}+{config.driver}"
    return URL.create(
        drivername=drivername,
        username=config.user,
        password=config.password,
        host=config.host,
        port=config.port,
        database=config.database,
    ).render_as_string(hide_password=False)


def load_sql(path_text: str) -> tuple[Path, str]:
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"SQL file not found: {path}")
    return path, path.read_text(encoding="utf-8")


def normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    return value


def execute_query(
    engine_url: str,
    label: str,
    sql_path: Path,
    sql_text: str,
    debug: bool,
    sample_size: int,
) -> QueryRunResult:
    from sqlalchemy import create_engine, text

    start = time.perf_counter()
    try:
        engine = create_engine(engine_url)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                result = connection.execute(text(sql_text))
                rows = result.fetchall() if result.returns_rows else []
                transaction.rollback()
            except Exception:
                transaction.rollback()
                raise

        duration_ms = (time.perf_counter() - start) * 1000
        columns = list(result.keys()) if result.returns_rows else []
        normalized_rows = [tuple(normalize_value(value) for value in row) for row in rows]
        sample_rows = [dict(zip(columns, row)) for row in normalized_rows[:sample_size]]
        return QueryRunResult(
            label=label,
            sql_path=str(sql_path),
            duration_ms=duration_ms,
            success=True,
            columns=columns,
            row_count=len(normalized_rows),
            row_signature=Counter(normalized_rows),
            sample_rows=sample_rows,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        return QueryRunResult(
            label=label,
            sql_path=str(sql_path),
            duration_ms=duration_ms,
            success=False,
            columns=[],
            row_count=0,
            row_signature=Counter(),
            sample_rows=[],
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_text=traceback.format_exc() if debug else None,
        )


def test_connection(config: ConnectionConfig) -> None:
    from sqlalchemy import create_engine, text

    engine_url = build_connection_string(config)
    engine = create_engine(engine_url)
    with engine.connect() as connection:
        # Executes a lightweight round-trip query to validate credentials and connectivity.
        connection.execute(text("SELECT 1"))


def sample_differences(
    left: Counter[tuple[Any, ...]],
    right: Counter[tuple[Any, ...]],
    sample_size: int,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row, count in (left - right).items():
        for _ in range(count):
            rows.append(list(row))
            if len(rows) >= sample_size:
                return rows
    return rows


def compare_results(
    result_a: QueryRunResult,
    result_b: QueryRunResult,
    sample_size: int,
) -> dict[str, Any]:
    same_columns = result_a.columns == result_b.columns
    same_rows = result_a.row_signature == result_b.row_signature
    rows_only_in_a = sample_differences(result_a.row_signature, result_b.row_signature, sample_size)
    rows_only_in_b = sample_differences(result_b.row_signature, result_a.row_signature, sample_size)

    winner: str | None
    reason: str
    if result_a.success and not result_b.success:
        winner = result_a.label
        reason = "Only the first query executed successfully."
    elif result_b.success and not result_a.success:
        winner = result_b.label
        reason = "Only the second query executed successfully."
    elif not result_a.success and not result_b.success:
        winner = None
        reason = "Neither query executed successfully."
    elif same_columns and same_rows:
        winner = result_a.label if result_a.duration_ms <= result_b.duration_ms else result_b.label
        reason = "Both queries returned equivalent results, so the faster query is better."
    else:
        winner = None
        reason = "Both queries ran, but they returned different results. Review the differences before deciding which is better."

    return {
        "same_columns": same_columns,
        "same_rows": same_rows,
        "rows_only_in_a": rows_only_in_a,
        "rows_only_in_b": rows_only_in_b,
        "winner": winner,
        "reason": reason,
    }


def printable_result(result: QueryRunResult) -> dict[str, Any]:
    payload = asdict(result)
    payload.pop("row_signature")
    return payload


def result_from_payload(payload: dict[str, Any]) -> QueryRunResult:
    return QueryRunResult(
        label=payload["label"],
        sql_path=payload["sql_path"],
        duration_ms=payload["duration_ms"],
        success=payload["success"],
        columns=payload["columns"],
        row_count=payload["row_count"],
        row_signature=Counter(),
        sample_rows=payload["sample_rows"],
        error_type=payload.get("error_type"),
        error_message=payload.get("error_message"),
        traceback_text=payload.get("traceback_text"),
    )


def run_comparison(
    config: ConnectionConfig,
    query_a_sql: str,
    query_b_sql: str,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    debug: bool = False,
    query_a_name: str = "Query A",
    query_b_name: str = "Query B",
) -> dict[str, Any]:
    engine_url = build_connection_string(config)
    result_a = execute_query(
        engine_url,
        query_a_name,
        Path(query_a_name),
        query_a_sql,
        debug,
        sample_size,
    )
    result_b = execute_query(
        engine_url,
        query_b_name,
        Path(query_b_name),
        query_b_sql,
        debug,
        sample_size,
    )
    comparison = compare_results(result_a, result_b, sample_size)
    return {
        "query_a": printable_result(result_a),
        "query_b": printable_result(result_b),
        "comparison": comparison,
    }


def render_text_report(
    result_a: QueryRunResult,
    result_b: QueryRunResult,
    comparison: dict[str, Any],
) -> str:
    lines = [
        "SQL Query Comparison Report",
        "=" * 27,
        "",
    ]

    for result in (result_a, result_b):
        lines.extend(
            [
                f"{result.label}: {result.sql_path}",
                f"  Success: {result.success}",
                f"  Duration: {result.duration_ms:.2f} ms",
                f"  Columns: {', '.join(result.columns) if result.columns else '(none)'}",
                f"  Row count: {result.row_count}",
            ]
        )
        if result.error_message:
            lines.append(f"  Error: {result.error_type}: {result.error_message}")
        if result.traceback_text:
            lines.append("  Traceback:")
            lines.extend(f"    {line}" for line in result.traceback_text.rstrip().splitlines())
        lines.append("")

    lines.extend(
        [
            "Comparison",
            "-" * 10,
            f"Same columns: {comparison['same_columns']}",
            f"Same rows: {comparison['same_rows']}",
            f"Winner: {comparison['winner'] or 'No automatic winner'}",
            f"Reason: {comparison['reason']}",
        ]
    )

    if comparison["rows_only_in_a"]:
        lines.append("Rows only in Query A:")
        lines.extend(f"  {row}" for row in comparison["rows_only_in_a"])
    if comparison["rows_only_in_b"]:
        lines.append("Rows only in Query B:")
        lines.extend(f"  {row}" for row in comparison["rows_only_in_b"])

    return "\n".join(lines)


def main() -> int:
    load_environment()
    args = parse_args()

    try:
        query_a_path, query_a_sql = load_sql(args.query_a)
        query_b_path, query_b_sql = load_sql(args.query_b)
        payload = run_comparison(
            connection_config_from_args(args),
            query_a_sql,
            query_b_sql,
            sample_size=args.sample_size,
            debug=args.debug,
            query_a_name=str(query_a_path),
            query_b_name=str(query_b_path),
        )
    except Exception as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        if args.debug:
            print(traceback.format_exc(), file=sys.stderr)
        return 2

    result_a = payload["query_a"]
    result_b = payload["query_b"]
    comparison = payload["comparison"]

    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(render_text_report(result_from_payload(result_a), result_from_payload(result_b), comparison))

    if result_a["success"] and result_b["success"]:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())