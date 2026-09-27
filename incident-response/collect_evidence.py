"""Collect a small, repeatable, read-only incident evidence packet."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://127.0.0.1:3100")
TEMPO_URL = os.getenv("TEMPO_URL", "http://127.0.0.1:3200")
REDACTED_KEYS = ("authorization", "password", "secret", "token", "cookie")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(word in key.lower() for word in REDACTED_KEYS) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_redact(value), indent=2, sort_keys=True), encoding="utf-8")


def _get_json(base_url: str, path: str, params: dict[str, str]) -> Any:
    url = f"{base_url}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)
    except Exception as exc:  # Evidence gaps are recorded rather than hiding the alert.
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def collect(alert: dict[str, Any], incident_dir: Path) -> None:
    """Run only the queries declared in this function and save their results."""

    incident_dir.mkdir(parents=True, exist_ok=True)
    _write_json(incident_dir / "alert.json", alert)

    metric_query = (
        'sum by (http_response_status_code) '
        '(increase(order_tracker_order_lookups_total[5m]))'
    )
    metrics = _get_json(PROMETHEUS_URL, "/api/v1/query", {"query": metric_query})
    _write_json(incident_dir / "metrics.json", {"query": metric_query, "result": metrics})

    end_ns = time.time_ns()
    start_ns = end_ns - (15 * 60 * 1_000_000_000)
    log_query = '{service_name="order-tracker"} |= "order_lookup"'
    logs = _get_json(
        LOKI_URL,
        "/loki/api/v1/query_range",
        {"query": log_query, "start": str(start_ns), "end": str(end_ns), "limit": "200"},
    )
    _write_json(incident_dir / "logs.json", {"query": log_query, "result": logs})

    trace_query = '{ resource.service.name = "order-tracker" && status = error }'
    traces = _get_json(TEMPO_URL, "/api/search", {"q": trace_query, "limit": "20"})
    _write_json(incident_dir / "traces.json", {"query": trace_query, "result": traces})

    command = [
        "git",
        "-c",
        f"safe.directory={REPO_ROOT.as_posix()}",
        "log",
        "-5",
        "--oneline",
        "--decorate",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    (incident_dir / "recent-changes.txt").write_text(
        completed.stdout or completed.stderr,
        encoding="utf-8",
    )
