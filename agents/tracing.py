"""
Distributed request tracing with OpenTelemetry-compatible primitives.

Provides trace IDs, span hierarchy, latency tracking, error propagation,
and cross-service correlation without requiring an external collector.
Works standalone for local agent runtime; can export to any OTLP backend.
"""

import time
import uuid
import json
import threading
import contextlib
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

class SpanStatus(Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class SpanKind(Enum):
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


@dataclass
class SpanEvent:
    name: str
    timestamp_ns: int
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpanLink:
    trace_id: str
    span_id: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    kind: SpanKind = SpanKind.INTERNAL
    status: SpanStatus = SpanStatus.UNSET
    status_message: str = ""
    start_time_ns: int = 0
    end_time_ns: int = 0
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    links: List[SpanLink] = field(default_factory=list)
    resource: Dict[str, str] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.end_time_ns and self.start_time_ns:
            return (self.end_time_ns - self.start_time_ns) / 1_000_000
        return 0.0

    @property
    def is_error(self) -> bool:
        return self.status == SpanStatus.ERROR

    def set_attribute(self, key: str, value: Any) -> "Span":
        self.attributes[key] = value
        return self

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> "Span":
        self.events.append(SpanEvent(
            name=name,
            timestamp_ns=time.time_ns(),
            attributes=attributes or {},
        ))
        return self

    def record_exception(self, exc: Exception) -> "Span":
        self.status = SpanStatus.ERROR
        self.status_message = str(exc)
        self.add_event("exception", {
            "exception.type": type(exc).__name__,
            "exception.message": str(exc),
        })
        return self

    def end(self, status: Optional[SpanStatus] = None) -> "Span":
        self.end_time_ns = time.time_ns()
        if status is not None:
            self.status = status
        elif self.status == SpanStatus.UNSET:
            self.status = SpanStatus.OK
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        d["duration_ms"] = self.duration_ms
        d["events"] = [asdict(e) for e in self.events]
        d["links"] = [asdict(ln) for ln in self.links]
        return d


# ---------------------------------------------------------------------------
# Trace context propagation (W3C Trace Context compatible)
# ---------------------------------------------------------------------------

@dataclass
class TraceContext:
    trace_id: str
    span_id: str
    trace_flags: int = 1  # sampled

    def to_traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags:02x}"

    @classmethod
    def from_traceparent(cls, header: str) -> "TraceContext":
        parts = header.split("-")
        if len(parts) != 4 or parts[0] != "00":
            raise ValueError(f"Invalid traceparent: {header}")
        return cls(
            trace_id=parts[1],
            span_id=parts[2],
            trace_flags=int(parts[3], 16),
        )

    @classmethod
    def extract(cls, headers: Dict[str, str]) -> Optional["TraceContext"]:
        tp = headers.get("traceparent")
        if tp:
            return cls.from_traceparent(tp)
        return None

    def inject(self, headers: Dict[str, str]) -> Dict[str, str]:
        headers["traceparent"] = self.to_traceparent()
        return headers


# ---------------------------------------------------------------------------
# Span processor / exporter interface
# ---------------------------------------------------------------------------

class SpanExporter:
    def export(self, spans: List[Span]) -> bool:
        raise NotImplementedError

    def shutdown(self) -> None:
        pass


class InMemoryExporter(SpanExporter):
    def __init__(self) -> None:
        self._spans: List[Span] = []
        self._lock = threading.Lock()

    def export(self, spans: List[Span]) -> bool:
        with self._lock:
            self._spans.extend(spans)
        return True

    def get_spans(self) -> List[Span]:
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def shutdown(self) -> None:
        pass


class ConsoleExporter(SpanExporter):
    def export(self, spans: List[Span]) -> bool:
        for span in spans:
            print(json.dumps(span.to_dict(), indent=2, default=str))
        return True


class BatchSpanProcessor:
    def __init__(self, exporter: SpanExporter, max_batch: int = 64, flush_interval_s: float = 5.0) -> None:
        self._exporter = exporter
        self._max_batch = max_batch
        self._flush_interval = flush_interval_s
        self._queue: List[Span] = []
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def on_end(self, span: Span) -> None:
        with self._lock:
            self._queue.append(span)
            if len(self._queue) >= self._max_batch:
                batch = self._queue[:]
                self._queue.clear()
        if len(self._queue) == 0 and 'batch' in dir():
            pass
        else:
            batch = None
        if batch:
            self._exporter.export(batch)

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(self._flush_interval)
            self.force_flush()

    def force_flush(self) -> None:
        with self._lock:
            if self._queue:
                batch = self._queue[:]
                self._queue.clear()
            else:
                batch = None
        if batch:
            self._exporter.export(batch)

    def shutdown(self) -> None:
        self._running = False
        self.force_flush()
        self._exporter.shutdown()


class SimpleSpanProcessor:
    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter

    def on_end(self, span: Span) -> None:
        self._exporter.export([span])

    def force_flush(self) -> None:
        pass

    def shutdown(self) -> None:
        self._exporter.shutdown()


# ---------------------------------------------------------------------------
# Tracer & TracerProvider
# ---------------------------------------------------------------------------

_context_var = threading.local()


def _current_span() -> Optional[Span]:
    stack = getattr(_context_var, "span_stack", [])
    return stack[-1] if stack else None


def _push_span(span: Span) -> None:
    if not hasattr(_context_var, "span_stack"):
        _context_var.span_stack = []
    _context_var.span_stack.append(span)


def _pop_span() -> Optional[Span]:
    stack = getattr(_context_var, "span_stack", [])
    return stack.pop() if stack else None


def _gen_id(length: int = 32) -> str:
    raw = uuid.uuid4().hex
    if length == 32:
        return uuid.uuid4().hex  # trace_id: 128-bit
    return raw[:16]  # span_id: 64-bit


class Tracer:
    def __init__(self, name: str, provider: "TracerProvider") -> None:
        self.name = name
        self._provider = provider

    @contextlib.contextmanager
    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None,
        links: Optional[List[SpanLink]] = None,
        parent_context: Optional[TraceContext] = None,
    ):
        parent = _current_span()

        if parent_context:
            trace_id = parent_context.trace_id
            parent_span_id = parent_context.span_id
        elif parent:
            trace_id = parent.trace_id
            parent_span_id = parent.span_id
        else:
            trace_id = _gen_id(32)
            parent_span_id = None

        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=_gen_id(16),
            parent_span_id=parent_span_id,
            kind=kind,
            start_time_ns=time.time_ns(),
            attributes=attributes or {},
            links=links or [],
            resource=self._provider.resource,
        )

        _push_span(span)
        try:
            yield span
            if span.status == SpanStatus.UNSET:
                span.status = SpanStatus.OK
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            _pop_span()
            for proc in self._provider._processors:
                proc.on_end(span)

    def start_span_no_context(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Span:
        return Span(
            name=name,
            trace_id=trace_id or _gen_id(32),
            span_id=_gen_id(16),
            parent_span_id=parent_span_id,
            kind=kind,
            start_time_ns=time.time_ns(),
            attributes=attributes or {},
            resource=self._provider.resource,
        )


class TracerProvider:
    def __init__(self, resource: Optional[Dict[str, str]] = None) -> None:
        self.resource: Dict[str, str] = resource or {
            "service.name": "local-agent-runtime",
            "service.version": "1.0.0",
        }
        self._processors: List[Any] = []
        self._tracers: Dict[str, Tracer] = {}

    def add_span_processor(self, processor) -> "TracerProvider":
        self._processors.append(processor)
        return self

    def get_tracer(self, name: str) -> Tracer:
        if name not in self._tracers:
            self._tracers[name] = Tracer(name, self)
        return self._tracers[name]

    def shutdown(self) -> None:
        for p in self._processors:
            p.shutdown()


# ---------------------------------------------------------------------------
# Trace analytics: latency, error aggregation, correlation
# ---------------------------------------------------------------------------

class TraceAnalyzer:
    def __init__(self, exporter: InMemoryExporter) -> None:
        self._exporter = exporter

    def get_traces(self) -> Dict[str, List[Span]]:
        traces: Dict[str, List[Span]] = defaultdict(list)
        for span in self._exporter.get_spans():
            traces[span.trace_id].append(span)
        return dict(traces)

    def get_trace(self, trace_id: str) -> List[Span]:
        return [s for s in self._exporter.get_spans() if s.trace_id == trace_id]

    def latency_summary(self, trace_id: str) -> Dict[str, Any]:
        spans = self.get_trace(trace_id)
        if not spans:
            return {"error": "trace not found"}
        total_ms = max(s.end_time_ns for s in spans) - min(s.start_time_ns for s in spans)
        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "total_duration_ms": total_ms / 1_000_000,
            "spans": [
                {"name": s.name, "duration_ms": s.duration_ms, "status": s.status.value}
                for s in sorted(spans, key=lambda x: x.start_time_ns)
            ],
        }

    def error_spans(self, trace_id: Optional[str] = None) -> List[Span]:
        spans = self._exporter.get_spans()
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return [s for s in spans if s.is_error]

    def error_propagation_chain(self, trace_id: str) -> List[Dict[str, Any]]:
        spans = self.get_trace(trace_id)
        error_spans = [s for s in spans if s.is_error]
        span_map = {s.span_id: s for s in spans}

        chains: List[Dict[str, Any]] = []
        for es in error_spans:
            chain = []
            current = es
            while current:
                chain.append({
                    "span_id": current.span_id,
                    "name": current.name,
                    "status": current.status.value,
                    "status_message": current.status_message,
                    "duration_ms": current.duration_ms,
                })
                current = span_map.get(current.parent_span_id) if current.parent_span_id else None
            chains.append({"error_origin": es.name, "propagation_path": list(reversed(chain))})
        return chains

    def correlate_spans(self, attribute_key: str, attribute_value: Any) -> List[Span]:
        return [
            s for s in self._exporter.get_spans()
            if s.attributes.get(attribute_key) == attribute_value
        ]

    def slowest_spans(self, n: int = 5) -> List[Span]:
        spans = self._exporter.get_spans()
        return sorted(spans, key=lambda s: s.duration_ms, reverse=True)[:n]

    def service_breakdown(self) -> Dict[str, Dict[str, Any]]:
        breakdown: Dict[str, Dict[str, Any]] = {}
        for span in self._exporter.get_spans():
            svc = span.resource.get("service.name", "unknown")
            if svc not in breakdown:
                breakdown[svc] = {"span_count": 0, "error_count": 0, "total_ms": 0.0}
            breakdown[svc]["span_count"] += 1
            breakdown[svc]["total_ms"] += span.duration_ms
            if span.is_error:
                breakdown[svc]["error_count"] += 1
        for svc in breakdown:
            cnt = breakdown[svc]["span_count"]
            breakdown[svc]["avg_ms"] = breakdown[svc]["total_ms"] / cnt if cnt else 0
            breakdown[svc]["error_rate"] = breakdown[svc]["error_count"] / cnt if cnt else 0
        return breakdown


# ---------------------------------------------------------------------------
# Decorators for easy instrumentation
# ---------------------------------------------------------------------------

def trace(
    tracer: Tracer,
    name: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[Dict[str, Any]] = None,
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        span_name = name or fn.__qualname__

        def wrapper(*args, **kwargs):
            with tracer.start_span(span_name, kind=kind, attributes=attributes) as span:
                span.set_attribute("code.function", fn.__name__)
                return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        wrapper.__qualname__ = fn.__qualname__
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Middleware helper for HTTP-style request tracing
# ---------------------------------------------------------------------------

class TracingMiddleware:
    def __init__(self, tracer: Tracer) -> None:
        self.tracer = tracer

    def handle_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        handler: Callable,
    ) -> Dict[str, Any]:
        parent_ctx = TraceContext.extract(headers)
        attrs = {"http.method": method, "http.target": path}

        with self.tracer.start_span(
            f"{method} {path}",
            kind=SpanKind.SERVER,
            attributes=attrs,
            parent_context=parent_ctx,
        ) as span:
            try:
                result = handler()
                span.set_attribute("http.status_code", result.get("status", 200))
                return result
            except Exception as exc:
                span.set_attribute("http.status_code", 500)
                raise


# ===========================================================================
# __main__: full integration test with assertions
# ===========================================================================

if __name__ == "__main__":

    # --- Setup provider + in-memory exporter ---
    exporter = InMemoryExporter()
    processor = SimpleSpanProcessor(exporter)
    provider = TracerProvider(resource={"service.name": "test-service", "service.version": "0.1.0"})
    provider.add_span_processor(processor)
    tracer = provider.get_tracer("test-tracer")

    # =========================================================================
    # TEST 1: Basic span creation and hierarchy
    # =========================================================================
    with tracer.start_span("root-operation", attributes={"user.id": "u-123"}) as root:
        root_trace_id = root.trace_id
        root_span_id = root.span_id

        with tracer.start_span("child-db-query", kind=SpanKind.CLIENT) as child:
            child.set_attribute("db.system", "postgresql")
            child.set_attribute("db.statement", "SELECT * FROM tasks")
            time.sleep(0.01)  # simulate latency

            with tracer.start_span("child-cache-lookup") as grandchild:
                grandchild.set_attribute("cache.hit", True)
                time.sleep(0.005)

        with tracer.start_span("child-http-call", kind=SpanKind.CLIENT) as http_child:
            http_child.set_attribute("http.url", "https://api.example.com/data")
            time.sleep(0.008)

    spans = exporter.get_spans()

    # Verify span count
    assert len(spans) == 4, f"Expected 4 spans, got {len(spans)}"

    # Verify all share the same trace_id
    trace_ids = set(s.trace_id for s in spans)
    assert len(trace_ids) == 1, f"Expected 1 trace, got {len(trace_ids)}"
    assert root_trace_id in trace_ids

    # Verify parent-child relationships
    span_by_name = {s.name: s for s in spans}
    assert span_by_name["root-operation"].parent_span_id is None
    assert span_by_name["child-db-query"].parent_span_id == root_span_id
    assert span_by_name["child-cache-lookup"].parent_span_id == span_by_name["child-db-query"].span_id
    assert span_by_name["child-http-call"].parent_span_id == root_span_id

    # Verify latency recorded
    for s in spans:
        assert s.duration_ms > 0, f"Span {s.name} has no duration"
        assert s.status == SpanStatus.OK

    # Verify attributes
    assert span_by_name["root-operation"].attributes["user.id"] == "u-123"
    assert span_by_name["child-db-query"].attributes["db.system"] == "postgresql"
    assert span_by_name["child-cache-lookup"].attributes["cache.hit"] is True
    print("TEST 1 PASSED: Basic span creation and hierarchy")

    # =========================================================================
    # TEST 2: Error propagation and exception recording
    # =========================================================================
    exporter.clear()

    try:
        with tracer.start_span("failing-pipeline") as pipeline:
            pipeline_trace = pipeline.trace_id
            with tracer.start_span("agent-router") as router:
                router.set_attribute("agent.name", "router")
                time.sleep(0.005)
            with tracer.start_span("agent-executor") as executor:
                executor.set_attribute("agent.name", "executor")
                raise RuntimeError("Model inference timeout")
    except RuntimeError:
        pass

    spans = exporter.get_spans()
    assert len(spans) == 3

    span_by_name = {s.name: s for s in spans}
    # The executor where the exception originated should be ERROR
    assert span_by_name["agent-executor"].status == SpanStatus.ERROR
    assert "timeout" in span_by_name["agent-executor"].status_message.lower()
    assert len(span_by_name["agent-executor"].events) == 1
    assert span_by_name["agent-executor"].events[0].name == "exception"
    assert span_by_name["agent-executor"].events[0].attributes["exception.type"] == "RuntimeError"

    # The parent pipeline should also be ERROR (exception propagated)
    assert span_by_name["failing-pipeline"].status == SpanStatus.ERROR

    # Router completed before the error, so it should be OK
    assert span_by_name["agent-router"].status == SpanStatus.OK
    print("TEST 2 PASSED: Error propagation and exception recording")

    # =========================================================================
    # TEST 3: W3C Trace Context propagation
    # =========================================================================
    exporter.clear()

    # Simulate an incoming request with traceparent header
    incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"
    incoming_span_id = "b7ad6b7169203331"
    headers = {"traceparent": f"00-{incoming_trace_id}-{incoming_span_id}-01"}

    ctx = TraceContext.extract(headers)
    assert ctx is not None
    assert ctx.trace_id == incoming_trace_id
    assert ctx.span_id == incoming_span_id
    assert ctx.trace_flags == 1

    # Create a child span using the extracted context
    with tracer.start_span("downstream-service", parent_context=ctx) as span:
        assert span.trace_id == incoming_trace_id
        assert span.parent_span_id == incoming_span_id
        # Inject into outgoing headers
        out_headers: Dict[str, str] = {}
        child_ctx = TraceContext(trace_id=span.trace_id, span_id=span.span_id)
        child_ctx.inject(out_headers)
        assert "traceparent" in out_headers
        parts = out_headers["traceparent"].split("-")
        assert parts[1] == incoming_trace_id  # trace preserved

    # Round-trip
    reparsed = TraceContext.from_traceparent(out_headers["traceparent"])
    assert reparsed.trace_id == incoming_trace_id
    print("TEST 3 PASSED: W3C Trace Context propagation")

    # =========================================================================
    # TEST 4: TraceAnalyzer — latency summary, error chains, correlations
    # =========================================================================
    exporter.clear()

    # Build a multi-span trace with one error branch
    with tracer.start_span("request-handler", attributes={"request.id": "req-001"}) as root:
        analysis_trace = root.trace_id
        with tracer.start_span("validate-input") as v:
            v.set_attribute("request.id", "req-001")
            time.sleep(0.003)
        with tracer.start_span("run-pipeline", attributes={"request.id": "req-001"}) as pipe:
            with tracer.start_span("agent-retriever") as retriever:
                retriever.set_attribute("agent.type", "retriever")
                time.sleep(0.01)
            try:
                with tracer.start_span("agent-skeptic") as skeptic:
                    skeptic.set_attribute("agent.type", "skeptic")
                    time.sleep(0.005)
                    raise ValueError("Contradictory evidence found")
            except ValueError:
                pass
        with tracer.start_span("format-response") as fmt:
            time.sleep(0.002)

    analyzer = TraceAnalyzer(exporter)

    # Latency summary
    summary = analyzer.latency_summary(analysis_trace)
    assert summary["span_count"] == 6
    assert summary["total_duration_ms"] > 0
    assert len(summary["spans"]) == 6

    # Error spans — only agent-skeptic is ERROR (exception caught before propagating)
    errors = analyzer.error_spans(analysis_trace)
    assert len(errors) == 1, f"Expected 1 error span, got {len(errors)}: {[e.name for e in errors]}"
    assert errors[0].name == "agent-skeptic"

    # Error propagation chain — traces ancestry from error span up to root
    chains = analyzer.error_propagation_chain(analysis_trace)
    assert len(chains) == 1
    skeptic_chain = chains[0]
    assert skeptic_chain["error_origin"] == "agent-skeptic"
    path_names = [p["name"] for p in skeptic_chain["propagation_path"]]
    assert "request-handler" in path_names  # chain goes up to root
    assert "run-pipeline" in path_names     # passes through parent
    assert "agent-skeptic" in path_names    # ends at error origin

    # Correlation by attribute
    correlated = analyzer.correlate_spans("request.id", "req-001")
    assert len(correlated) >= 2  # root + validate-input + run-pipeline

    # Slowest spans
    slowest = analyzer.slowest_spans(3)
    assert len(slowest) == 3
    assert slowest[0].duration_ms >= slowest[1].duration_ms >= slowest[2].duration_ms

    # Service breakdown
    breakdown = analyzer.service_breakdown()
    assert "test-service" in breakdown
    assert breakdown["test-service"]["span_count"] == 6
    assert breakdown["test-service"]["error_count"] == 1
    assert 0 < breakdown["test-service"]["error_rate"] < 1
    print("TEST 4 PASSED: TraceAnalyzer — latency, errors, correlations")

    # =========================================================================
    # TEST 5: @trace decorator
    # =========================================================================
    exporter.clear()

    @trace(tracer, name="decorated-operation", attributes={"tier": "premium"})
    def my_operation(x: int, y: int) -> int:
        time.sleep(0.005)
        return x + y

    result = my_operation(3, 7)
    assert result == 10

    spans = exporter.get_spans()
    assert len(spans) == 1
    assert spans[0].name == "decorated-operation"
    assert spans[0].attributes["tier"] == "premium"
    assert spans[0].attributes["code.function"] == "my_operation"
    assert spans[0].status == SpanStatus.OK
    assert spans[0].duration_ms >= 5
    print("TEST 5 PASSED: @trace decorator")

    # =========================================================================
    # TEST 6: TracingMiddleware
    # =========================================================================
    exporter.clear()

    middleware = TracingMiddleware(tracer)
    handler_result = middleware.handle_request(
        method="POST",
        path="/api/diagnose",
        headers={},
        handler=lambda: {"status": 200, "body": {"id": "diag-001"}},
    )

    assert handler_result["status"] == 200
    spans = exporter.get_spans()
    assert len(spans) == 1
    assert spans[0].name == "POST /api/diagnose"
    assert spans[0].kind == SpanKind.SERVER
    assert spans[0].attributes["http.method"] == "POST"
    assert spans[0].attributes["http.status_code"] == 200
    print("TEST 6 PASSED: TracingMiddleware")

    # =========================================================================
    # TEST 7: Cross-service correlation via span links
    # =========================================================================
    exporter.clear()

    # Simulate a producer creating a task
    with tracer.start_span("enqueue-task", kind=SpanKind.PRODUCER) as producer:
        producer_trace = producer.trace_id
        producer_span = producer.span_id
        producer.set_attribute("task.id", "t-abc")

    # Consumer picks up the task and links back
    link = SpanLink(
        trace_id=producer_trace,
        span_id=producer_span,
        attributes={"link.type": "follows_from"},
    )
    with tracer.start_span("process-task", kind=SpanKind.CONSUMER, links=[link]) as consumer:
        consumer.set_attribute("task.id", "t-abc")
        time.sleep(0.005)

    spans = exporter.get_spans()
    consumer_span = [s for s in spans if s.name == "process-task"][0]
    assert len(consumer_span.links) == 1
    assert consumer_span.links[0].trace_id == producer_trace
    assert consumer_span.links[0].span_id == producer_span
    assert consumer_span.links[0].attributes["link.type"] == "follows_from"
    print("TEST 7 PASSED: Cross-service span links")

    # =========================================================================
    # TEST 8: Span serialization to dict / JSON
    # =========================================================================
    exporter.clear()

    with tracer.start_span("serialize-test", attributes={"key": "value"}) as span:
        span.add_event("checkpoint", {"step": 1})

    spans = exporter.get_spans()
    d = spans[0].to_dict()
    assert d["name"] == "serialize-test"
    assert d["status"] == "OK"
    assert d["duration_ms"] > 0
    assert d["attributes"]["key"] == "value"
    assert len(d["events"]) == 1
    assert d["events"][0]["name"] == "checkpoint"

    # Ensure JSON-serializable
    json_str = json.dumps(d, default=str)
    reparsed = json.loads(json_str)
    assert reparsed["name"] == "serialize-test"
    print("TEST 8 PASSED: Span serialization")

    # =========================================================================
    # Cleanup
    # =========================================================================
    provider.shutdown()

    print("\n" + "=" * 60)
    print("ALL 8 TESTS PASSED — distributed tracing fully operational")
    print("=" * 60)
