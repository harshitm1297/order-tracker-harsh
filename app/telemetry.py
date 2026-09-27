"""OpenTelemetry setup for Order Tracker.

Console export is the safe default for Question 2.  Docker Compose switches the
same instrumentation to OTLP so the Collector can route each signal to its
backend.  No request bodies, order identifiers, or credentials are attached to
telemetry.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


SERVICE_NAME = "order-tracker"
ROUTE = "/api/orders/{order_id}"


@dataclass(frozen=True)
class Telemetry:
    tracer: trace.Tracer
    lookup_counter: metrics.Counter
    logger: logging.Logger


def _resource() -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": os.getenv("APP_VERSION", "dev"),
            "deployment.environment.name": os.getenv("APP_ENV", "development"),
        }
    )


def configure_telemetry(app) -> Telemetry:
    """Configure traces, metrics, and structured logs once at application start."""

    resource = _resource()
    mode = os.getenv("OTEL_EXPORTER_MODE", "console").lower()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

    tracer_provider = TracerProvider(resource=resource)
    logger_provider = LoggerProvider(resource=resource)

    metric_readers = []
    if mode == "otlp":
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )
        metric_exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
        metric_readers.append(
            PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "5000")),
            )
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
        )
    elif mode == "console":
        tracer_provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter(out=sys.__stdout__))
        )
        metric_exporter = ConsoleMetricExporter(out=sys.__stdout__)
        metric_readers.append(
            PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "5000")),
            )
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(ConsoleLogRecordExporter(out=sys.__stdout__))
        )

    elif mode != "none":
        raise ValueError("OTEL_EXPORTER_MODE must be console, otlp, or none")

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")

    logger = logging.getLogger(SERVICE_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    if mode != "none":
        logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))

    meter = metrics.get_meter(SERVICE_NAME)
    lookup_counter = meter.create_counter(
        "order_tracker.order_lookups",
        description="Number of order lookup requests by route, HTTP status, and outcome",
        unit="{request}",
    )
    return Telemetry(
        tracer=trace.get_tracer(SERVICE_NAME),
        lookup_counter=lookup_counter,
        logger=logger,
    )


def lookup_attributes(status_code: int, outcome: str, priority: str = "unknown") -> dict[str, object]:
    """Return bounded, non-sensitive dimensions shared by all lookup signals."""

    return {
        "http.route": ROUTE,
        "http.response.status_code": status_code,
        "order.priority": priority,
        "order.lookup.outcome": outcome,
    }
