"""
Refactor: Eliminate Deep Nesting

Before: process_orders() has 5 levels of nesting (if/for/try/if/if).
After:  Refactored using early returns, guard clauses, and extracted helpers.
        Maximum nesting depth: 2.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class Item:
    name: str
    price: float
    quantity: int
    taxable: bool = True


@dataclass
class Order:
    order_id: str
    items: list
    customer_tier: str = "standard"  # "standard", "premium", "vip"
    currency: str = "USD"
    is_valid: bool = True


@dataclass
class OrderResult:
    order_id: str
    total: float
    discount: float
    tax: float
    final_total: float
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# BEFORE — 5 levels of nesting
# ---------------------------------------------------------------------------

def process_orders_before(orders, tax_rate=0.08):
    """Original deeply-nested version (5 levels)."""
    results = []
    errors = []
    if orders is not None:                                          # level 1
        for order in orders:                                        # level 2
            try:                                                    # level 3
                if order.is_valid:                                  # level 4
                    total = 0.0
                    tax = 0.0
                    for item in order.items:                        # level 5
                        if item.quantity > 0 and item.price > 0:
                            subtotal = item.price * item.quantity
                            total += subtotal
                            if item.taxable:
                                tax += subtotal * tax_rate
                    if total > 0:
                        if order.customer_tier == "vip":
                            discount = total * 0.20
                        elif order.customer_tier == "premium":
                            discount = total * 0.10
                        else:
                            discount = 0.0
                        final = total - discount + tax
                        results.append(OrderResult(
                            order_id=order.order_id,
                            total=round(total, 2),
                            discount=round(discount, 2),
                            tax=round(tax, 2),
                            final_total=round(final, 2),
                        ))
                    else:
                        errors.append(f"{order.order_id}: empty total")
                else:
                    errors.append(f"{order.order_id}: invalid order")
            except Exception as e:
                errors.append(f"{order.order_id}: {e}")
    return results, errors


# ---------------------------------------------------------------------------
# AFTER — max 2 levels of nesting, using guard clauses + helpers
# ---------------------------------------------------------------------------

def _compute_item_subtotal(item: Item) -> Optional[float]:
    """Return subtotal for a single item, or None if the item is skipped."""
    if item.quantity <= 0 or item.price <= 0:
        return None
    return item.price * item.quantity


def _compute_item_tax(item: Item, subtotal: float, tax_rate: float) -> float:
    """Return the tax amount for a single item."""
    if not item.taxable:
        return 0.0
    return subtotal * tax_rate


def _compute_totals(items: list, tax_rate: float) -> tuple:
    """Sum up total and tax across all valid items."""
    total = 0.0
    tax = 0.0
    for item in items:
        subtotal = _compute_item_subtotal(item)
        if subtotal is None:
            continue
        total += subtotal
        tax += _compute_item_tax(item, subtotal, tax_rate)
    return total, tax


def _compute_discount(total: float, tier: str) -> float:
    """Return the discount amount based on customer tier."""
    rates = {"vip": 0.20, "premium": 0.10}
    return total * rates.get(tier, 0.0)


def _process_single_order(order: Order, tax_rate: float) -> OrderResult:
    """Process one validated order. Raises ValueError on empty total."""
    if not order.is_valid:
        raise ValueError("invalid order")

    total, tax = _compute_totals(order.items, tax_rate)
    if total <= 0:
        raise ValueError("empty total")

    discount = _compute_discount(total, order.customer_tier)
    final = total - discount + tax

    return OrderResult(
        order_id=order.order_id,
        total=round(total, 2),
        discount=round(discount, 2),
        tax=round(tax, 2),
        final_total=round(final, 2),
    )


def process_orders_after(orders, tax_rate=0.08):
    """Refactored version — max nesting depth of 2."""
    if orders is None:
        return [], []

    results = []
    errors = []

    for order in orders:
        try:
            result = _process_single_order(order, tax_rate)
            results.append(result)
        except Exception as e:
            errors.append(f"{order.order_id}: {e}")

    return results, errors


# ---------------------------------------------------------------------------
# Main — verify both versions produce identical output
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_orders = [
        Order(
            order_id="ORD-001",
            items=[
                Item("Widget", 25.00, 3, taxable=True),
                Item("Gadget", 49.99, 1, taxable=True),
                Item("Freebie", 0.00, 1, taxable=False),
            ],
            customer_tier="premium",
        ),
        Order(
            order_id="ORD-002",
            items=[
                Item("Deluxe Widget", 100.00, 2, taxable=True),
                Item("Service Plan", 29.99, 1, taxable=False),
            ],
            customer_tier="vip",
        ),
        Order(
            order_id="ORD-003",
            items=[Item("Nothing", 0.00, 0)],
            customer_tier="standard",
        ),
        Order(
            order_id="ORD-004",
            items=[Item("Valid", 10.00, 1)],
            is_valid=False,
        ),
    ]

    before_results, before_errors = process_orders_before(test_orders)
    after_results, after_errors = process_orders_after(test_orders)

    # Same number of successes and errors
    assert len(before_results) == len(after_results), (
        f"Result count mismatch: {len(before_results)} vs {len(after_results)}"
    )
    assert len(before_errors) == len(after_errors), (
        f"Error count mismatch: {len(before_errors)} vs {len(after_errors)}"
    )

    # Each result matches field-by-field
    for b, a in zip(before_results, after_results):
        assert b.order_id == a.order_id, f"order_id mismatch: {b} vs {a}"
        assert b.total == a.total, f"total mismatch: {b} vs {a}"
        assert b.discount == a.discount, f"discount mismatch: {b} vs {a}"
        assert b.tax == a.tax, f"tax mismatch: {b} vs {a}"
        assert b.final_total == a.final_total, f"final_total mismatch: {b} vs {a}"

    # Verify specific computed values for ORD-001
    ord1 = after_results[0]
    assert ord1.order_id == "ORD-001"
    assert ord1.total == 124.99  # 25*3 + 49.99
    assert ord1.discount == 12.50  # 10% premium
    assert ord1.tax == 10.00  # 124.99 * 0.08 rounded
    assert ord1.final_total == 122.49  # 124.99 - 12.50 + 10.00

    # Verify specific computed values for ORD-002
    ord2 = after_results[1]
    assert ord2.order_id == "ORD-002"
    assert ord2.total == 229.99  # 100*2 + 29.99
    assert ord2.discount == 46.00  # 20% vip
    assert ord2.tax == 16.0  # 200.00 * 0.08
    assert ord2.final_total == 199.99  # 229.99 - 46.00 + 16.0

    # ORD-003 and ORD-004 should be errors
    assert len(after_errors) == 2
    assert "ORD-003" in after_errors[0]
    assert "ORD-004" in after_errors[1]

    # None input handled gracefully
    r, e = process_orders_after(None)
    assert r == [] and e == []

    # Empty list handled gracefully
    r, e = process_orders_after([])
    assert r == [] and e == []

    print("All assertions passed.")
