import unittest
from dataclasses import dataclass, field
from typing import Optional


# --- Implementation ---

@dataclass
class Item:
    name: str
    price: float
    quantity: int = 1


@dataclass
class Coupon:
    code: str
    type: str  # "percent" or "fixed"
    value: float


@dataclass
class Receipt:
    items: list
    subtotal: float
    discount: float
    tax: float
    total: float
    coupon_code: Optional[str] = None


class ShoppingCart:
    TAX_RATE = 0.08

    def __init__(self):
        self.items: dict[str, Item] = {}
        self.coupon: Optional[Coupon] = None

    def add_item(self, name: str, price: float, quantity: int = 1):
        if price < 0:
            raise ValueError("Price cannot be negative")
        if quantity < 1:
            raise ValueError("Quantity must be at least 1")
        if name in self.items:
            self.items[name].quantity += quantity
        else:
            self.items[name] = Item(name=name, price=price, quantity=quantity)

    def remove_item(self, name: str, quantity: Optional[int] = None):
        if name not in self.items:
            raise KeyError(f"Item '{name}' not in cart")
        if quantity is None or quantity >= self.items[name].quantity:
            del self.items[name]
        else:
            if quantity < 1:
                raise ValueError("Quantity must be at least 1")
            self.items[name].quantity -= quantity

    def apply_coupon(self, coupon: Coupon):
        if coupon.type not in ("percent", "fixed"):
            raise ValueError(f"Invalid coupon type: {coupon.type}")
        if coupon.type == "percent" and not (0 < coupon.value <= 100):
            raise ValueError("Percent coupon must be between 0 and 100")
        if coupon.type == "fixed" and coupon.value < 0:
            raise ValueError("Fixed coupon value cannot be negative")
        self.coupon = coupon

    def get_subtotal(self) -> float:
        return sum(item.price * item.quantity for item in self.items.values())

    def _calc_discount(self, subtotal: float) -> float:
        if self.coupon is None:
            return 0.0
        if self.coupon.type == "percent":
            return round(subtotal * (self.coupon.value / 100), 2)
        else:
            return min(self.coupon.value, subtotal)

    def get_total(self) -> float:
        subtotal = self.get_subtotal()
        discount = self._calc_discount(subtotal)
        after_discount = subtotal - discount
        tax = round(after_discount * self.TAX_RATE, 2)
        return round(after_discount + tax, 2)

    def checkout(self) -> Receipt:
        if not self.items:
            raise RuntimeError("Cannot checkout an empty cart")
        subtotal = self.get_subtotal()
        discount = self._calc_discount(subtotal)
        after_discount = subtotal - discount
        tax = round(after_discount * self.TAX_RATE, 2)
        total = round(after_discount + tax, 2)
        receipt = Receipt(
            items=list(self.items.values()),
            subtotal=subtotal,
            discount=discount,
            tax=tax,
            total=total,
            coupon_code=self.coupon.code if self.coupon else None,
        )
        self.items.clear()
        self.coupon = None
        return receipt


# --- Tests ---

class TestAddItem(unittest.TestCase):
    def setUp(self):
        self.cart = ShoppingCart()

    def test_add_single_item(self):
        self.cart.add_item("Apple", 1.50)
        self.assertIn("Apple", self.cart.items)
        self.assertEqual(self.cart.items["Apple"].quantity, 1)

    def test_add_item_with_quantity(self):
        self.cart.add_item("Banana", 0.75, quantity=3)
        self.assertEqual(self.cart.items["Banana"].quantity, 3)

    def test_add_duplicate_item_increments_quantity(self):
        self.cart.add_item("Apple", 1.50, quantity=2)
        self.cart.add_item("Apple", 1.50, quantity=3)
        self.assertEqual(self.cart.items["Apple"].quantity, 5)

    def test_add_multiple_different_items(self):
        self.cart.add_item("Apple", 1.50)
        self.cart.add_item("Banana", 0.75)
        self.assertEqual(len(self.cart.items), 2)

    def test_add_item_negative_price_raises(self):
        with self.assertRaises(ValueError):
            self.cart.add_item("Bad", -1.00)

    def test_add_item_zero_quantity_raises(self):
        with self.assertRaises(ValueError):
            self.cart.add_item("Bad", 1.00, quantity=0)


class TestRemoveItem(unittest.TestCase):
    def setUp(self):
        self.cart = ShoppingCart()
        self.cart.add_item("Apple", 1.50, quantity=5)

    def test_remove_item_entirely(self):
        self.cart.remove_item("Apple")
        self.assertNotIn("Apple", self.cart.items)

    def test_remove_partial_quantity(self):
        self.cart.remove_item("Apple", quantity=2)
        self.assertEqual(self.cart.items["Apple"].quantity, 3)

    def test_remove_exact_quantity_removes_item(self):
        self.cart.remove_item("Apple", quantity=5)
        self.assertNotIn("Apple", self.cart.items)

    def test_remove_more_than_available_removes_item(self):
        self.cart.remove_item("Apple", quantity=10)
        self.assertNotIn("Apple", self.cart.items)

    def test_remove_nonexistent_item_raises(self):
        with self.assertRaises(KeyError):
            self.cart.remove_item("Ghost")

    def test_remove_zero_quantity_raises(self):
        with self.assertRaises(ValueError):
            self.cart.remove_item("Apple", quantity=0)


class TestApplyCoupon(unittest.TestCase):
    def setUp(self):
        self.cart = ShoppingCart()
        self.cart.add_item("Laptop", 1000.00)

    def test_apply_percent_coupon(self):
        coupon = Coupon(code="SAVE10", type="percent", value=10)
        self.cart.apply_coupon(coupon)
        self.assertEqual(self.cart.coupon.code, "SAVE10")

    def test_apply_fixed_coupon(self):
        coupon = Coupon(code="FLAT50", type="fixed", value=50.00)
        self.cart.apply_coupon(coupon)
        self.assertEqual(self.cart.coupon.code, "FLAT50")

    def test_apply_coupon_replaces_previous(self):
        self.cart.apply_coupon(Coupon(code="A", type="percent", value=10))
        self.cart.apply_coupon(Coupon(code="B", type="fixed", value=20))
        self.assertEqual(self.cart.coupon.code, "B")

    def test_invalid_coupon_type_raises(self):
        with self.assertRaises(ValueError):
            self.cart.apply_coupon(Coupon(code="BAD", type="bogo", value=10))

    def test_percent_coupon_over_100_raises(self):
        with self.assertRaises(ValueError):
            self.cart.apply_coupon(Coupon(code="X", type="percent", value=150))

    def test_percent_coupon_zero_raises(self):
        with self.assertRaises(ValueError):
            self.cart.apply_coupon(Coupon(code="X", type="percent", value=0))

    def test_fixed_coupon_negative_raises(self):
        with self.assertRaises(ValueError):
            self.cart.apply_coupon(Coupon(code="X", type="fixed", value=-5))


class TestGetTotal(unittest.TestCase):
    def setUp(self):
        self.cart = ShoppingCart()

    def test_total_single_item_with_tax(self):
        self.cart.add_item("Book", 10.00)
        # 10.00 * 1.08 = 10.80
        self.assertEqual(self.cart.get_total(), 10.80)

    def test_total_multiple_items(self):
        self.cart.add_item("Book", 10.00)
        self.cart.add_item("Pen", 2.00, quantity=3)
        # subtotal = 10 + 6 = 16, tax = 1.28, total = 17.28
        self.assertEqual(self.cart.get_total(), 17.28)

    def test_total_with_percent_coupon(self):
        self.cart.add_item("Shirt", 50.00)
        self.cart.apply_coupon(Coupon(code="HALF", type="percent", value=50))
        # subtotal=50, discount=25, after=25, tax=2.00, total=27.00
        self.assertEqual(self.cart.get_total(), 27.00)

    def test_total_with_fixed_coupon(self):
        self.cart.add_item("Shirt", 50.00)
        self.cart.apply_coupon(Coupon(code="TEN", type="fixed", value=10.00))
        # subtotal=50, discount=10, after=40, tax=3.20, total=43.20
        self.assertEqual(self.cart.get_total(), 43.20)

    def test_total_fixed_coupon_exceeds_subtotal(self):
        self.cart.add_item("Gum", 1.00)
        self.cart.apply_coupon(Coupon(code="BIG", type="fixed", value=100.00))
        # discount capped at subtotal, total = 0 + 0 tax = 0
        self.assertEqual(self.cart.get_total(), 0.00)

    def test_total_100_percent_coupon(self):
        self.cart.add_item("Item", 25.00)
        self.cart.apply_coupon(Coupon(code="FREE", type="percent", value=100))
        self.assertEqual(self.cart.get_total(), 0.00)

    def test_total_empty_cart(self):
        self.assertEqual(self.cart.get_total(), 0.00)

    def test_total_no_coupon(self):
        self.cart.add_item("Widget", 19.99)
        # 19.99 * 1.08 = 21.5892 -> 21.59
        self.assertEqual(self.cart.get_total(), 21.59)


class TestCheckout(unittest.TestCase):
    def setUp(self):
        self.cart = ShoppingCart()

    def test_checkout_returns_receipt(self):
        self.cart.add_item("Laptop", 999.99)
        receipt = self.cart.checkout()
        self.assertIsInstance(receipt, Receipt)

    def test_checkout_receipt_fields(self):
        self.cart.add_item("Monitor", 300.00)
        self.cart.apply_coupon(Coupon(code="SAVE20", type="percent", value=20))
        receipt = self.cart.checkout()
        self.assertEqual(receipt.subtotal, 300.00)
        self.assertEqual(receipt.discount, 60.00)
        self.assertEqual(receipt.tax, 19.20)  # 240 * 0.08
        self.assertEqual(receipt.total, 259.20)
        self.assertEqual(receipt.coupon_code, "SAVE20")

    def test_checkout_clears_cart(self):
        self.cart.add_item("Mouse", 25.00)
        self.cart.checkout()
        self.assertEqual(len(self.cart.items), 0)
        self.assertIsNone(self.cart.coupon)

    def test_checkout_clears_coupon(self):
        self.cart.add_item("Keyboard", 75.00)
        self.cart.apply_coupon(Coupon(code="OFF5", type="fixed", value=5.00))
        self.cart.checkout()
        self.assertIsNone(self.cart.coupon)

    def test_checkout_empty_cart_raises(self):
        with self.assertRaises(RuntimeError):
            self.cart.checkout()

    def test_checkout_no_coupon_receipt(self):
        self.cart.add_item("Cable", 12.00)
        receipt = self.cart.checkout()
        self.assertIsNone(receipt.coupon_code)
        self.assertEqual(receipt.discount, 0.0)
        self.assertEqual(receipt.subtotal, 12.00)
        self.assertEqual(receipt.tax, 0.96)
        self.assertEqual(receipt.total, 12.96)

    def test_checkout_multiple_items(self):
        self.cart.add_item("A", 10.00, quantity=2)
        self.cart.add_item("B", 5.00, quantity=1)
        self.cart.apply_coupon(Coupon(code="FLAT5", type="fixed", value=5.00))
        receipt = self.cart.checkout()
        # subtotal=25, discount=5, after=20, tax=1.60, total=21.60
        self.assertEqual(receipt.subtotal, 25.00)
        self.assertEqual(receipt.discount, 5.00)
        self.assertEqual(receipt.tax, 1.60)
        self.assertEqual(receipt.total, 21.60)

    def test_double_checkout_raises(self):
        self.cart.add_item("Dongle", 15.00)
        self.cart.checkout()
        with self.assertRaises(RuntimeError):
            self.cart.checkout()


class TestEdgeCases(unittest.TestCase):
    def test_add_then_remove_then_total(self):
        cart = ShoppingCart()
        cart.add_item("X", 10.00, quantity=3)
        cart.remove_item("X", quantity=2)
        # 1 * 10 = 10, tax = 0.80, total = 10.80
        self.assertEqual(cart.get_total(), 10.80)

    def test_coupon_on_empty_cart_total_zero(self):
        cart = ShoppingCart()
        cart.apply_coupon(Coupon(code="X", type="fixed", value=50))
        self.assertEqual(cart.get_total(), 0.00)

    def test_fractional_prices(self):
        cart = ShoppingCart()
        cart.add_item("Candy", 0.33, quantity=3)
        # subtotal = 0.99, tax = 0.08 (0.0792 rounded), total = 1.07
        self.assertEqual(cart.get_subtotal(), 0.99)
        self.assertEqual(cart.get_total(), 1.07)

    def test_large_order(self):
        cart = ShoppingCart()
        cart.add_item("Bulk", 0.01, quantity=10000)
        # subtotal = 100, tax = 8.00, total = 108.00
        self.assertEqual(cart.get_total(), 108.00)


if __name__ == "__main__":
    # Run unittest suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Additional standalone assertions
    print("\n--- Standalone Assertions ---")

    cart = ShoppingCart()
    cart.add_item("Widget", 25.00, quantity=2)
    assert cart.get_subtotal() == 50.00, "Subtotal should be 50.00"

    cart.apply_coupon(Coupon(code="10OFF", type="percent", value=10))
    assert cart.get_total() == 48.60, "Total should be 48.60 (50 - 5 = 45, tax 3.60)"

    receipt = cart.checkout()
    assert receipt.subtotal == 50.00
    assert receipt.discount == 5.00
    assert receipt.tax == 3.60
    assert receipt.total == 48.60
    assert receipt.coupon_code == "10OFF"
    assert len(cart.items) == 0

    cart.add_item("Gadget", 100.00)
    cart.apply_coupon(Coupon(code="FLAT25", type="fixed", value=25.00))
    assert cart.get_total() == 81.00  # 100-25=75, tax=6.00, total=81.00
    receipt = cart.checkout()
    assert receipt.total == 81.00

    print("All standalone assertions passed.")
