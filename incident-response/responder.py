"""Grafana webhook receiver and bounded headless Codex responder."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException

from collect_evidence import REPO_ROOT, collect


HERE = Path(__file__).resolve().parent
INCIDENTS_DIR = HERE / "incidents"
SCHEMA = HERE / "response.schema.json"
TASK = HERE / "responder-task.md"
RUN_LOCK = Lock()

app = FastAPI(title="Order Tracker Incident Responder")


def _incident_id() -> str:
    return datetime.now(timezone.utc).strftime("INC-%Y%m%dT%H%M%S%fZ")


def _primary_alert(payload: dict[str, Any]) -> dict[str, Any]:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts or not isinstance(alerts[0], dict):
        raise HTTPException(422, "Payload must contain at least one alert")
    return alerts[0]


def _may_fix(alert: dict[str, Any]) -> bool:
    labels = alert.get("labels") or {}
    return (
        alert.get("status") == "firing"
        and labels.get("alertname") == "OrderTrackerOrderLookup5xx"
        and str(labels.get("allow_fix", "")).lower() == "true"
    )


def _save_status(incident_dir: Path, state: str, **extra: Any) -> None:
    value = {"incident_id": incident_dir.name, "state": state, **extra}
    (incident_dir / "status.json").write_text(json.dumps(value, indent=2), encoding="utf-8")


def _run_agent(payload: dict[str, Any], incident_dir: Path, allow_fix: bool) -> None:
    with RUN_LOCK:
        try:
            _save_status(incident_dir, "collecting_evidence")
            collect(payload, incident_dir)
        except Exception as exc:
            _save_status(incident_dir, "failed", error=f"Evidence collection failed: {exc}")
            return

        codex = os.getenv("CODEX_COMMAND") or shutil.which("codex")
        if not codex:
            _save_status(incident_dir, "failed", error="codex executable was not found")
            return

        mode = "workspace-write" if allow_fix else "read-only"
        prompt = TASK.read_text(encoding="utf-8").format(
            incident_id=incident_dir.name,
            incident_dir=incident_dir,
            access_mode=(
                "You may make the smallest source and regression-test correction and run tests."
                if allow_fix
                else "You have read-only access. Do not modify files."
            ),
        )
        response_path = incident_dir / "response.json"
        command = [
            codex,
            "exec",
            "--ephemeral",
            "--output-schema",
            str(SCHEMA),
            "--output-last-message",
            str(response_path),
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-C",
            str(REPO_ROOT),
        ]
        if allow_fix:
            command.append("--approve-for-me")
        else:
            command.extend(["--sandbox", mode])
        command.append(prompt)

        _save_status(incident_dir, "agent_running", sandbox=mode)
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("RESPONDER_TIMEOUT_SECONDS", "900")),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _save_status(incident_dir, "failed", error=f"Agent timed out: {exc}")
            return

        (incident_dir / "agent-events.jsonl").write_text(completed.stdout, encoding="utf-8")
        (incident_dir / "agent-stderr.txt").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            _save_status(
                incident_dir,
                "failed",
                error=f"Agent exited with code {completed.returncode}",
            )
            return

        response = json.loads(response_path.read_text(encoding="utf-8"))
        _save_status(
            incident_dir,
            "completed",
            sandbox=mode,
            final_line=response["final_line"],
        )


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/alerts", status_code=202)
def receive_alert(payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, str]:
    alert = _primary_alert(payload)
    incident_dir = INCIDENTS_DIR / _incident_id()
    incident_dir.mkdir(parents=True)
    _save_status(incident_dir, "accepted")
    background_tasks.add_task(_run_agent, payload, incident_dir, _may_fix(alert))
    return {"incident_id": incident_dir.name, "status": "accepted"}


@app.get("/incidents/{incident_id}")
def incident_status(incident_id: str) -> dict[str, Any]:
    if not incident_id.startswith("INC-") or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for char in incident_id):
        raise HTTPException(400, "Invalid incident ID")
    status_path = INCIDENTS_DIR / incident_id / "status.json"
    if not status_path.is_file():
        raise HTTPException(404, "Incident not found")
    return json.loads(status_path.read_text(encoding="utf-8"))
