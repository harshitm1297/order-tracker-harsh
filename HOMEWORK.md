# Homework 4: DevOps and Observability

## What the homework is teaching

The assignment begins with a failure that cannot be diagnosed reliably from a web page alone. The first goal is to make one important user journey—looking up an order—observable through metrics, logs, and traces. A metric gives the aggregate symptom, a log supplies a structured event, and a trace connects the request to the failing operation. The implementation deliberately avoids recording order IDs, customer data, request bodies, or credentials as telemetry attributes.

The second goal is to turn raw signals into an operational system. The OpenTelemetry Collector receives OTLP from the app and routes it to specialized stores: Prometheus for numeric time series, Loki for logs, and Tempo for traces. Grafana reads all three, provides a dashboard, and evaluates an alert based on customer-visible HTTP 5xx responses rather than an indirect machine statistic such as CPU use.

The final goal is controlled agentic incident response. Grafana posts an alert to a small responder, which collects a narrow evidence packet and launches Codex headlessly. The responder does not grant blanket autonomy: ordinary and test alerts are read-only, while a write sandbox is allowed only for a firing `OrderTrackerOrderLookup5xx` alert explicitly labelled `allow_fix=true`. The task also forbids the agent from committing, pushing, deploying, restarting containers, accessing credentials, or leaving the repository. The agent must either make the smallest tested correction or escalate.

## Question-by-question results

### Question 1 — Run the app

`GET /healthz` checks that the SQLite database is reachable. Its response is:

```json
{"status":"ok"}
```

Correct option: **`{"status":"ok"}`**.

### Question 2 — Instrument one endpoint

`GET /api/orders/{order_id}` now creates an `orders.lookup` span, increments `order_tracker.order_lookups`, and emits a structured lookup log. The bounded attributes include the normalized route, HTTP status, order priority, and lookup outcome. Console export remains the default, while Compose switches the same instrumentation to OTLP.

`standard-1001` exists, so its lookup succeeds and the metric records **HTTP 200**.

Correct option: **200**.

### Question 3 — Build the telemetry pipeline

Compose now runs the app, OpenTelemetry Collector, Prometheus, Loki, Tempo, and Grafana. The provisioned dashboard includes request counts by status, a 5xx panel, logs, and trace search. Grafana datasource links also carry trace IDs between Loki and Tempo.

The homework asks for `standard-1002`, but the starter seeds `standard-1001`, `standard-1003`, and `express-1002`. Therefore `standard-1002` is absent and the instrumented lookup records **HTTP 404**. This is intentional: a 404 is observable user impact, but it is not a server failure.

Correct option: **404**.

### Question 4 — Configure the alert

The provisioned alert evaluates the increase in lookup 5xx responses over one minute. It includes the endpoint, one-minute window, dashboard link, and treats no data as OK. Repeating the missing `standard-1002` lookup generates 404 responses, not 5xx responses, so the alert stays **Normal**.

Correct option: **Normal**.

### Question 5 — Build the automatic responder

The exact test payload from the homework was sent to `POST /alerts`. The responder recognized that it was a test, selected a read-only sandbox, collected the evidence packet, and made no source changes. The retained incident is `INC-20260927T115335472557Z`.

The requested last line from the agent is:

> INC-20260927T115335472557Z was a test notification, so no fix was required.

### Question 6 — Watch the agent fix the incident

Before the correction, `GET /api/orders/express-1002` returned HTTP 500. The seed places that express order on the last day of the previous month. The code attempted `placed_at.replace(day=placed_at.day + 2)`, which constructs a nonexistent day instead of advancing time across the month boundary. The authorized responder reproduced the failure, replaced it with `placed_at + timedelta(days=2)`, and added a regression test.

After restarting the app, the same lookup returned HTTP 200 and an estimated delivery date two days later. The complete suite returned `4 passed`.

Correct option: **The express delivery date calculation tried to use a day that does not exist in that month.**

## Evidence and implementation map

- `app/telemetry.py`: OpenTelemetry resource, trace, metric, and log setup.
- `app/main.py`: lookup instrumentation and the agent-authored date correction.
- `observability/`: Collector, Prometheus, Loki, Tempo, Grafana dashboard, datasources, and alert rule.
- `incident-response/`: webhook service, evidence collector, output schema, autonomy policy, and agent task.
- `incident-response/incidents/INC-20260927T115335472557Z/`: exact homework test-alert evidence and response.
- `incident-response/incidents/INC-20260927T114938626845Z/`: real incident evidence and structured response.
- `tests/test_api.py`: API suite and month-boundary regression test.

Raw Codex JSONL and stderr are retained locally for debugging but excluded from Git because they can contain machine-specific details. The structured alert, metrics, logs, traces, recent-change summary, response, and status are the submission evidence.
