"""
CQRS (Command Query Responsibility Segregation) Pattern

Separates read and write models, optimizing each independently.
Commands mutate state; Queries read projections built from events.
"""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Domain Events
# ---------------------------------------------------------------------------

class EventType(Enum):
    TASK_CREATED = "task_created"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_PRIORITY_CHANGED = "task_priority_changed"


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: EventType
    aggregate_id: str
    payload: dict
    timestamp: float
    version: int


# ---------------------------------------------------------------------------
# Event Store (write-side persistence)
# ---------------------------------------------------------------------------

class EventStore:
    def __init__(self) -> None:
        self._streams: dict[str, list[Event]] = {}
        self._all_events: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []

    def append(self, event: Event) -> None:
        self._streams.setdefault(event.aggregate_id, []).append(event)
        self._all_events.append(event)
        for sub in self._subscribers:
            sub(event)

    def get_stream(self, aggregate_id: str) -> list[Event]:
        return list(self._streams.get(aggregate_id, []))

    def all_events(self) -> list[Event]:
        return list(self._all_events)

    def subscribe(self, handler: Callable[[Event], None]) -> None:
        self._subscribers.append(handler)


# ---------------------------------------------------------------------------
# Write Model — Aggregate
# ---------------------------------------------------------------------------

class TaskAggregate:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.title: str = ""
        self.assignee: str | None = None
        self.priority: int = 0
        self.completed: bool = False
        self.version: int = 0

    def apply(self, event: Event) -> None:
        if event.event_type == EventType.TASK_CREATED:
            self.title = event.payload["title"]
            self.priority = event.payload.get("priority", 0)
        elif event.event_type == EventType.TASK_ASSIGNED:
            self.assignee = event.payload["assignee"]
        elif event.event_type == EventType.TASK_COMPLETED:
            self.completed = True
        elif event.event_type == EventType.TASK_PRIORITY_CHANGED:
            self.priority = event.payload["priority"]
        self.version = event.version

    @staticmethod
    def load(events: list[Event]) -> TaskAggregate:
        if not events:
            raise ValueError("No events for aggregate")
        agg = TaskAggregate(events[0].aggregate_id)
        for e in events:
            agg.apply(e)
        return agg


# ---------------------------------------------------------------------------
# Command Bus
# ---------------------------------------------------------------------------

@dataclass
class Command:
    name: str
    payload: dict


class CommandValidationError(Exception):
    pass


class CommandBus:
    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store
        self._handlers: dict[str, Callable[[Command], list[Event]]] = {}

    def register(self, command_name: str, handler: Callable[[Command], list[Event]]) -> None:
        self._handlers[command_name] = handler

    def dispatch(self, command: Command) -> list[Event]:
        handler = self._handlers.get(command.name)
        if handler is None:
            raise ValueError(f"No handler for command: {command.name}")
        events = handler(command)
        for event in events:
            self._store.append(event)
        return events


# ---------------------------------------------------------------------------
# Command Handlers (write side)
# ---------------------------------------------------------------------------

class TaskCommandHandlers:
    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store

    def _next_version(self, aggregate_id: str) -> int:
        stream = self._store.get_stream(aggregate_id)
        return len(stream) + 1

    def handle_create_task(self, cmd: Command) -> list[Event]:
        title = cmd.payload.get("title", "").strip()
        if not title:
            raise CommandValidationError("Title is required")
        task_id = cmd.payload.get("task_id") or str(uuid.uuid4())
        if self._store.get_stream(task_id):
            raise CommandValidationError(f"Task {task_id} already exists")
        return [Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.TASK_CREATED,
            aggregate_id=task_id,
            payload={"title": title, "priority": cmd.payload.get("priority", 0)},
            timestamp=time.time(),
            version=1,
        )]

    def handle_assign_task(self, cmd: Command) -> list[Event]:
        task_id = cmd.payload["task_id"]
        agg = TaskAggregate.load(self._store.get_stream(task_id))
        if agg.completed:
            raise CommandValidationError("Cannot assign a completed task")
        assignee = cmd.payload.get("assignee", "").strip()
        if not assignee:
            raise CommandValidationError("Assignee is required")
        return [Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.TASK_ASSIGNED,
            aggregate_id=task_id,
            payload={"assignee": assignee},
            timestamp=time.time(),
            version=self._next_version(task_id),
        )]

    def handle_complete_task(self, cmd: Command) -> list[Event]:
        task_id = cmd.payload["task_id"]
        agg = TaskAggregate.load(self._store.get_stream(task_id))
        if agg.completed:
            raise CommandValidationError("Task already completed")
        return [Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.TASK_COMPLETED,
            aggregate_id=task_id,
            payload={},
            timestamp=time.time(),
            version=self._next_version(task_id),
        )]

    def handle_change_priority(self, cmd: Command) -> list[Event]:
        task_id = cmd.payload["task_id"]
        agg = TaskAggregate.load(self._store.get_stream(task_id))
        if agg.completed:
            raise CommandValidationError("Cannot change priority of completed task")
        priority = cmd.payload["priority"]
        if not isinstance(priority, int) or priority < 0:
            raise CommandValidationError("Priority must be a non-negative integer")
        return [Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.TASK_PRIORITY_CHANGED,
            aggregate_id=task_id,
            payload={"priority": priority},
            timestamp=time.time(),
            version=self._next_version(task_id),
        )]


# ---------------------------------------------------------------------------
# Read Model — Projections (query side, optimized for reads)
# ---------------------------------------------------------------------------

@dataclass
class TaskReadModel:
    task_id: str
    title: str
    assignee: str | None
    priority: int
    completed: bool
    created_at: float
    updated_at: float


@dataclass
class AssigneeWorkload:
    assignee: str
    total: int = 0
    completed: int = 0
    pending: int = 0


class TaskListProjection:
    """Flat denormalized view of all tasks — optimized for listing and filtering."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskReadModel] = {}

    def handle_event(self, event: Event) -> None:
        if event.event_type == EventType.TASK_CREATED:
            self._tasks[event.aggregate_id] = TaskReadModel(
                task_id=event.aggregate_id,
                title=event.payload["title"],
                assignee=None,
                priority=event.payload.get("priority", 0),
                completed=False,
                created_at=event.timestamp,
                updated_at=event.timestamp,
            )
        elif event.event_type == EventType.TASK_ASSIGNED:
            t = self._tasks.get(event.aggregate_id)
            if t:
                t.assignee = event.payload["assignee"]
                t.updated_at = event.timestamp
        elif event.event_type == EventType.TASK_COMPLETED:
            t = self._tasks.get(event.aggregate_id)
            if t:
                t.completed = True
                t.updated_at = event.timestamp
        elif event.event_type == EventType.TASK_PRIORITY_CHANGED:
            t = self._tasks.get(event.aggregate_id)
            if t:
                t.priority = event.payload["priority"]
                t.updated_at = event.timestamp

    # Query methods
    def get_task(self, task_id: str) -> TaskReadModel | None:
        return self._tasks.get(task_id)

    def list_all(self) -> list[TaskReadModel]:
        return list(self._tasks.values())

    def list_pending(self) -> list[TaskReadModel]:
        return [t for t in self._tasks.values() if not t.completed]

    def list_by_assignee(self, assignee: str) -> list[TaskReadModel]:
        return [t for t in self._tasks.values() if t.assignee == assignee]

    def list_by_priority(self, min_priority: int = 0) -> list[TaskReadModel]:
        return sorted(
            [t for t in self._tasks.values() if t.priority >= min_priority],
            key=lambda t: -t.priority,
        )


class WorkloadProjection:
    """Aggregated view of assignee workload — optimized for dashboard queries."""

    def __init__(self) -> None:
        self._assignments: dict[str, dict[str, bool]] = {}  # assignee -> {task_id: completed}

    def handle_event(self, event: Event) -> None:
        if event.event_type == EventType.TASK_ASSIGNED:
            assignee = event.payload["assignee"]
            self._assignments.setdefault(assignee, {})[event.aggregate_id] = False
        elif event.event_type == EventType.TASK_COMPLETED:
            for assignee, tasks in self._assignments.items():
                if event.aggregate_id in tasks:
                    tasks[event.aggregate_id] = True

    def get_workload(self, assignee: str) -> AssigneeWorkload:
        tasks = self._assignments.get(assignee, {})
        completed = sum(1 for done in tasks.values() if done)
        return AssigneeWorkload(
            assignee=assignee,
            total=len(tasks),
            completed=completed,
            pending=len(tasks) - completed,
        )

    def all_workloads(self) -> list[AssigneeWorkload]:
        return [self.get_workload(a) for a in self._assignments]


# ---------------------------------------------------------------------------
# Query Bus
# ---------------------------------------------------------------------------

@dataclass
class Query:
    name: str
    params: dict = field(default_factory=dict)


class QueryBus:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[Query], Any]] = {}

    def register(self, query_name: str, handler: Callable[[Query], Any]) -> None:
        self._handlers[query_name] = handler

    def execute(self, query: Query) -> Any:
        handler = self._handlers.get(query.name)
        if handler is None:
            raise ValueError(f"No handler for query: {query.name}")
        return handler(query)


# ---------------------------------------------------------------------------
# Query Handlers (read side)
# ---------------------------------------------------------------------------

class TaskQueryHandlers:
    def __init__(self, task_projection: TaskListProjection, workload_projection: WorkloadProjection) -> None:
        self._tasks = task_projection
        self._workloads = workload_projection

    def handle_get_task(self, query: Query) -> TaskReadModel | None:
        return self._tasks.get_task(query.params["task_id"])

    def handle_list_all(self, _query: Query) -> list[TaskReadModel]:
        return self._tasks.list_all()

    def handle_list_pending(self, _query: Query) -> list[TaskReadModel]:
        return self._tasks.list_pending()

    def handle_list_by_assignee(self, query: Query) -> list[TaskReadModel]:
        return self._tasks.list_by_assignee(query.params["assignee"])

    def handle_list_by_priority(self, query: Query) -> list[TaskReadModel]:
        return self._tasks.list_by_priority(query.params.get("min_priority", 0))

    def handle_workload(self, query: Query) -> AssigneeWorkload:
        return self._workloads.get_workload(query.params["assignee"])

    def handle_all_workloads(self, _query: Query) -> list[AssigneeWorkload]:
        return self._workloads.all_workloads()


# ---------------------------------------------------------------------------
# Application Wiring
# ---------------------------------------------------------------------------

class CQRSApplication:
    def __init__(self) -> None:
        self.event_store = EventStore()

        # Read-side projections
        self.task_projection = TaskListProjection()
        self.workload_projection = WorkloadProjection()

        # Wire projections to event store
        self.event_store.subscribe(self.task_projection.handle_event)
        self.event_store.subscribe(self.workload_projection.handle_event)

        # Command side
        cmd_handlers = TaskCommandHandlers(self.event_store)
        self.command_bus = CommandBus(self.event_store)
        self.command_bus.register("create_task", cmd_handlers.handle_create_task)
        self.command_bus.register("assign_task", cmd_handlers.handle_assign_task)
        self.command_bus.register("complete_task", cmd_handlers.handle_complete_task)
        self.command_bus.register("change_priority", cmd_handlers.handle_change_priority)

        # Query side
        qry_handlers = TaskQueryHandlers(self.task_projection, self.workload_projection)
        self.query_bus = QueryBus()
        self.query_bus.register("get_task", qry_handlers.handle_get_task)
        self.query_bus.register("list_all", qry_handlers.handle_list_all)
        self.query_bus.register("list_pending", qry_handlers.handle_list_pending)
        self.query_bus.register("list_by_assignee", qry_handlers.handle_list_by_assignee)
        self.query_bus.register("list_by_priority", qry_handlers.handle_list_by_priority)
        self.query_bus.register("workload", qry_handlers.handle_workload)
        self.query_bus.register("all_workloads", qry_handlers.handle_all_workloads)


# ---------------------------------------------------------------------------
# Main — verify correctness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = CQRSApplication()

    # --- Command: create tasks ---
    app.command_bus.dispatch(Command("create_task", {"task_id": "t-1", "title": "Build API", "priority": 3}))
    app.command_bus.dispatch(Command("create_task", {"task_id": "t-2", "title": "Write tests", "priority": 5}))
    app.command_bus.dispatch(Command("create_task", {"task_id": "t-3", "title": "Deploy infra", "priority": 1}))

    # --- Query: list all ---
    all_tasks = app.query_bus.execute(Query("list_all"))
    assert len(all_tasks) == 3, f"Expected 3 tasks, got {len(all_tasks)}"

    # --- Query: by priority ---
    high_priority = app.query_bus.execute(Query("list_by_priority", {"min_priority": 3}))
    assert len(high_priority) == 2, f"Expected 2 high-priority tasks, got {len(high_priority)}"
    assert high_priority[0].title == "Write tests", "Highest priority should be first"

    # --- Command: assign tasks ---
    app.command_bus.dispatch(Command("assign_task", {"task_id": "t-1", "assignee": "alice"}))
    app.command_bus.dispatch(Command("assign_task", {"task_id": "t-2", "assignee": "alice"}))
    app.command_bus.dispatch(Command("assign_task", {"task_id": "t-3", "assignee": "bob"}))

    # --- Query: by assignee ---
    alice_tasks = app.query_bus.execute(Query("list_by_assignee", {"assignee": "alice"}))
    assert len(alice_tasks) == 2, f"Expected 2 tasks for alice, got {len(alice_tasks)}"

    # --- Query: workload ---
    alice_wl = app.query_bus.execute(Query("workload", {"assignee": "alice"}))
    assert alice_wl.total == 2
    assert alice_wl.pending == 2
    assert alice_wl.completed == 0

    # --- Command: complete a task ---
    app.command_bus.dispatch(Command("complete_task", {"task_id": "t-1"}))

    # --- Query: pending ---
    pending = app.query_bus.execute(Query("list_pending"))
    assert len(pending) == 2, f"Expected 2 pending tasks, got {len(pending)}"

    # --- Query: workload updated ---
    alice_wl = app.query_bus.execute(Query("workload", {"assignee": "alice"}))
    assert alice_wl.completed == 1
    assert alice_wl.pending == 1

    # --- Query: get single task ---
    task = app.query_bus.execute(Query("get_task", {"task_id": "t-1"}))
    assert task is not None
    assert task.completed is True
    assert task.assignee == "alice"
    assert task.title == "Build API"

    # --- Command: change priority ---
    app.command_bus.dispatch(Command("change_priority", {"task_id": "t-3", "priority": 10}))
    task3 = app.query_bus.execute(Query("get_task", {"task_id": "t-3"}))
    assert task3.priority == 10

    # --- Query: priority re-sorted ---
    by_prio = app.query_bus.execute(Query("list_by_priority", {"min_priority": 0}))
    assert by_prio[0].task_id == "t-3", "t-3 should be highest priority now"

    # --- Validation: cannot assign completed task ---
    try:
        app.command_bus.dispatch(Command("assign_task", {"task_id": "t-1", "assignee": "charlie"}))
        assert False, "Should have raised CommandValidationError"
    except CommandValidationError:
        pass

    # --- Validation: cannot complete twice ---
    try:
        app.command_bus.dispatch(Command("complete_task", {"task_id": "t-1"}))
        assert False, "Should have raised CommandValidationError"
    except CommandValidationError:
        pass

    # --- Validation: cannot create duplicate ---
    try:
        app.command_bus.dispatch(Command("create_task", {"task_id": "t-1", "title": "Duplicate"}))
        assert False, "Should have raised CommandValidationError"
    except CommandValidationError:
        pass

    # --- Validation: empty title ---
    try:
        app.command_bus.dispatch(Command("create_task", {"title": ""}))
        assert False, "Should have raised CommandValidationError"
    except CommandValidationError:
        pass

    # --- Event store integrity ---
    all_events = app.event_store.all_events()
    assert len(all_events) == 8, f"Expected 8 events, got {len(all_events)}"

    # --- Aggregate rebuild from events ---
    stream = app.event_store.get_stream("t-1")
    rebuilt = TaskAggregate.load(stream)
    assert rebuilt.title == "Build API"
    assert rebuilt.assignee == "alice"
    assert rebuilt.completed is True

    # --- All workloads ---
    workloads = app.query_bus.execute(Query("all_workloads"))
    assert len(workloads) == 2
    names = {w.assignee for w in workloads}
    assert names == {"alice", "bob"}

    print("All assertions passed.")
