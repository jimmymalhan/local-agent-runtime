"""
CQRS Event-Sourced Order Management System

Components:
- Event Store: append-only log of domain events with optimistic concurrency
- Command Bus: dispatches commands to handlers that produce events
- Query Bus: dispatches queries against denormalised read models
- Projector: subscribes to events and maintains read models
- Order Aggregate: event-sourced state reconstruction + domain rules
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable


# ============================================================================
# Domain Events
# ============================================================================

class EventType(Enum):
    ORDER_CREATED = auto()
    ITEM_ADDED = auto()
    ITEM_REMOVED = auto()
    ORDER_CONFIRMED = auto()
    ORDER_SHIPPED = auto()
    ORDER_CANCELLED = auto()


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    event_type: EventType
    aggregate_id: str
    timestamp: datetime
    version: int
    data: dict


def _make_event(event_type: EventType, aggregate_id: str, version: int, data: dict) -> DomainEvent:
    return DomainEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        aggregate_id=aggregate_id,
        timestamp=datetime.now(timezone.utc),
        version=version,
        data=data,
    )


# ============================================================================
# Event Store (append-only, optimistic concurrency, pub/sub)
# ============================================================================

class ConcurrencyError(Exception):
    pass


class EventStore:
    def __init__(self) -> None:
        self._streams: dict[str, list[DomainEvent]] = {}
        self._global_log: list[DomainEvent] = []
        self._subscribers: list[Callable[[DomainEvent], None]] = []

    def append(self, events: list[DomainEvent], expected_version: int) -> None:
        if not events:
            return
        agg_id = events[0].aggregate_id
        stream = self._streams.get(agg_id, [])
        current_version = stream[-1].version if stream else 0
        if current_version != expected_version:
            raise ConcurrencyError(
                f"Expected version {expected_version}, stream at {current_version}"
            )
        for evt in events:
            stream.append(evt)
            self._global_log.append(evt)
        self._streams[agg_id] = stream
        for evt in events:
            for sub in self._subscribers:
                sub(evt)

    def load_stream(self, aggregate_id: str) -> list[DomainEvent]:
        return list(self._streams.get(aggregate_id, []))

    def subscribe(self, callback: Callable[[DomainEvent], None]) -> None:
        self._subscribers.append(callback)

    @property
    def global_log(self) -> list[DomainEvent]:
        return list(self._global_log)


# ============================================================================
# Order Aggregate (event-sourced)
# ============================================================================

class OrderStatus(Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class DomainError(Exception):
    pass


class OrderAggregate:
    def __init__(self) -> None:
        self.id: str | None = None
        self.customer_id: str | None = None
        self.status: OrderStatus = OrderStatus.DRAFT
        self.items: dict[str, dict] = {}
        self.version: int = 0
        self._pending: list[DomainEvent] = []

    # -- Reconstitution from events ------------------------------------------

    @classmethod
    def from_events(cls, events: list[DomainEvent]) -> OrderAggregate:
        agg = cls()
        for evt in events:
            agg._apply(evt)
        return agg

    def _apply(self, event: DomainEvent) -> None:
        applier = self._APPLIERS.get(event.event_type)
        if applier is None:
            raise ValueError(f"No applier for {event.event_type}")
        applier(self, event)
        self.version = event.version

    def _on_created(self, evt: DomainEvent) -> None:
        self.id = evt.aggregate_id
        self.customer_id = evt.data["customer_id"]
        self.status = OrderStatus.DRAFT

    def _on_item_added(self, evt: DomainEvent) -> None:
        sku = evt.data["sku"]
        if sku in self.items:
            self.items[sku]["qty"] += evt.data["qty"]
        else:
            self.items[sku] = {
                "name": evt.data["name"],
                "qty": evt.data["qty"],
                "unit_price": evt.data["unit_price"],
            }

    def _on_item_removed(self, evt: DomainEvent) -> None:
        self.items.pop(evt.data["sku"], None)

    def _on_confirmed(self, _evt: DomainEvent) -> None:
        self.status = OrderStatus.CONFIRMED

    def _on_shipped(self, _evt: DomainEvent) -> None:
        self.status = OrderStatus.SHIPPED

    def _on_cancelled(self, _evt: DomainEvent) -> None:
        self.status = OrderStatus.CANCELLED

    _APPLIERS: dict[EventType, Callable[["OrderAggregate", DomainEvent], None]] = {
        EventType.ORDER_CREATED: _on_created,
        EventType.ITEM_ADDED: _on_item_added,
        EventType.ITEM_REMOVED: _on_item_removed,
        EventType.ORDER_CONFIRMED: _on_confirmed,
        EventType.ORDER_SHIPPED: _on_shipped,
        EventType.ORDER_CANCELLED: _on_cancelled,
    }

    # -- Command methods (produce pending events) ----------------------------

    def _emit(self, event_type: EventType, data: dict) -> None:
        assert self.id is not None
        next_ver = self.version + len(self._pending) + 1
        evt = _make_event(event_type, self.id, next_ver, data)
        self._pending.append(evt)
        self._apply(evt)

    @classmethod
    def create(cls, order_id: str, customer_id: str) -> OrderAggregate:
        agg = cls()
        agg.id = order_id
        evt = _make_event(EventType.ORDER_CREATED, order_id, 1, {"customer_id": customer_id})
        agg._pending.append(evt)
        agg._apply(evt)
        return agg

    def add_item(self, sku: str, name: str, qty: int, unit_price: float) -> None:
        if self.status != OrderStatus.DRAFT:
            raise DomainError("Can only add items to draft orders")
        if qty <= 0:
            raise DomainError("Quantity must be positive")
        self._emit(EventType.ITEM_ADDED, {"sku": sku, "name": name, "qty": qty, "unit_price": unit_price})

    def remove_item(self, sku: str) -> None:
        if self.status != OrderStatus.DRAFT:
            raise DomainError("Can only remove items from draft orders")
        if sku not in self.items:
            raise DomainError(f"Item {sku} not in order")
        self._emit(EventType.ITEM_REMOVED, {"sku": sku})

    def confirm(self) -> None:
        if self.status != OrderStatus.DRAFT:
            raise DomainError("Only draft orders can be confirmed")
        if not self.items:
            raise DomainError("Cannot confirm an empty order")
        self._emit(EventType.ORDER_CONFIRMED, {})

    def ship(self) -> None:
        if self.status != OrderStatus.CONFIRMED:
            raise DomainError("Only confirmed orders can be shipped")
        self._emit(EventType.ORDER_SHIPPED, {})

    def cancel(self) -> None:
        if self.status in (OrderStatus.SHIPPED, OrderStatus.CANCELLED):
            raise DomainError(f"Cannot cancel order in {self.status.value} state")
        self._emit(EventType.ORDER_CANCELLED, {})

    def collect_pending(self) -> tuple[list[DomainEvent], int]:
        expected = self.version - len(self._pending)
        events = list(self._pending)
        self._pending.clear()
        return events, expected

    @property
    def total(self) -> float:
        return sum(it["qty"] * it["unit_price"] for it in self.items.values())


# ============================================================================
# Commands & Command Bus
# ============================================================================

@dataclass(frozen=True)
class CreateOrder:
    order_id: str
    customer_id: str

@dataclass(frozen=True)
class AddItem:
    order_id: str
    sku: str
    name: str
    qty: int
    unit_price: float

@dataclass(frozen=True)
class RemoveItem:
    order_id: str
    sku: str

@dataclass(frozen=True)
class ConfirmOrder:
    order_id: str

@dataclass(frozen=True)
class ShipOrder:
    order_id: str

@dataclass(frozen=True)
class CancelOrder:
    order_id: str


class CommandBus:
    def __init__(self) -> None:
        self._handlers: dict[type, Callable[[Any], None]] = {}

    def register(self, command_type: type, handler: Callable[[Any], None]) -> None:
        self._handlers[command_type] = handler

    def dispatch(self, command: Any) -> None:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise ValueError(f"No handler registered for {type(command).__name__}")
        handler(command)


class OrderCommandHandler:
    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store

    def _load(self, order_id: str) -> OrderAggregate:
        events = self._store.load_stream(order_id)
        if not events:
            raise DomainError(f"Order {order_id} not found")
        return OrderAggregate.from_events(events)

    def _save(self, aggregate: OrderAggregate) -> None:
        events, expected = aggregate.collect_pending()
        self._store.append(events, expected)

    def handle_create(self, cmd: CreateOrder) -> None:
        if self._store.load_stream(cmd.order_id):
            raise DomainError(f"Order {cmd.order_id} already exists")
        agg = OrderAggregate.create(cmd.order_id, cmd.customer_id)
        self._save(agg)

    def handle_add_item(self, cmd: AddItem) -> None:
        agg = self._load(cmd.order_id)
        agg.add_item(cmd.sku, cmd.name, cmd.qty, cmd.unit_price)
        self._save(agg)

    def handle_remove_item(self, cmd: RemoveItem) -> None:
        agg = self._load(cmd.order_id)
        agg.remove_item(cmd.sku)
        self._save(agg)

    def handle_confirm(self, cmd: ConfirmOrder) -> None:
        agg = self._load(cmd.order_id)
        agg.confirm()
        self._save(agg)

    def handle_ship(self, cmd: ShipOrder) -> None:
        agg = self._load(cmd.order_id)
        agg.ship()
        self._save(agg)

    def handle_cancel(self, cmd: CancelOrder) -> None:
        agg = self._load(cmd.order_id)
        agg.cancel()
        self._save(agg)


# ============================================================================
# Read Models & Projector
# ============================================================================

@dataclass
class OrderSummaryRM:
    order_id: str
    customer_id: str
    status: str
    item_count: int
    total: float
    last_updated: datetime


@dataclass
class CustomerOrdersRM:
    customer_id: str
    order_ids: list[str] = field(default_factory=list)
    total_spent: float = 0.0


class Projector:
    def __init__(self) -> None:
        self.order_summaries: dict[str, OrderSummaryRM] = {}
        self.customer_orders: dict[str, CustomerOrdersRM] = {}
        self._items_cache: dict[str, dict[str, dict]] = {}

    def handle_event(self, event: DomainEvent) -> None:
        dispatch = {
            EventType.ORDER_CREATED: self._on_created,
            EventType.ITEM_ADDED: self._on_item_added,
            EventType.ITEM_REMOVED: self._on_item_removed,
            EventType.ORDER_CONFIRMED: self._on_status,
            EventType.ORDER_SHIPPED: self._on_status,
            EventType.ORDER_CANCELLED: self._on_status,
        }
        handler = dispatch.get(event.event_type)
        if handler:
            handler(event)

    def _on_created(self, evt: DomainEvent) -> None:
        cid = evt.data["customer_id"]
        self.order_summaries[evt.aggregate_id] = OrderSummaryRM(
            order_id=evt.aggregate_id, customer_id=cid,
            status="draft", item_count=0, total=0.0, last_updated=evt.timestamp,
        )
        self._items_cache[evt.aggregate_id] = {}
        if cid not in self.customer_orders:
            self.customer_orders[cid] = CustomerOrdersRM(customer_id=cid)
        self.customer_orders[cid].order_ids.append(evt.aggregate_id)

    def _recalc(self, oid: str) -> tuple[int, float]:
        items = self._items_cache.get(oid, {})
        count = sum(v["qty"] for v in items.values())
        total = sum(v["qty"] * v["unit_price"] for v in items.values())
        return count, total

    def _on_item_added(self, evt: DomainEvent) -> None:
        oid, sku = evt.aggregate_id, evt.data["sku"]
        cache = self._items_cache.setdefault(oid, {})
        if sku in cache:
            cache[sku]["qty"] += evt.data["qty"]
        else:
            cache[sku] = {"qty": evt.data["qty"], "unit_price": evt.data["unit_price"]}
        s = self.order_summaries[oid]
        s.item_count, s.total = self._recalc(oid)
        s.last_updated = evt.timestamp

    def _on_item_removed(self, evt: DomainEvent) -> None:
        oid = evt.aggregate_id
        self._items_cache.get(oid, {}).pop(evt.data["sku"], None)
        s = self.order_summaries[oid]
        s.item_count, s.total = self._recalc(oid)
        s.last_updated = evt.timestamp

    def _on_status(self, evt: DomainEvent) -> None:
        status_map = {
            EventType.ORDER_CONFIRMED: "confirmed",
            EventType.ORDER_SHIPPED: "shipped",
            EventType.ORDER_CANCELLED: "cancelled",
        }
        s = self.order_summaries[evt.aggregate_id]
        s.status = status_map[evt.event_type]
        s.last_updated = evt.timestamp
        if evt.event_type == EventType.ORDER_CONFIRMED:
            cid = s.customer_id
            if cid in self.customer_orders:
                self.customer_orders[cid].total_spent += s.total


# ============================================================================
# Queries & Query Bus
# ============================================================================

@dataclass(frozen=True)
class GetOrderSummary:
    order_id: str

@dataclass(frozen=True)
class GetCustomerOrders:
    customer_id: str

@dataclass(frozen=True)
class GetAllOrders:
    pass


class QueryBus:
    def __init__(self) -> None:
        self._handlers: dict[type, Callable[[Any], Any]] = {}

    def register(self, query_type: type, handler: Callable[[Any], Any]) -> None:
        self._handlers[query_type] = handler

    def dispatch(self, query: Any) -> Any:
        handler = self._handlers.get(type(query))
        if handler is None:
            raise ValueError(f"No handler registered for {type(query).__name__}")
        return handler(query)


class OrderQueryHandler:
    def __init__(self, projector: Projector) -> None:
        self._p = projector

    def handle_get_summary(self, q: GetOrderSummary) -> OrderSummaryRM | None:
        return self._p.order_summaries.get(q.order_id)

    def handle_get_customer_orders(self, q: GetCustomerOrders) -> CustomerOrdersRM | None:
        return self._p.customer_orders.get(q.customer_id)

    def handle_get_all(self, _q: GetAllOrders) -> list[OrderSummaryRM]:
        return list(self._p.order_summaries.values())


# ============================================================================
# Wiring
# ============================================================================

def build_system() -> tuple[CommandBus, QueryBus, EventStore, Projector]:
    store = EventStore()
    projector = Projector()
    store.subscribe(projector.handle_event)

    cmd_h = OrderCommandHandler(store)
    cmd_bus = CommandBus()
    cmd_bus.register(CreateOrder, cmd_h.handle_create)
    cmd_bus.register(AddItem, cmd_h.handle_add_item)
    cmd_bus.register(RemoveItem, cmd_h.handle_remove_item)
    cmd_bus.register(ConfirmOrder, cmd_h.handle_confirm)
    cmd_bus.register(ShipOrder, cmd_h.handle_ship)
    cmd_bus.register(CancelOrder, cmd_h.handle_cancel)

    qry_h = OrderQueryHandler(projector)
    qry_bus = QueryBus()
    qry_bus.register(GetOrderSummary, qry_h.handle_get_summary)
    qry_bus.register(GetCustomerOrders, qry_h.handle_get_customer_orders)
    qry_bus.register(GetAllOrders, qry_h.handle_get_all)

    return cmd_bus, qry_bus, store, projector


# ============================================================================
# Main — end-to-end assertions
# ============================================================================

if __name__ == "__main__":
    cmd_bus, qry_bus, store, projector = build_system()

    oid1 = "order-001"
    oid2 = "order-002"
    cid = "customer-42"

    # 1. Create orders
    cmd_bus.dispatch(CreateOrder(order_id=oid1, customer_id=cid))
    cmd_bus.dispatch(CreateOrder(order_id=oid2, customer_id=cid))

    s1 = qry_bus.dispatch(GetOrderSummary(order_id=oid1))
    assert s1 is not None
    assert s1.status == "draft"
    assert s1.item_count == 0
    assert s1.total == 0.0
    print("[PASS] 1. Orders created in draft status")

    # 2. Add items (including duplicate SKU to test qty accumulation)
    cmd_bus.dispatch(AddItem(order_id=oid1, sku="WIDGET-A", name="Widget A", qty=3, unit_price=10.0))
    cmd_bus.dispatch(AddItem(order_id=oid1, sku="GADGET-B", name="Gadget B", qty=1, unit_price=25.50))
    cmd_bus.dispatch(AddItem(order_id=oid1, sku="WIDGET-A", name="Widget A", qty=2, unit_price=10.0))

    s1 = qry_bus.dispatch(GetOrderSummary(order_id=oid1))
    assert s1.item_count == 6  # 5 widgets + 1 gadget
    assert s1.total == 5 * 10.0 + 1 * 25.50  # 75.50
    print(f"[PASS] 2. Items added — count={s1.item_count}, total=${s1.total:.2f}")

    # 3. Remove item
    cmd_bus.dispatch(RemoveItem(order_id=oid1, sku="GADGET-B"))
    s1 = qry_bus.dispatch(GetOrderSummary(order_id=oid1))
    assert s1.item_count == 5
    assert s1.total == 50.0
    print("[PASS] 3. Item removed")

    # 4. Confirm order
    cmd_bus.dispatch(ConfirmOrder(order_id=oid1))
    s1 = qry_bus.dispatch(GetOrderSummary(order_id=oid1))
    assert s1.status == "confirmed"
    cust = qry_bus.dispatch(GetCustomerOrders(customer_id=cid))
    assert cust is not None
    assert len(cust.order_ids) == 2
    assert cust.total_spent == 50.0
    print(f"[PASS] 4. Order confirmed — customer spent=${cust.total_spent:.2f}")

    # 5. Ship order
    cmd_bus.dispatch(ShipOrder(order_id=oid1))
    s1 = qry_bus.dispatch(GetOrderSummary(order_id=oid1))
    assert s1.status == "shipped"
    print("[PASS] 5. Order shipped")

    # 6. Cancel a draft order
    cmd_bus.dispatch(AddItem(order_id=oid2, sku="THING-C", name="Thing C", qty=1, unit_price=9.99))
    cmd_bus.dispatch(CancelOrder(order_id=oid2))
    s2 = qry_bus.dispatch(GetOrderSummary(order_id=oid2))
    assert s2.status == "cancelled"
    print("[PASS] 6. Draft order cancelled")

    # 7. Domain rule enforcement
    domain_errors = 0
    cases = [
        lambda: cmd_bus.dispatch(AddItem(oid1, "X", "X", 1, 1.0)),      # shipped — no add
        lambda: cmd_bus.dispatch(ConfirmOrder(oid1)),                     # shipped — no confirm
        lambda: cmd_bus.dispatch(CancelOrder(oid1)),                      # shipped — no cancel
        lambda: cmd_bus.dispatch(ShipOrder(oid2)),                        # cancelled — no ship
        lambda: cmd_bus.dispatch(CreateOrder(oid1, "x")),                 # duplicate id
        lambda: cmd_bus.dispatch(AddItem(oid1, "X", "X", -1, 1.0)),      # negative qty
        lambda: cmd_bus.dispatch(RemoveItem(oid1, "NONEXISTENT")),        # shipped — no remove
    ]
    for case in cases:
        try:
            case()
            assert False, "Should have raised DomainError"
        except DomainError:
            domain_errors += 1
    assert domain_errors == len(cases)
    print(f"[PASS] 7. All {domain_errors} domain violations caught")

    # 8. Event stream integrity
    stream1 = store.load_stream(oid1)
    # created + 3 item_added + item_removed + confirmed + shipped = 7
    assert len(stream1) == 7
    assert stream1[0].event_type == EventType.ORDER_CREATED
    assert stream1[-1].event_type == EventType.ORDER_SHIPPED
    for i, evt in enumerate(stream1):
        assert evt.version == i + 1
    print(f"[PASS] 8. Event stream: {len(stream1)} events, versions sequential")

    # 9. Global log
    gl = store.global_log
    # order-001: 7 events, order-002: 3 events (created, item_added, cancelled)
    assert len(gl) == 10
    print(f"[PASS] 9. Global log: {len(gl)} events")

    # 10. Aggregate reconstitution from events
    rebuilt = OrderAggregate.from_events(store.load_stream(oid1))
    assert rebuilt.id == oid1
    assert rebuilt.status == OrderStatus.SHIPPED
    assert rebuilt.customer_id == cid
    assert len(rebuilt.items) == 1
    assert rebuilt.items["WIDGET-A"]["qty"] == 5
    assert rebuilt.total == 50.0
    assert rebuilt.version == 7
    print("[PASS] 10. Aggregate reconstituted from event stream")

    # 11. GetAllOrders query
    all_orders = qry_bus.dispatch(GetAllOrders())
    assert len(all_orders) == 2
    statuses = {o.order_id: o.status for o in all_orders}
    assert statuses[oid1] == "shipped"
    assert statuses[oid2] == "cancelled"
    print("[PASS] 11. GetAllOrders returns correct statuses")

    # 12. Optimistic concurrency violation
    try:
        store.append([_make_event(EventType.ORDER_CONFIRMED, oid1, 99, {})], expected_version=0)
        assert False, "Should have raised ConcurrencyError"
    except ConcurrencyError:
        pass
    print("[PASS] 12. Optimistic concurrency violation detected")

    # 13. Full projector rebuild from global log
    fresh = Projector()
    for evt in store.global_log:
        fresh.handle_event(evt)
    assert fresh.order_summaries[oid1].status == "shipped"
    assert fresh.order_summaries[oid1].total == 50.0
    assert fresh.order_summaries[oid2].status == "cancelled"
    assert fresh.customer_orders[cid].total_spent == 50.0
    print("[PASS] 13. Projector rebuilt from global log matches original")

    # 14. Event immutability
    evt = store.load_stream(oid1)[0]
    try:
        evt.version = 999
        assert False, "DomainEvent should be frozen"
    except AttributeError:
        pass
    print("[PASS] 14. Events are immutable (frozen dataclass)")

    # 15. CommandBus rejects unknown commands
    try:
        cmd_bus.dispatch("not a command")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "No handler" in str(e)
    print("[PASS] 15. CommandBus rejects unknown commands")

    # 16. QueryBus rejects unknown queries
    try:
        qry_bus.dispatch(42)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "No handler" in str(e)
    print("[PASS] 16. QueryBus rejects unknown queries")

    # 17. Query for nonexistent order returns None
    assert qry_bus.dispatch(GetOrderSummary(order_id="nope")) is None
    print("[PASS] 17. Query for nonexistent order returns None")

    # 18. Confirm empty order is rejected
    cmd_bus.dispatch(CreateOrder(order_id="order-empty", customer_id="c-1"))
    try:
        cmd_bus.dispatch(ConfirmOrder(order_id="order-empty"))
        assert False, "Should reject empty order confirmation"
    except DomainError as e:
        assert "empty" in str(e).lower()
    print("[PASS] 18. Cannot confirm empty order")

    # 19. Multiple subscribers
    received: list[DomainEvent] = []
    store.subscribe(lambda e: received.append(e))
    cmd_bus.dispatch(CreateOrder(order_id="order-sub", customer_id="c-sub"))
    assert len(received) == 1
    assert received[0].event_type == EventType.ORDER_CREATED
    print("[PASS] 19. Multiple event store subscribers work")

    # 20. Full lifecycle: create -> add -> confirm -> ship
    lid = "order-lifecycle"
    cmd_bus.dispatch(CreateOrder(order_id=lid, customer_id="c-life"))
    cmd_bus.dispatch(AddItem(order_id=lid, sku="LC-1", name="Lifecycle Item", qty=2, unit_price=15.0))
    cmd_bus.dispatch(ConfirmOrder(order_id=lid))
    cmd_bus.dispatch(ShipOrder(order_id=lid))
    ls = qry_bus.dispatch(GetOrderSummary(order_id=lid))
    assert ls.status == "shipped"
    assert ls.total == 30.0
    assert ls.item_count == 2
    stream = store.load_stream(lid)
    assert len(stream) == 4
    assert [e.event_type for e in stream] == [
        EventType.ORDER_CREATED, EventType.ITEM_ADDED,
        EventType.ORDER_CONFIRMED, EventType.ORDER_SHIPPED,
    ]
    print("[PASS] 20. Full order lifecycle verified")

    print("\n=== ALL 20 CHECKS PASSED ===")
