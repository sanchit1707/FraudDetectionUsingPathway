"""
tracing.py
----------

OpenTelemetry tracing setup for FlashGuard Agent 6.

Usage
-----
    from tracing import get_tracer, init_tracing

    # Call once at application startup (done automatically in api.py lifespan)
    init_tracing()

    # Use in any module
    tracer = get_tracer()
    with tracer.start_as_current_span("my.operation") as span:
        span.set_attribute("txn.id", request.transaction_id)
        ...

Environment Variables
---------------------
    OTLP_ENDPOINT    gRPC endpoint of OTLP collector   (default: http://localhost:4317)
    OTEL_SERVICE_NAME  Service name in traces           (default: flashguard-agent6)
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)

_tracer_provider: TracerProvider | None = None
_NOOP_TRACER = trace.get_tracer(__name__)


def init_tracing() -> None:
    """
    Initialise the global TracerProvider.

    If OTLP_ENDPOINT is set and reachable the exporter sends spans to the
    OTLP collector (Jaeger, Tempo, …).  Otherwise a ConsoleSpanExporter is
    used so traces are still visible during local development without infra.

    Safe to call multiple times – only the first call has any effect.
    """
    global _tracer_provider

    if _tracer_provider is not None:
        return  # Already initialised

    service_name = os.getenv("OTEL_SERVICE_NAME", "flashguard-agent6")
    otlp_endpoint = os.getenv("OTLP_ENDPOINT", "")

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry: OTLP exporter → %s", otlp_endpoint)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "OpenTelemetry: OTLP exporter failed to init (%s). "
                "Falling back to ConsoleSpanExporter.",
                exc,
            )
            provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )
    else:
        # No OTLP endpoint configured – use console so developer can see spans
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("OpenTelemetry: no OTLP_ENDPOINT set, using ConsoleSpanExporter")

    trace.set_tracer_provider(provider)
    _tracer_provider = provider


def get_tracer(name: str = "flashguard.agent6") -> trace.Tracer:
    """
    Return a tracer.  Works whether or not init_tracing() has been called
    (falls back to the global no-op tracer if the SDK is not initialised).
    """
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider.  Call at application exit."""
    global _tracer_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None
