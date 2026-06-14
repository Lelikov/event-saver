import os
os.environ["OTEL_SDK_DISABLED"] = "false"

from opentelemetry import context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def test_inbound_traceparent_is_continued():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = provider.get_tracer("test")

    # Simulate an inbound message carrying a W3C traceparent header.
    carrier = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    ctx = TraceContextTextMapPropagator().extract(carrier=carrier)
    token = context.attach(ctx)
    try:
        with tracer.start_as_current_span("consume"):
            pass
    finally:
        context.detach(token)

    spans = exporter.get_finished_spans()
    assert spans[0].context.trace_id == 0x0AF7651916CD43DD8448EB211C80319C
