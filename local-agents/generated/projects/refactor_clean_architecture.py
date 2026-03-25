"""
Refactor: Spaghetti code into clean architecture (SRP).

Part 1 — The messy 100-line function that does everything.
Part 2 — Clean refactored classes with single responsibilities.
Both produce identical results; assertions at the bottom prove it.
"""

import json
import re
import os
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional


# ============================================================================
# PART 1: THE SPAGHETTI — one giant function does parse, validate, transform, store
# ============================================================================

def process_orders_messy(raw_json: str, storage_dir: str = "/tmp/orders") -> dict:
    """100-line monster: parses JSON, validates fields, transforms data,
    computes summaries, and persists to disk — all in one function."""

    # --- parse ---
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Invalid JSON: {e}"}

    if not isinstance(data, dict) or "orders" not in data:
        return {"ok": False, "error": "Missing 'orders' key"}

    orders = data["orders"]
    if not isinstance(orders, list) or len(orders) == 0:
        return {"ok": False, "error": "Orders must be a non-empty list"}

    validated = []
    errors = []

    for idx, order in enumerate(orders):
        # --- validate each order ---
        if not isinstance(order, dict):
            errors.append(f"Order {idx}: not a dict")
            continue

        oid = order.get("id")
        if not oid or not isinstance(oid, str) or not re.match(r"^ORD-\d{4,}$", oid):
            errors.append(f"Order {idx}: invalid id '{oid}'")
            continue

        customer = order.get("customer", "")
        if not customer or len(customer) < 2 or len(customer) > 120:
            errors.append(f"Order {idx}: invalid customer '{customer}'")
            continue

        email = order.get("email", "")
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            errors.append(f"Order {idx}: invalid email '{email}'")
            continue

        items = order.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            errors.append(f"Order {idx}: no items")
            continue

        valid_items = []
        item_ok = True
        for jdx, item in enumerate(items):
            name = item.get("name", "")
            qty = item.get("qty", 0)
            price = item.get("price", 0)
            if not name or not isinstance(qty, int) or qty < 1 or not isinstance(price, (int, float)) or price <= 0:
                errors.append(f"Order {idx}, item {jdx}: invalid")
                item_ok = False
                break
            valid_items.append({"name": name.strip().title(), "qty": qty, "unit_price": round(float(price), 2)})

        if not item_ok:
            continue

        # --- transform ---
        subtotal = sum(i["unit_price"] * i["qty"] for i in valid_items)
        tax_rate = 0.08
        tax = round(subtotal * tax_rate, 2)
        total = round(subtotal + tax, 2)
        discount = 0.0
        if total > 500:
            discount = round(total * 0.10, 2)
            total = round(total - discount, 2)
        elif total > 200:
            discount = round(total * 0.05, 2)
            total = round(total - discount, 2)

        transformed = {
            "order_id": oid,
            "customer": customer.strip().title(),
            "email": email.strip().lower(),
            "items": valid_items,
            "subtotal": round(subtotal, 2),
            "tax": tax,
            "discount": discount,
            "total": total,
            "status": "confirmed",
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        validated.append(transformed)

    # --- store (simulate) ---
    stored_ids = []
    for vo in validated:
        blob = json.dumps(vo, sort_keys=True)
        checksum = hashlib.sha256(blob.encode()).hexdigest()[:12]
        vo["checksum"] = checksum
        stored_ids.append(vo["order_id"])

    # --- summary ---
    grand_total = round(sum(v["total"] for v in validated), 2)
    summary = {
        "ok": True,
        "processed": len(validated),
        "failed": len(errors),
        "errors": errors,
        "grand_total": grand_total,
        "stored_ids": stored_ids,
        "results": validated,
    }
    return summary


# ============================================================================
# PART 2: CLEAN ARCHITECTURE — separate classes, single responsibility each
# ============================================================================

class ParseError(Exception):
    pass


class ValidationError(Exception):
    def __init__(self, message: str, index: int):
        self.message = message
        self.index = index
        super().__init__(message)


@dataclass
class OrderItem:
    name: str
    qty: int
    unit_price: float


@dataclass
class Order:
    order_id: str
    customer: str
    email: str
    items: list  # list[OrderItem]
    subtotal: float = 0.0
    tax: float = 0.0
    discount: float = 0.0
    total: float = 0.0
    status: str = "confirmed"
    processed_at: str = ""
    checksum: str = ""


# --- Parser: only responsible for deserializing raw input ---

class OrderParser:
    """Parses raw JSON into a list of raw order dicts."""

    def parse(self, raw_json: str) -> list[dict]:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON: {e}")

        if not isinstance(data, dict) or "orders" not in data:
            raise ParseError("Missing 'orders' key")

        orders = data["orders"]
        if not isinstance(orders, list) or len(orders) == 0:
            raise ParseError("Orders must be a non-empty list")

        return orders


# --- Validator: only responsible for checking business rules ---

class OrderValidator:
    """Validates a single raw order dict. Returns cleaned data or raises."""

    ID_PATTERN = re.compile(r"^ORD-\d{4,}$")
    EMAIL_PATTERN = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

    def validate(self, raw: dict, index: int) -> dict:
        if not isinstance(raw, dict):
            raise ValidationError(f"Order {index}: not a dict", index)

        oid = self._require_id(raw, index)
        customer = self._require_customer(raw, index)
        email = self._require_email(raw, index)
        items = self._require_items(raw, index)

        return {"id": oid, "customer": customer, "email": email, "items": items}

    def _require_id(self, raw: dict, idx: int) -> str:
        oid = raw.get("id")
        if not oid or not isinstance(oid, str) or not self.ID_PATTERN.match(oid):
            raise ValidationError(f"Order {idx}: invalid id '{oid}'", idx)
        return oid

    def _require_customer(self, raw: dict, idx: int) -> str:
        customer = raw.get("customer", "")
        if not customer or len(customer) < 2 or len(customer) > 120:
            raise ValidationError(f"Order {idx}: invalid customer '{customer}'", idx)
        return customer

    def _require_email(self, raw: dict, idx: int) -> str:
        email = raw.get("email", "")
        if not self.EMAIL_PATTERN.match(email):
            raise ValidationError(f"Order {idx}: invalid email '{email}'", idx)
        return email

    def _require_items(self, raw: dict, idx: int) -> list[dict]:
        items = raw.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            raise ValidationError(f"Order {idx}: no items", idx)

        validated = []
        for jdx, item in enumerate(items):
            name = item.get("name", "")
            qty = item.get("qty", 0)
            price = item.get("price", 0)
            if (not name
                    or not isinstance(qty, int) or qty < 1
                    or not isinstance(price, (int, float)) or price <= 0):
                raise ValidationError(f"Order {idx}, item {jdx}: invalid", idx)
            validated.append({"name": name, "qty": qty, "price": price})
        return validated


# --- Transformer: only responsible for business calculations ---

class OrderTransformer:
    """Applies pricing rules: tax, discounts, formatting."""

    TAX_RATE = 0.08
    HIGH_DISCOUNT_THRESHOLD = 500
    HIGH_DISCOUNT_RATE = 0.10
    LOW_DISCOUNT_THRESHOLD = 200
    LOW_DISCOUNT_RATE = 0.05

    def transform(self, validated: dict) -> Order:
        items = [
            OrderItem(
                name=i["name"].strip().title(),
                qty=i["qty"],
                unit_price=round(float(i["price"]), 2),
            )
            for i in validated["items"]
        ]

        subtotal = sum(i.unit_price * i.qty for i in items)
        tax = round(subtotal * self.TAX_RATE, 2)
        total = round(subtotal + tax, 2)
        discount = self._compute_discount(total)
        total = round(total - discount, 2)

        return Order(
            order_id=validated["id"],
            customer=validated["customer"].strip().title(),
            email=validated["email"].strip().lower(),
            items=items,
            subtotal=round(subtotal, 2),
            tax=tax,
            discount=discount,
            total=total,
            status="confirmed",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _compute_discount(self, total: float) -> float:
        if total > self.HIGH_DISCOUNT_THRESHOLD:
            return round(total * self.HIGH_DISCOUNT_RATE, 2)
        if total > self.LOW_DISCOUNT_THRESHOLD:
            return round(total * self.LOW_DISCOUNT_RATE, 2)
        return 0.0


# --- Storage: only responsible for persistence concerns ---

class OrderStore:
    """Computes checksum and records an order (in-memory for demo)."""

    def __init__(self):
        self.stored: list[Order] = []

    def save(self, order: Order) -> str:
        blob = json.dumps(self._serializable(order), sort_keys=True)
        order.checksum = hashlib.sha256(blob.encode()).hexdigest()[:12]
        self.stored.append(order)
        return order.order_id

    @staticmethod
    def _serializable(order: Order) -> dict:
        items = [{"name": i.name, "qty": i.qty, "unit_price": i.unit_price} for i in order.items]
        return {
            "order_id": order.order_id,
            "customer": order.customer,
            "email": order.email,
            "items": items,
            "subtotal": order.subtotal,
            "tax": order.tax,
            "discount": order.discount,
            "total": order.total,
            "status": order.status,
            "processed_at": order.processed_at,
        }


# --- Orchestrator: composes the pipeline, delegates to each class ---

class OrderProcessor:
    """Thin orchestrator — no business logic, just wiring."""

    def __init__(self):
        self.parser = OrderParser()
        self.validator = OrderValidator()
        self.transformer = OrderTransformer()
        self.store = OrderStore()

    def process(self, raw_json: str) -> dict:
        try:
            raw_orders = self.parser.parse(raw_json)
        except ParseError as e:
            return {"ok": False, "error": str(e)}

        results = []
        errors = []

        for idx, raw in enumerate(raw_orders):
            try:
                validated = self.validator.validate(raw, idx)
                order = self.transformer.transform(validated)
                self.store.save(order)
                results.append(order)
            except ValidationError as e:
                errors.append(e.message)

        stored_ids = [o.order_id for o in results]
        grand_total = round(sum(o.total for o in results), 2)

        return {
            "ok": True,
            "processed": len(results),
            "failed": len(errors),
            "errors": errors,
            "grand_total": grand_total,
            "stored_ids": stored_ids,
            "results": results,
        }


# ============================================================================
# PART 3: TESTS — both implementations must produce identical outcomes
# ============================================================================

if __name__ == "__main__":

    # --- Test fixtures ---

    GOOD_PAYLOAD = json.dumps({
        "orders": [
            {
                "id": "ORD-1001",
                "customer": "Alice Smith",
                "email": "alice@example.com",
                "items": [
                    {"name": "widget", "qty": 3, "price": 25.00},
                    {"name": "gadget", "qty": 1, "price": 149.99},
                ],
            },
            {
                "id": "ORD-1002",
                "customer": "Bob Jones",
                "email": "bob@example.com",
                "items": [
                    {"name": "thingamajig", "qty": 10, "price": 55.00},
                ],
            },
        ]
    })

    MIXED_PAYLOAD = json.dumps({
        "orders": [
            {
                "id": "ORD-2001",
                "customer": "Carol White",
                "email": "carol@example.com",
                "items": [{"name": "book", "qty": 2, "price": 12.50}],
            },
            {
                "id": "BAD-ID",  # invalid id
                "customer": "Dave",
                "email": "dave@example.com",
                "items": [{"name": "pen", "qty": 1, "price": 3.00}],
            },
            {
                "id": "ORD-2003",
                "customer": "Eve Black",
                "email": "not-an-email",  # invalid email
                "items": [{"name": "notebook", "qty": 1, "price": 8.00}],
            },
            {
                "id": "ORD-2004",
                "customer": "F",  # too short
                "email": "f@example.com",
                "items": [{"name": "eraser", "qty": 1, "price": 1.00}],
            },
        ]
    })

    BIG_ORDER_PAYLOAD = json.dumps({
        "orders": [
            {
                "id": "ORD-3001",
                "customer": "Grace Hopper",
                "email": "grace@navy.mil",
                "items": [
                    {"name": "mainframe part", "qty": 5, "price": 120.00},
                ],
            },
        ]
    })

    # --- Helper to compare both implementations ---

    def compare(messy_result: dict, clean_result: dict, label: str):
        """Compare key fields; timestamps and object types will differ."""
        assert messy_result["ok"] == clean_result["ok"], f"{label}: ok mismatch"
        if not messy_result["ok"]:
            assert messy_result["error"] == clean_result["error"], f"{label}: error mismatch"
            return

        assert messy_result["processed"] == clean_result["processed"], f"{label}: processed count"
        assert messy_result["failed"] == clean_result["failed"], f"{label}: failed count"
        assert messy_result["errors"] == clean_result["errors"], f"{label}: errors list"
        assert messy_result["grand_total"] == clean_result["grand_total"], f"{label}: grand_total"
        assert messy_result["stored_ids"] == clean_result["stored_ids"], f"{label}: stored_ids"

        for m, c in zip(messy_result["results"], clean_result["results"]):
            mo = m if isinstance(m, dict) else m.__dict__
            co = c if isinstance(c, dict) else c.__dict__
            assert mo["order_id"] == co["order_id"], f"{label}: order_id"
            assert mo["customer"] == co["customer"], f"{label}: customer"
            assert mo["email"] == co["email"], f"{label}: email"
            assert mo["subtotal"] == co["subtotal"], f"{label}: subtotal"
            assert mo["tax"] == co["tax"], f"{label}: tax"
            assert mo["discount"] == co["discount"], f"{label}: discount"
            assert mo["total"] == co["total"], f"{label}: total"
            assert mo["status"] == co["status"], f"{label}: status"

    # ---- Run tests ----

    # Test 1: valid orders
    m1 = process_orders_messy(GOOD_PAYLOAD)
    c1 = OrderProcessor().process(GOOD_PAYLOAD)
    compare(m1, c1, "Test 1 — good payload")
    assert m1["processed"] == 2
    assert m1["failed"] == 0
    print("PASS  Test 1: valid orders processed correctly")

    # Test 2: mixed valid/invalid
    m2 = process_orders_messy(MIXED_PAYLOAD)
    c2 = OrderProcessor().process(MIXED_PAYLOAD)
    compare(m2, c2, "Test 2 — mixed payload")
    assert m2["processed"] == 1
    assert m2["failed"] == 3
    assert len(m2["errors"]) == 3
    print("PASS  Test 2: mixed valid/invalid handled identically")

    # Test 3: high-value discount (>500 => 10%)
    m3 = process_orders_messy(BIG_ORDER_PAYLOAD)
    c3 = OrderProcessor().process(BIG_ORDER_PAYLOAD)
    compare(m3, c3, "Test 3 — big order")
    assert m3["results"][0]["discount"] > 0, "Expected discount for large order"
    subtotal = 5 * 120.00
    expected_tax = round(subtotal * 0.08, 2)
    pre_discount = round(subtotal + expected_tax, 2)
    expected_discount = round(pre_discount * 0.10, 2)
    expected_total = round(pre_discount - expected_discount, 2)
    assert m3["results"][0]["total"] == expected_total
    print("PASS  Test 3: high-value discount applied correctly")

    # Test 4: invalid JSON
    m4 = process_orders_messy("{bad json")
    c4 = OrderProcessor().process("{bad json")
    assert m4["ok"] is False
    assert c4["ok"] is False
    print("PASS  Test 4: invalid JSON rejected")

    # Test 5: missing orders key
    m5 = process_orders_messy('{"data": []}')
    c5 = OrderProcessor().process('{"data": []}')
    assert m5["ok"] is False and "Missing" in m5["error"]
    assert c5["ok"] is False and "Missing" in c5["error"]
    print("PASS  Test 5: missing 'orders' key rejected")

    # Test 6: empty orders list
    m6 = process_orders_messy('{"orders": []}')
    c6 = OrderProcessor().process('{"orders": []}')
    assert m6["ok"] is False
    assert c6["ok"] is False
    print("PASS  Test 6: empty orders list rejected")

    # Test 7: order with no items
    no_items = json.dumps({"orders": [{"id": "ORD-9999", "customer": "Test User", "email": "t@t.com", "items": []}]})
    m7 = process_orders_messy(no_items)
    c7 = OrderProcessor().process(no_items)
    compare(m7, c7, "Test 7 — no items")
    assert m7["processed"] == 0
    assert m7["failed"] == 1
    print("PASS  Test 7: order with empty items rejected")

    # Test 8: low-value order (no discount, total <= 200)
    small = json.dumps({"orders": [{"id": "ORD-8001", "customer": "Tiny Tim", "email": "tim@t.com",
                                     "items": [{"name": "pencil", "qty": 1, "price": 2.50}]}]})
    m8 = process_orders_messy(small)
    c8 = OrderProcessor().process(small)
    compare(m8, c8, "Test 8 — small order")
    assert m8["results"][0]["discount"] == 0.0
    print("PASS  Test 8: no discount for small order")

    # Test 9: mid-value discount (200 < total <= 500 => 5%)
    mid = json.dumps({"orders": [{"id": "ORD-8002", "customer": "Mid Mike", "email": "mike@m.com",
                                   "items": [{"name": "chair", "qty": 2, "price": 110.00}]}]})
    m9 = process_orders_messy(mid)
    c9 = OrderProcessor().process(mid)
    compare(m9, c9, "Test 9 — mid order")
    assert m9["results"][0]["discount"] > 0
    mid_sub = 2 * 110.00
    mid_tax = round(mid_sub * 0.08, 2)
    mid_pre = round(mid_sub + mid_tax, 2)
    assert m9["results"][0]["discount"] == round(mid_pre * 0.05, 2)
    print("PASS  Test 9: 5% discount for mid-value order")

    # Test 10: checksum is stable and non-empty
    assert m1["results"][0].get("checksum")
    assert len(m1["results"][0]["checksum"]) == 12
    print("PASS  Test 10: checksum present and correct length")

    # Test 11: formatting — names title-cased, emails lowercased
    weird = json.dumps({"orders": [{"id": "ORD-7001", "customer": "  jaNe dOE  ",
                                     "email": "  JANE@Example.COM  ",
                                     "items": [{"name": "  RUBBER duck  ", "qty": 1, "price": 5.00}]}]})
    m11 = process_orders_messy(weird)
    c11 = OrderProcessor().process(weird)
    compare(m11, c11, "Test 11 — formatting")
    assert m11["results"][0]["customer"] == "Jane Doe"
    assert m11["results"][0]["email"] == "jane@example.com"
    assert m11["results"][0]["items"][0]["name"] == "Rubber Duck"
    print("PASS  Test 11: names title-cased, emails lowercased")

    # Test 12: item with zero qty is rejected
    zero_qty = json.dumps({"orders": [{"id": "ORD-6001", "customer": "Zero Zoe", "email": "z@z.com",
                                        "items": [{"name": "thing", "qty": 0, "price": 10.00}]}]})
    m12 = process_orders_messy(zero_qty)
    c12 = OrderProcessor().process(zero_qty)
    compare(m12, c12, "Test 12 — zero qty")
    assert m12["processed"] == 0
    print("PASS  Test 12: zero-quantity item rejected")

    print("\n--- ALL 12 TESTS PASSED ---")
