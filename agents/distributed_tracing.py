"""
Distributed Request Tracing — OpenTelemetry-compatible tracing for the agent runtime.

Provides:
  - Trace IDs and span IDs (W3C Trace Context format)
  - Latency tracking per span with start/end timestamps
  - Error propagation across nested spans
  - Correlations between parent/child spans and across services
  - Context propagation via TracingContext carrier
  - Span export to JSONL for analysis

Usage:
    from agents.distributed_tracing import Tracer, TracingContext, InMemoryExporter

    exporter = InMemoryExporter()
    tracer = Tracer(service_name="agent-runtime", exporter=exporter)

    with tracer.start_span("handle_task") as span:
        span.set_attribute("task.id", "t-abc123")
        with tracer.start_span("call_executor") as child:
            child.set_attribute("agent", "executor")
        # child auto-closes with latency recorded

    for s in exporter.spans:
        print(s.to_dict())
"""

import json
import os
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ID generation (W3C Trace Context compatible)
# ---------------------------------------------------------------------------

def _random_hex(n_bytes: int) -> str:
    """Generate a lowercase hex string of *n_bytes* random bytes."""
    return os.urandom(n_bytes).hex()


def generate_trace_id() -> str:
    """128-bit trace ID as 32-char hex string."""
    return _random_hex(16)


def generate_span_id() -> str:
    """64-bit span ID as 16-char hex string."""
    return _random_hex(8)


# ---------------------------------------------------------------------------
# Span status
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


# ---------------------------------------------------------------------------
# Event (span event / log)
# ---------------------------------------------------------------------------

@dataclass
class SpanEvent:
    name: str
    timestamp: float = field(default_factory=time.time)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timestamp_ms": int(self.timestamp * 1000),
            "attributes": dict(self.attributes),
        }


# ---------------------------------------------------------------------------
# Link (correlation between spans across traces)
# ---------------------------------------------------------------------------

@dataclass
class SpanLink:
    trace_id: str
    span_id: str
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attributes": dict(self.attributes),
        }


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

class Span:
    """A single unit of work within a trace."""

    def __init__(
        self,
        name: str,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str] = None,
        kind: SpanKind = SpanKind.INTERNAL,
        service_name: str = "unknown",
    ):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.kind = kind
        self.service_name = service_name

        self.start_time: float = time.time()
        self.end_time: Optional[float] = None
        self.status: SpanStatus = SpanStatus.UNSET
        self.status_message: str = ""
        self.attributes: Dict[str, Any] = {}
        self.events: List[SpanEvent] = []
        self.links: List[SpanLink] = []
        self._ended = False

    # -- attributes ----------------------------------------------------------

    def set_attribute(self, key: str, value: Any) -> "Span":
        self.attributes[key] = value
        return self

    def set_attributes(self, attrs: Dict[str, Any]) -> "Span":
        self.attributes.update(attrs)
        return self

    # -- events --------------------------------------------------------------

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> "Span":
        self.events.append(SpanEvent(name=name, attributes=attributes or {}))
        return self

    # -- links (cross-trace correlations) ------------------------------------

    def add_link(self, trace_id: str, span_id: str, attributes: Optional[Dict[str, Any]] = None) -> "Span":
        self.links.append(SpanLink(trace_id=trace_id, span_id=span_id, attributes=attributes or {}))
        return self

    # -- status / error propagation ------------------------------------------

    def set_status(self, status: SpanStatus, message: str = "") -> "Span":
        self.status = status
        self.status_message = message
        return self

    def record_exception(self, exc: BaseException) -> "Span":
        self.set_status(SpanStatus.ERROR, str(exc))
        self.add_event(
            "exception",
            {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
            },
        )
        return self

    # -- lifecycle -----------------------------------------------------------

    def end(self) -> None:
        if self._ended:
            return
        self.end_time = time.time()
        self._ended = True

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    @property
    def is_ended(self) -> bool:
        return self._ended

    # -- W3C traceparent header ----------------------------------------------

    @property
    def traceparent(self) -> str:
        """Generate W3C traceparent header value."""
        flags = "01"  # sampled
        return f"00-{self.trace_id}-{self.span_id}-{flags}"

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind.value,
            "service_name": self.service_name,
            "start_time_ms": int(self.start_time * 1000),
            "end_time_ms": int(self.end_time * 1000) if self.end_time else None,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status.value,
            "status_message": self.status_message,
            "attributes": dict(self.attributes),
        }
        if self.events:
            d["events"] = [e.to_dict() for e in self.events]
        if self.links:
            d["links"] = [lnk.to_dict() for lnk in self.links]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"Span(name={self.name!r}, trace={self.trace_id[:8]}..., "
            f"span={self.span_id[:8]}..., status={self.status.value}, "
            f"duration={self.duration_ms:.1f}ms)"
        )


# ---------------------------------------------------------------------------
# Tracing context (propagation carrier)
# ---------------------------------------------------------------------------

class TracingContext:
    """Thread-local context for propagating trace/span IDs across call boundaries."""

    _local = threading.local()

    @classmethod
    def current_span(cls) -> Optional[Span]:
        stack = getattr(cls._local, "span_stack", [])
        return stack[-1] if stack else None

    @classmethod
    def _push(cls, span: Span) -> None:
        if not hasattr(cls._local, "span_stack"):
            cls._local.span_stack = []
        cls._local.span_stack.append(span)

    @classmethod
    def _pop(cls) -> Optional[Span]:
        stack = getattr(cls._local, "span_stack", [])
        return stack.pop() if stack else None

    @classmethod
    def inject(cls) -> Dict[str, str]:
        """Inject current trace context into a carrier dict (for cross-service propagation)."""
        span = cls.current_span()
        if span is None:
            return {}
        return {"traceparent": span.traceparent}

    @classmethod
    def extract(cls, carrier: Dict[str, str]) -> Optional[Dict[str, str]]:
        """Extract trace/span IDs from a carrier dict."""
        tp = carrier.get("traceparent")
        if not tp:
            return None
        parts = tp.split("-")
        if len(parts) != 4:
            return None
        return {
            "version": parts[0],
            "trace_id": parts[1],
            "span_id": parts[2],
            "flags": parts[3],
        }

    @classmethod
    def clear(cls) -> None:
        cls._local.span_stack = []


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

class SpanExporter:
    """Base exporter interface."""

    def export(self, span: Span) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        pass


class InMemoryExporter(SpanExporter):
    """Collects spans in memory for testing and assertions."""

    def __init__(self) -> None:
        self.spans: List[Span] = []
        self._lock = threading.Lock()

    def export(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)

    def get_spans_by_trace(self, trace_id: str) -> List[Span]:
        with self._lock:
            return [s for s in self.spans if s.trace_id == trace_id]

    def get_spans_by_name(self, name: str) -> List[Span]:
        with self._lock:
            return [s for s in self.spans if s.name == name]

    def clear(self) -> None:
        with self._lock:
            self.spans.clear()

    def shutdown(self) -> None:
        pass


class JSONLFileExporter(SpanExporter):
    """Appends spans as JSONL to a file."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self._lock = threading.Lock()

    def export(self, span: Span) -> None:
        line = span.to_json() + "\n"
        with self._lock:
            with open(self.file_path, "a") as f:
                f.write(line)

    def shutdown(self) -> None:
        pass


class CompositeExporter(SpanExporter):
    """Fan-out to multiple exporters."""

    def __init__(self, exporters: List[SpanExporter]) -> None:
        self.exporters = list(exporters)

    def export(self, span: Span) -> None:
        for exp in self.exporters:
            exp.export(span)

    def shutdown(self) -> None:
        for exp in self.exporters:
            exp.shutdown()


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """Creates and manages spans within a service."""

    def __init__(
        self,
        service_name: str = "agent-runtime",
        exporter: Optional[SpanExporter] = None,
    ):
        self.service_name = service_name
        self.exporter = exporter or InMemoryExporter()

    @contextmanager
    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        parent: Optional[Span] = None,
        links: Optional[List[SpanLink]] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Context manager that creates, activates, and auto-closes a span."""
        # Determine parent
        if parent is None:
            parent = TracingContext.current_span()

        if parent is not None:
            trace_id = parent.trace_id
            parent_span_id = parent.span_id
        else:
            trace_id = generate_trace_id()
            parent_span_id = None

        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=generate_span_id(),
            parent_span_id=parent_span_id,
            kind=kind,
            service_name=self.service_name,
        )
        if links:
            span.links = list(links)
        if attributes:
            span.set_attributes(attributes)

        TracingContext._push(span)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            TracingContext._pop()
            self.exporter.export(span)

    def start_span_from_carrier(
        self,
        name: str,
        carrier: Dict[str, str],
        kind: SpanKind = SpanKind.SERVER,
    ):
        """Start a span using propagated context from an incoming request."""
        extracted = TracingContext.extract(carrier)
        if extracted:
            trace_id = extracted["trace_id"]
            parent_span_id = extracted["span_id"]
        else:
            trace_id = generate_trace_id()
            parent_span_id = None

        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=generate_span_id(),
            parent_span_id=parent_span_id,
            kind=kind,
            service_name=self.service_name,
        )
        return self._managed_span(span)

    @contextmanager
    def _managed_span(self, span: Span):
        TracingContext._push(span)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            TracingContext._pop()
            self.exporter.export(span)

    def shutdown(self) -> None:
        self.exporter.shutdown()


# ---------------------------------------------------------------------------
# Trace analysis utilities
# ---------------------------------------------------------------------------

def build_trace_tree(spans: List[Span]) -> Dict[str, Any]:
    """Build a nested tree structure from a flat list of spans in the same trace."""
    by_id: Dict[str, Dict[str, Any]] = {}
    roots: List[Dict[str, Any]] = []

    for s in sorted(spans, key=lambda x: x.start_time):
        node = {"span": s, "children": []}
        by_id[s.span_id] = node

    for s in sorted(spans, key=lambda x: x.start_time):
        node = by_id[s.span_id]
        if s.parent_span_id and s.parent_span_id in by_id:
            by_id[s.parent_span_id]["children"].append(node)
        else:
            roots.append(node)

    return {"roots": roots, "total_spans": len(spans)}


def compute_critical_path(spans: List[Span]) -> List[Span]:
    """Return the longest latency path through the trace tree."""
    tree = build_trace_tree(spans)
    if not tree["roots"]:
        return []

    def _longest(node: Dict[str, Any]) -> List[Span]:
        span = node["span"]
        if not node["children"]:
            return [span]
        child_paths = [_longest(c) for c in node["children"]]
        longest_child = max(child_paths, key=lambda p: sum(s.duration_ms for s in p))
        return [span] + longest_child

    all_paths = [_longest(r) for r in tree["roots"]]
    return max(all_paths, key=lambda p: sum(s.duration_ms for s in p))


def find_error_spans(spans: List[Span]) -> List[Span]:
    """Return all spans with ERROR status."""
    return [s for s in spans if s.status == SpanStatus.ERROR]


def trace_summary(spans: List[Span]) -> Dict[str, Any]:
    """Compute summary statistics for a trace."""
    if not spans:
        return {"total_spans": 0}

    durations = [s.duration_ms for s in spans if s.is_ended]
    errors = find_error_spans(spans)
    services = set(s.service_name for s in spans)
    root_spans = [s for s in spans if s.parent_span_id is None]

    return {
        "trace_id": spans[0].trace_id,
        "total_spans": len(spans),
        "total_duration_ms": round(max(s.end_time for s in spans if s.end_time) - min(s.start_time for s in spans), 4) * 1000 if durations else 0,
        "avg_span_duration_ms": round(sum(durations) / len(durations), 3) if durations else 0,
        "max_span_duration_ms": round(max(durations), 3) if durations else 0,
        "error_count": len(errors),
        "error_rate": round(len(errors) / len(spans), 4) if spans else 0,
        "services": sorted(services),
        "root_span_count": len(root_spans),
        "critical_path_depth": len(compute_critical_path(spans)),
    }


# ---------------------------------------------------------------------------
# __main__ — verification assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Distributed Tracing — Verification Suite")
    print("=" * 60)

    # ---- Test 1: Basic span creation and trace ID propagation ----
    print("\n[1] Span creation and trace propagation...")
    exporter = InMemoryExporter()
    tracer = Tracer(service_name="test-service", exporter=exporter)

    with tracer.start_span("root_op") as root:
        root.set_attribute("task.id", "t-001")
        assert len(root.trace_id) == 32, f"trace_id should be 32 hex chars, got {len(root.trace_id)}"
        assert len(root.span_id) == 16, f"span_id should be 16 hex chars, got {len(root.span_id)}"
        assert root.parent_span_id is None, "Root span should have no parent"

        with tracer.start_span("child_op") as child:
            child.set_attribute("step", 1)
            assert child.trace_id == root.trace_id, "Child must share parent trace ID"
            assert child.parent_span_id == root.span_id, "Child parent_span_id must match root span_id"

            with tracer.start_span("grandchild_op") as gc:
                gc.set_attribute("depth", 3)
                assert gc.trace_id == root.trace_id, "Grandchild must share root trace ID"
                assert gc.parent_span_id == child.span_id, "Grandchild parent must be child"

    assert len(exporter.spans) == 3, f"Expected 3 spans, got {len(exporter.spans)}"
    assert all(s.is_ended for s in exporter.spans), "All spans should be ended"
    print("  PASS: 3 nested spans with correct trace/parent propagation")

    # ---- Test 2: Latency tracking ----
    print("\n[2] Latency tracking...")
    exporter.clear()

    with tracer.start_span("timed_op") as span:
        time.sleep(0.05)  # 50ms

    timed = exporter.spans[0]
    assert timed.end_time is not None, "Span should have end_time"
    assert timed.duration_ms >= 40, f"Duration should be >= 40ms, got {timed.duration_ms:.1f}ms"
    assert timed.duration_ms < 500, f"Duration should be < 500ms, got {timed.duration_ms:.1f}ms"
    assert timed.start_time < timed.end_time, "start_time must be before end_time"
    print(f"  PASS: Latency recorded as {timed.duration_ms:.1f}ms")

    # ---- Test 3: Error propagation ----
    print("\n[3] Error propagation...")
    exporter.clear()

    try:
        with tracer.start_span("failing_op") as span:
            span.set_attribute("task.id", "t-fail")
            with tracer.start_span("inner_fail") as inner:
                raise ValueError("simulated DB timeout")
    except ValueError:
        pass

    assert len(exporter.spans) == 2, f"Expected 2 spans, got {len(exporter.spans)}"
    inner_span = exporter.spans[0]  # inner ends first
    outer_span = exporter.spans[1]

    assert inner_span.status == SpanStatus.ERROR, "Inner span should have ERROR status"
    assert "simulated DB timeout" in inner_span.status_message
    assert len(inner_span.events) == 1, "Inner span should have exception event"
    assert inner_span.events[0].name == "exception"
    assert inner_span.events[0].attributes["exception.type"] == "ValueError"

    # Outer span should also be ERROR because exception propagated
    assert outer_span.status == SpanStatus.ERROR, "Outer span should also be ERROR (exception propagated)"
    errors = find_error_spans(exporter.spans)
    assert len(errors) == 2, "Both spans should be in error"
    print("  PASS: Error propagated from inner to outer span with exception events")

    # ---- Test 4: W3C traceparent context propagation ----
    print("\n[4] Cross-service context propagation (W3C traceparent)...")
    exporter.clear()

    # Service A creates a request
    tracer_a = Tracer(service_name="service-a", exporter=exporter)
    tracer_b = Tracer(service_name="service-b", exporter=exporter)

    with tracer_a.start_span("handle_request", kind=SpanKind.CLIENT) as span_a:
        span_a.set_attribute("http.method", "POST")
        # Inject context into "headers"
        headers = TracingContext.inject()
        assert "traceparent" in headers, "Should inject traceparent header"

        tp = headers["traceparent"]
        parts = tp.split("-")
        assert len(parts) == 4, "traceparent must have 4 parts"
        assert parts[0] == "00", "Version must be 00"
        assert parts[1] == span_a.trace_id, "trace_id in header must match span"
        assert parts[2] == span_a.span_id, "span_id in header must match span"

    # Service B receives the request
    with tracer_b.start_span_from_carrier("process_request", carrier=headers) as span_b:
        span_b.set_attribute("http.status_code", 200)
        assert span_b.trace_id == span_a.trace_id, "Service B must continue same trace"
        assert span_b.parent_span_id == span_a.span_id, "Service B parent must be Service A span"

    assert len(exporter.spans) == 2
    services = {s.service_name for s in exporter.spans}
    assert services == {"service-a", "service-b"}, "Should have spans from both services"
    print(f"  PASS: Context propagated via traceparent: {tp[:40]}...")

    # ---- Test 5: Span links (correlations) ----
    print("\n[5] Span links (cross-trace correlations)...")
    exporter.clear()

    # Create a "cause" trace
    with tracer.start_span("cause_operation") as cause_span:
        cause_span.set_attribute("trigger", "webhook")
        cause_trace_id = cause_span.trace_id
        cause_span_id = cause_span.span_id

    # Create an "effect" trace that links back to the cause
    with tracer.start_span("effect_operation") as effect_span:
        effect_span.add_link(
            trace_id=cause_trace_id,
            span_id=cause_span_id,
            attributes={"link.type": "caused_by"},
        )
        effect_span.set_attribute("source", "async_queue")

    assert len(exporter.spans) == 2
    effect = exporter.spans[1]
    assert len(effect.links) == 1, "Effect span should have 1 link"
    assert effect.links[0].trace_id == cause_trace_id
    assert effect.links[0].span_id == cause_span_id
    assert effect.links[0].attributes["link.type"] == "caused_by"
    # Different traces
    assert exporter.spans[0].trace_id != exporter.spans[1].trace_id, "Should be different traces"
    print("  PASS: Cross-trace link established with correlation attributes")

    # ---- Test 6: Trace tree and critical path ----
    print("\n[6] Trace tree and critical path analysis...")
    exporter.clear()

    with tracer.start_span("root") as r:
        with tracer.start_span("fast_child") as fc:
            time.sleep(0.01)
        with tracer.start_span("slow_child") as sc:
            time.sleep(0.05)
            with tracer.start_span("slow_grandchild") as sg:
                time.sleep(0.03)

    trace_spans = exporter.get_spans_by_trace(r.trace_id)
    assert len(trace_spans) == 4, f"Expected 4 spans in trace, got {len(trace_spans)}"

    tree = build_trace_tree(trace_spans)
    assert tree["total_spans"] == 4
    assert len(tree["roots"]) == 1, "Should have exactly 1 root"
    assert len(tree["roots"][0]["children"]) == 2, "Root should have 2 children"

    crit_path = compute_critical_path(trace_spans)
    assert len(crit_path) >= 2, "Critical path should have at least 2 spans"
    crit_names = [s.name for s in crit_path]
    assert "root" in crit_names, "Critical path should include root"
    assert "slow_child" in crit_names, "Critical path should go through slow_child"
    print(f"  PASS: Tree built with 4 spans, critical path: {' -> '.join(crit_names)}")

    # ---- Test 7: Trace summary statistics ----
    print("\n[7] Trace summary statistics...")
    summary = trace_summary(trace_spans)
    assert summary["trace_id"] == r.trace_id
    assert summary["total_spans"] == 4
    assert summary["error_count"] == 0
    assert summary["error_rate"] == 0.0
    assert summary["services"] == ["test-service"]
    assert summary["root_span_count"] == 1
    assert summary["critical_path_depth"] >= 2
    assert summary["max_span_duration_ms"] > 0
    assert summary["avg_span_duration_ms"] > 0
    print(f"  PASS: Summary — {summary['total_spans']} spans, "
          f"total={summary['total_duration_ms']:.0f}ms, "
          f"errors={summary['error_count']}")

    # ---- Test 8: JSONL export ----
    print("\n[8] JSONL file export...")
    jsonl_path = "/tmp/test_tracing_export.jsonl"
    if os.path.exists(jsonl_path):
        os.remove(jsonl_path)

    file_exporter = JSONLFileExporter(jsonl_path)
    tracer_file = Tracer(service_name="file-test", exporter=file_exporter)

    with tracer_file.start_span("exported_op") as s:
        s.set_attribute("key", "value")

    with open(jsonl_path) as f:
        lines = f.readlines()
    assert len(lines) == 1, "Should have 1 JSONL line"
    data = json.loads(lines[0])
    assert data["name"] == "exported_op"
    assert data["service_name"] == "file-test"
    assert data["attributes"]["key"] == "value"
    assert data["trace_id"] is not None
    assert data["span_id"] is not None
    assert data["duration_ms"] >= 0
    os.remove(jsonl_path)
    print("  PASS: Span exported to JSONL and verified")

    # ---- Test 9: Composite exporter ----
    print("\n[9] Composite exporter (fan-out)...")
    mem1 = InMemoryExporter()
    mem2 = InMemoryExporter()
    composite = CompositeExporter([mem1, mem2])
    tracer_comp = Tracer(service_name="composite-test", exporter=composite)

    with tracer_comp.start_span("multi_export") as s:
        s.set_attribute("dest", "both")

    assert len(mem1.spans) == 1, "Exporter 1 should have 1 span"
    assert len(mem2.spans) == 1, "Exporter 2 should have 1 span"
    assert mem1.spans[0].span_id == mem2.spans[0].span_id, "Same span in both exporters"
    print("  PASS: Span exported to both exporters")

    # ---- Test 10: Thread safety ----
    print("\n[10] Thread safety (concurrent spans)...")
    exporter.clear()
    thread_tracer = Tracer(service_name="thread-test", exporter=exporter)
    errors_found: List[str] = []

    def worker(worker_id: int) -> None:
        try:
            with thread_tracer.start_span(f"worker_{worker_id}") as w:
                w.set_attribute("worker.id", worker_id)
                time.sleep(random.uniform(0.01, 0.03))
                with thread_tracer.start_span(f"subtask_{worker_id}") as sub:
                    sub.set_attribute("worker.id", worker_id)
                    time.sleep(random.uniform(0.005, 0.015))
                    # Verify context isolation
                    current = TracingContext.current_span()
                    if current is None or current.span_id != sub.span_id:
                        errors_found.append(f"Worker {worker_id}: context leak detected")
        except Exception as e:
            errors_found.append(f"Worker {worker_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors_found) == 0, f"Thread safety errors: {errors_found}"
    assert len(exporter.spans) == 16, f"Expected 16 spans (8 workers x 2), got {len(exporter.spans)}"
    # Verify each worker's spans are correctly parented
    worker_spans = exporter.get_spans_by_name("worker_0")
    assert len(worker_spans) == 1
    subtask_spans = exporter.get_spans_by_name("subtask_0")
    assert len(subtask_spans) == 1
    assert subtask_spans[0].parent_span_id == worker_spans[0].span_id
    print(f"  PASS: 8 concurrent workers, 16 spans, correct parent-child, no context leaks")

    # ---- Test 11: Serialization round-trip ----
    print("\n[11] Serialization round-trip...")
    exporter.clear()

    with tracer.start_span("serialize_test") as s:
        s.set_attribute("int_val", 42)
        s.set_attribute("str_val", "hello")
        s.set_attribute("float_val", 3.14)
        s.set_attribute("bool_val", True)
        s.add_event("checkpoint", {"step": 1})
        s.add_link("a" * 32, "b" * 16, {"rel": "follows"})
        s.set_status(SpanStatus.OK, "all good")

    d = exporter.spans[0].to_dict()
    assert d["attributes"]["int_val"] == 42
    assert d["attributes"]["str_val"] == "hello"
    assert d["attributes"]["float_val"] == 3.14
    assert d["attributes"]["bool_val"] is True
    assert d["status"] == "OK"
    assert d["status_message"] == "all good"
    assert len(d["events"]) == 1
    assert d["events"][0]["name"] == "checkpoint"
    assert len(d["links"]) == 1
    assert d["links"][0]["trace_id"] == "a" * 32

    j = exporter.spans[0].to_json()
    parsed = json.loads(j)
    assert parsed == d, "JSON round-trip should produce identical dict"
    print("  PASS: Full serialization with attributes, events, links, status")

    # ---- Done ----
    TracingContext.clear()
    print("\n" + "=" * 60)
    print("ALL 11 TESTS PASSED")
    print("=" * 60)
