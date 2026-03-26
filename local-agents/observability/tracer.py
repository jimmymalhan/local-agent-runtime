"""
tracer.py — Lightweight agent observability. No external services needed.

Emits spans to local JSONL files. Dashboard reads for: loop rate, tool error rate,
cost per task, convergence time. OpenTelemetry-compatible schema.

Usage:
    from observability.tracer import trace_task, traced

    @traced("my_agent")
    def run(task): ...

    # Or manual:
    with trace_task("executor", task) as span:
        result = do_work()
        span.set_quality(result["quality"])
"""
import time, json, uuid, functools
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

TRACES_FILE = Path("local-agents/reports/traces.jsonl")

class Span:
    def __init__(self, agent: str, task: dict):
        self.trace_id = str(uuid.uuid4())[:12]
        self.agent = agent
        self.task_id = task.get("id", "unknown")
        self.task_type = task.get("category", "unknown")
        self.task_title = task.get("title", "")[:80]
        self.start_time = time.time()
        self.tool_calls = []
        self.events = []
        self.quality = 0
        self.tokens_used = 0
        self.error = None
        self.status = "running"

    def add_event(self, name: str, data: dict = None):
        self.events.append({"name": name, "t": time.time() - self.start_time, "data": data or {}})

    def add_tool_call(self, tool: str, success: bool, latency_ms: int = 0):
        self.tool_calls.append({"tool": tool, "ok": success, "ms": latency_ms})

    def set_quality(self, quality: int):
        self.quality = quality

    def set_tokens(self, tokens: int):
        self.tokens_used = tokens

    def finish(self, status: str = "ok", error: str = None):
        duration_ms = int((time.time() - self.start_time) * 1000)
        self.status = status
        self.error = error
        record = {
            "ts": datetime.utcnow().isoformat(),
            "trace_id": self.trace_id,
            "agent": self.agent,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_title": self.task_title,
            "status": status,
            "duration_ms": duration_ms,
            "quality": self.quality,
            "tokens": self.tokens_used,
            "tool_calls": self.tool_calls,
            "tool_error_count": sum(1 for t in self.tool_calls if not t["ok"]),
            "events": self.events,
            "error": error,
        }
        TRACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACES_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        return record

@contextmanager
def trace_task(agent: str, task: dict):
    span = Span(agent, task)
    try:
        yield span
        span.finish("ok")
    except Exception as e:
        span.finish("error", str(e))
        raise

def traced(agent_name: str):
    """Decorator: @traced('executor') wraps run() with automatic tracing"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(task: dict, *args, **kwargs):
            with trace_task(agent_name, task) as span:
                result = func(task, *args, **kwargs)
                if isinstance(result, dict):
                    span.set_quality(result.get("quality", 0))
                    span.set_tokens(result.get("tokens_used", 0))
                return result
        return wrapper
    return decorator
