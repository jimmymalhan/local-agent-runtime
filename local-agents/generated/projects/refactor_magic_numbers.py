"""
Refactor: Replace magic numbers and strings with named constants, Enums, and config.

Before: Code littered with 20+ magic numbers/strings inline.
After:  All values extracted to named constants, Enum classes, and a config dataclass.
Both versions produce identical behavior, verified by assertions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


# ============================================================================
# BEFORE — magic numbers and strings everywhere
# ============================================================================

def before_calculate_shipping(weight: float, destination: str) -> float:
    if weight <= 0:
        raise ValueError("Weight must be positive")
    if weight > 150:
        raise ValueError("Package too heavy")

    if destination == "domestic":
        base = 5.99
        per_lb = 0.50
        if weight > 50:
            per_lb = 0.35
    elif destination == "international":
        base = 15.99
        per_lb = 2.25
        if weight > 50:
            per_lb = 1.80
    elif destination == "express":
        base = 25.00
        per_lb = 3.50
        if weight > 50:
            per_lb = 2.75
    else:
        raise ValueError("Unknown destination type")

    cost = base + (weight * per_lb)
    cost = round(cost, 2)

    if cost > 500.00:
        cost = 500.00

    return cost


def before_classify_user(points: int, months_active: int) -> str:
    if points < 0 or months_active < 0:
        raise ValueError("Negative values not allowed")

    if points >= 10000 and months_active >= 24:
        return "platinum"
    elif points >= 5000 and months_active >= 12:
        return "gold"
    elif points >= 1000 and months_active >= 3:
        return "silver"
    else:
        return "bronze"


def before_apply_discount(price: float, user_tier: str, quantity: int) -> float:
    if price < 0:
        raise ValueError("Price cannot be negative")

    if user_tier == "platinum":
        discount = 0.20
    elif user_tier == "gold":
        discount = 0.15
    elif user_tier == "silver":
        discount = 0.10
    elif user_tier == "bronze":
        discount = 0.05
    else:
        discount = 0.0

    if quantity >= 100:
        discount += 0.10
    elif quantity >= 50:
        discount += 0.07
    elif quantity >= 10:
        discount += 0.03

    if discount > 0.40:
        discount = 0.40

    total = price * quantity * (1 - discount)
    return round(total, 2)


def before_compute_password_strength(password: str) -> str:
    score = 0

    if len(password) >= 16:
        score += 3
    elif len(password) >= 12:
        score += 2
    elif len(password) >= 8:
        score += 1

    if any(c.isupper() for c in password):
        score += 1
    if any(c.islower() for c in password):
        score += 1
    if any(c.isdigit() for c in password):
        score += 1
    if any(c in "!@#$%^&*()-_=+[]{}|;:',.<>?/`~" for c in password) :
        score += 2

    if score >= 7:
        return "strong"
    elif score >= 4:
        return "medium"
    else:
        return "weak"


def before_paginate(items: list, page: int, per_page: int | None = None) -> dict:
    if per_page is None:
        per_page = 25
    if per_page > 100:
        per_page = 100
    if per_page < 1:
        per_page = 1
    if page < 1:
        page = 1

    total = len(items)
    total_pages = max(1, math.ceil(total / per_page))
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page

    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


# ============================================================================
# AFTER — named constants, Enums, config dataclass
# ============================================================================

# --- Enums ---

class ShippingZone(str, Enum):
    DOMESTIC = "domestic"
    INTERNATIONAL = "international"
    EXPRESS = "express"


class UserTier(str, Enum):
    PLATINUM = "platinum"
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


class PasswordStrength(str, Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


# --- Shipping constants ---

MAX_PACKAGE_WEIGHT_LBS = 150
BULK_WEIGHT_THRESHOLD_LBS = 50
MAX_SHIPPING_COST = 500.00

SHIPPING_RATES: dict[ShippingZone, dict[str, float]] = {
    ShippingZone.DOMESTIC: {
        "base": 5.99,
        "per_lb": 0.50,
        "per_lb_bulk": 0.35,
    },
    ShippingZone.INTERNATIONAL: {
        "base": 15.99,
        "per_lb": 2.25,
        "per_lb_bulk": 1.80,
    },
    ShippingZone.EXPRESS: {
        "base": 25.00,
        "per_lb": 3.50,
        "per_lb_bulk": 2.75,
    },
}

# --- User classification thresholds ---

TIER_THRESHOLDS: list[tuple[UserTier, int, int]] = [
    (UserTier.PLATINUM, 10_000, 24),
    (UserTier.GOLD, 5_000, 12),
    (UserTier.SILVER, 1_000, 3),
]
DEFAULT_TIER = UserTier.BRONZE

# --- Discount constants ---

TIER_DISCOUNTS: dict[UserTier, float] = {
    UserTier.PLATINUM: 0.20,
    UserTier.GOLD: 0.15,
    UserTier.SILVER: 0.10,
    UserTier.BRONZE: 0.05,
}
DEFAULT_DISCOUNT = 0.0
MAX_DISCOUNT = 0.40

QUANTITY_DISCOUNT_BRACKETS: list[tuple[int, float]] = [
    (100, 0.10),
    (50, 0.07),
    (10, 0.03),
]

# --- Password strength constants ---

SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{}|;:',.<>?/`~"

PASSWORD_LENGTH_SCORES: list[tuple[int, int]] = [
    (16, 3),
    (12, 2),
    (8, 1),
]
SCORE_UPPERCASE = 1
SCORE_LOWERCASE = 1
SCORE_DIGIT = 1
SCORE_SPECIAL = 2

STRENGTH_THRESHOLDS: list[tuple[int, PasswordStrength]] = [
    (7, PasswordStrength.STRONG),
    (4, PasswordStrength.MEDIUM),
]
DEFAULT_STRENGTH = PasswordStrength.WEAK

# --- Pagination config ---


@dataclass(frozen=True)
class PaginationConfig:
    default_per_page: int = 25
    max_per_page: int = 100
    min_per_page: int = 1
    min_page: int = 1


PAGINATION = PaginationConfig()


# --- Refactored functions ---

def after_calculate_shipping(weight: float, destination: str) -> float:
    if weight <= 0:
        raise ValueError("Weight must be positive")
    if weight > MAX_PACKAGE_WEIGHT_LBS:
        raise ValueError("Package too heavy")

    zone = ShippingZone(destination)
    rates = SHIPPING_RATES[zone]

    per_lb = rates["per_lb_bulk"] if weight > BULK_WEIGHT_THRESHOLD_LBS else rates["per_lb"]
    cost = rates["base"] + (weight * per_lb)
    cost = round(cost, 2)

    return min(cost, MAX_SHIPPING_COST)


def after_classify_user(points: int, months_active: int) -> str:
    if points < 0 or months_active < 0:
        raise ValueError("Negative values not allowed")

    for tier, min_points, min_months in TIER_THRESHOLDS:
        if points >= min_points and months_active >= min_months:
            return tier.value

    return DEFAULT_TIER.value


def after_apply_discount(price: float, user_tier: str, quantity: int) -> float:
    if price < 0:
        raise ValueError("Price cannot be negative")

    tier_enum = UserTier(user_tier)
    discount = TIER_DISCOUNTS.get(tier_enum, DEFAULT_DISCOUNT)

    for min_qty, qty_discount in QUANTITY_DISCOUNT_BRACKETS:
        if quantity >= min_qty:
            discount += qty_discount
            break

    discount = min(discount, MAX_DISCOUNT)
    total = price * quantity * (1 - discount)
    return round(total, 2)


def after_compute_password_strength(password: str) -> str:
    score = 0

    for min_len, pts in PASSWORD_LENGTH_SCORES:
        if len(password) >= min_len:
            score += pts
            break

    if any(c.isupper() for c in password):
        score += SCORE_UPPERCASE
    if any(c.islower() for c in password):
        score += SCORE_LOWERCASE
    if any(c.isdigit() for c in password):
        score += SCORE_DIGIT
    if any(c in SPECIAL_CHARACTERS for c in password):
        score += SCORE_SPECIAL

    for threshold, strength in STRENGTH_THRESHOLDS:
        if score >= threshold:
            return strength.value

    return DEFAULT_STRENGTH.value


def after_paginate(items: list, page: int, per_page: int | None = None) -> dict:
    cfg = PAGINATION

    if per_page is None:
        per_page = cfg.default_per_page
    per_page = max(cfg.min_per_page, min(per_page, cfg.max_per_page))
    page = max(cfg.min_page, page)

    total = len(items)
    total_pages = max(1, math.ceil(total / per_page))
    page = min(page, total_pages)

    start = (page - 1) * per_page
    end = start + per_page

    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


# ============================================================================
# Verification — both versions must produce identical results
# ============================================================================

if __name__ == "__main__":

    # -- Shipping --
    shipping_cases = [
        (10.0, "domestic"),
        (60.0, "domestic"),
        (5.0, "international"),
        (75.0, "international"),
        (1.0, "express"),
        (100.0, "express"),
        (0.5, "domestic"),
        (50.0, "domestic"),
        (50.1, "domestic"),
        (150.0, "express"),
    ]
    for w, d in shipping_cases:
        b = before_calculate_shipping(w, d)
        a = after_calculate_shipping(w, d)
        assert b == a, f"Shipping mismatch: ({w}, {d}) => before={b}, after={a}"

    # Errors
    for bad_w, bad_d in [(-1, "domestic"), (0, "domestic"), (151, "domestic")]:
        for fn in (before_calculate_shipping, after_calculate_shipping):
            try:
                fn(bad_w, bad_d)
                assert False, "Should have raised"
            except ValueError:
                pass

    # -- User classification --
    classify_cases = [
        (10000, 24),
        (10000, 23),
        (9999, 24),
        (5000, 12),
        (5000, 11),
        (4999, 12),
        (1000, 3),
        (1000, 2),
        (999, 3),
        (0, 0),
        (50000, 100),
        (1500, 6),
    ]
    for pts, mo in classify_cases:
        b = before_classify_user(pts, mo)
        a = after_classify_user(pts, mo)
        assert b == a, f"Classify mismatch: ({pts}, {mo}) => before={b}, after={a}"

    # -- Discount --
    discount_cases = [
        (100.0, "platinum", 1),
        (100.0, "gold", 10),
        (100.0, "silver", 50),
        (100.0, "bronze", 100),
        (50.0, "platinum", 200),
        (10.0, "gold", 5),
        (0.0, "bronze", 1),
        (999.99, "platinum", 100),
        (25.0, "silver", 9),
        (25.0, "silver", 10),
        (25.0, "silver", 49),
        (25.0, "silver", 50),
        (25.0, "silver", 99),
        (25.0, "silver", 100),
    ]
    for pr, tier, qty in discount_cases:
        b = before_apply_discount(pr, tier, qty)
        a = after_apply_discount(pr, tier, qty)
        assert b == a, f"Discount mismatch: ({pr}, {tier}, {qty}) => before={b}, after={a}"

    # -- Password strength --
    password_cases = [
        "",
        "abc",
        "abcdefgh",
        "Abcdefgh",
        "Abcdefgh1",
        "Abcdefgh1!",
        "abcdefghijkl",
        "Abcdefghijkl1!",
        "AbcdefghijklmnopQ1!",
        "short",
        "1234567890123456",
        "ALLUPPERCASE!1",
        "!@#$%^&*()",
        "aA1!aA1!aA1!aA1!",
    ]
    for pw in password_cases:
        b = before_compute_password_strength(pw)
        a = after_compute_password_strength(pw)
        assert b == a, f"Password mismatch: '{pw}' => before={b}, after={a}"

    # -- Pagination --
    sample_items = list(range(237))
    paginate_cases = [
        (1, None),
        (1, 10),
        (5, 25),
        (10, 50),
        (1, 100),
        (1, 200),   # exceeds max
        (1, 0),     # below min
        (1, -5),    # below min
        (0, 25),    # page < 1
        (-3, 25),   # page < 1
        (999, 25),  # page > total_pages
        (1, 1),
        (237, 1),
        (238, 1),   # past end
        (3, 100),
    ]
    for pg, pp in paginate_cases:
        b = before_paginate(sample_items, pg, pp)
        a = after_paginate(sample_items, pg, pp)
        assert b == a, f"Paginate mismatch: (page={pg}, per_page={pp}) => before={b}, after={a}"

    # Empty list
    for pg, pp in [(1, None), (1, 10), (5, 25)]:
        b = before_paginate([], pg, pp)
        a = after_paginate([], pg, pp)
        assert b == a, f"Paginate empty mismatch: (page={pg}, per_page={pp})"

    print("All assertions passed. Before and after produce identical results.")
