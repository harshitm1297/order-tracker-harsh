# Order Tracker — Homework 4 solution

This repository contains the completed AI Dev Tools Zoomcamp observability homework. Order Tracker is instrumented with OpenTelemetry; a Collector routes metrics, logs, and traces to Prometheus, Loki, and Tempo; Grafana provisions a dashboard and a 5xx alert; and a policy-limited responder launches Codex headlessly when Grafana sends a webhook.

The implementation and the evidence-backed answers are documented in [HOMEWORK.md](HOMEWORK.md).

## Architecture

The application sends all three telemetry signals over OTLP to the OpenTelemetry Collector. The Collector exposes metrics for Prometheus and forwards logs and traces to Loki and Tempo. Grafana reads those stores, displays a provisioned dashboard, and evaluates a 5xx alert. Its webhook calls the responder running on the host at port 8001. The responder saves a bounded, redacted evidence packet before invoking Codex in read-only mode; only the exact authorized production-style alert can receive workspace-write access.

## Run the stack

You need Docker with Compose. To run the tests and incident responder, you also need Python 3.11+, `uv`, and an authenticated `codex` CLI.

```bash
docker compose up --build -d --wait
```

Open <http://127.0.0.1:8000> for the app and <http://127.0.0.1:3000> for Grafana (`admin` / `admin`). Prometheus, Loki, and Tempo are exposed locally on ports 9090, 3100, and 3200. Order and observability data use Docker volumes.

If port 8000 is occupied, set `ORDER_TRACKER_PORT`, for example:

```bash
ORDER_TRACKER_PORT=18080 docker compose up --build -d --wait
```

In a second terminal, start the responder:

```powershell
$env:UV_CACHE_DIR = "$PWD/.uv-cache"
uv run --frozen uvicorn responder:app --app-dir incident-response --host 0.0.0.0 --port 8001
```

Run tests with `uv run --frozen pytest -q`. Stop the stack with `docker compose down`. Add `-v` only if you intentionally want to delete all persistent data.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Web page |
| GET | `/healthz` | Database health check |
| GET | `/api/orders` | List orders |
| POST | `/api/orders` | Create an order |
| GET | `/api/orders/{id}` | Check an order |
| PATCH | `/api/orders/{id}` | Change an order status |

The app uses SQLite to keep setup small. Run one app container at a time. The course exercise is about detecting and handling an incident, not scaling the database.
