from __future__ import annotations

import os
from typing import Any

from flask import Flask, render_template, request

from compare_queries import (
    ConnectionConfig,
    DEFAULT_SAMPLE_SIZE,
    load_environment,
    run_comparison,
    test_connection,
)


app = Flask(__name__)


def default_form_data() -> dict[str, Any]:
    return {
        "dialect": os.getenv("DB_DIALECT", "mysql"),
        "driver": os.getenv("DB_DRIVER", "pymysql"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "3306"),
        "database": os.getenv("DB_DATABASE", ""),
        "user": os.getenv("DB_USER", ""),
        "password": os.getenv("DB_PASSWORD", ""),
        "sample_size": str(DEFAULT_SAMPLE_SIZE),
        "debug": False,
        "query_a": "",
        "query_b": "",
        "connection_verified": False,
        "connection_signature": "",
    }


def parse_port(raw_value: str) -> int | None:
    value = raw_value.strip()
    if not value:
        return None
    return int(value)


def parse_bool(raw_value: str | None) -> bool:
    return raw_value in {"1", "true", "True", "on"}


def build_connection_signature(form_data: dict[str, Any]) -> str:
    fields = [
        form_data["dialect"],
        form_data["driver"],
        form_data["host"],
        form_data["port"],
        form_data["database"],
        form_data["user"],
    ]
    return "|".join(fields)


def build_form_data(form: Any) -> dict[str, Any]:
    return {
        "dialect": form.get("dialect", "mysql").strip(),
        "driver": form.get("driver", "").strip(),
        "host": form.get("host", "").strip(),
        "port": form.get("port", "").strip(),
        "database": form.get("database", "").strip(),
        "user": form.get("user", "").strip(),
        "password": form.get("password", ""),
        "sample_size": form.get("sample_size", str(DEFAULT_SAMPLE_SIZE)).strip(),
        "debug": form.get("debug") == "on",
        "query_a": form.get("query_a", "").strip(),
        "query_b": form.get("query_b", "").strip(),
        "connection_verified": parse_bool(form.get("connection_verified")),
        "connection_signature": form.get("connection_signature", "").strip(),
    }


def difference_headers(columns: list[str], rows: list[list[Any]]) -> list[str]:
    if columns:
        return columns
    if not rows:
        return []
    return [f"Column {index + 1}" for index in range(len(rows[0]))]


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    form_data = default_form_data()
    payload: dict[str, Any] | None = None
    setup_error: str | None = None
    connection_ok_message: str | None = None

    if request.method == "POST":
        form_data = build_form_data(request.form)
        form_action = request.form.get("form_action", "compare")
        current_signature = build_connection_signature(form_data)
        if form_action == "close_connection":
            form_data["connection_verified"] = False
            form_data["connection_signature"] = ""
            connection_ok_message = "Connection closed. Test connection again before comparing scripts."
        elif form_action == "clear_scripts":
            form_data["query_a"] = ""
            form_data["query_b"] = ""
            connection_ok_message = "Scripts cleared. You can paste new SQL and compare again."
        else:
            try:
                config = ConnectionConfig(
                    dialect=form_data["dialect"] or "mysql",
                    driver=form_data["driver"] or None,
                    host=form_data["host"] or None,
                    port=parse_port(form_data["port"]),
                    database=form_data["database"] or None,
                    user=form_data["user"] or None,
                    password=form_data["password"] or None,
                )

                if form_action == "test_connection":
                    test_connection(config)
                    connection_ok_message = "Connection successful. You can now paste scripts and click Compare."
                    form_data["connection_verified"] = True
                    form_data["connection_signature"] = current_signature
                else:
                    signature_matches = form_data["connection_signature"] == current_signature
                    if not form_data["connection_verified"] or not signature_matches:
                        setup_error = "Test connection first, then enter scripts and compare."
                        form_data["connection_verified"] = False
                        form_data["connection_signature"] = ""
                    elif not form_data["query_a"] or not form_data["query_b"]:
                        setup_error = "Paste both SQL scripts before running the comparison."
                    else:
                        payload = run_comparison(
                            config,
                            form_data["query_a"],
                            form_data["query_b"],
                            sample_size=max(1, int(form_data["sample_size"])),
                            debug=form_data["debug"],
                            query_a_name="Query A",
                            query_b_name="Query B",
                        )
            except Exception as exc:
                setup_error = str(exc)
                form_data["connection_verified"] = False
                form_data["connection_signature"] = ""

    connection_verified = bool(form_data["connection_verified"])

    comparison = payload["comparison"] if payload else None
    result_a = payload["query_a"] if payload else None
    result_b = payload["query_b"] if payload else None
    has_successful_results = bool(result_a and result_b and result_a["success"] and result_b["success"])

    return render_template(
        "index.html",
        form_data=form_data,
        connection_verified=connection_verified,
        setup_error=setup_error,
        connection_ok_message=connection_ok_message,
        comparison=comparison,
        result_a=result_a,
        result_b=result_b,
        has_successful_results=has_successful_results,
        diff_headers_a=difference_headers(result_a["columns"], comparison["rows_only_in_a"]) if comparison and result_a else [],
        diff_headers_b=difference_headers(result_b["columns"], comparison["rows_only_in_b"]) if comparison and result_b else [],
    )


if __name__ == "__main__":
    load_environment()
    app.run(debug=True)