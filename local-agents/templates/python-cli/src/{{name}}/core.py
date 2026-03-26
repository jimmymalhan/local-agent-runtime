"""Core business logic for {{name}}."""
from __future__ import annotations


class ItemNotFoundError(Exception):
    """Raised when an item cannot be found."""


# In-memory store for demo purposes — swap with a real DB/API
_STORE: dict[int, dict] = {
    1: {"id": 1, "name": "Alpha", "status": "pending"},
    2: {"id": 2, "name": "Beta", "status": "done"},
    3: {"id": 3, "name": "Gamma", "status": "pending"},
}


def list_items(limit: int = 10) -> list[dict]:
    """Return up to `limit` items."""
    return list(_STORE.values())[:limit]


def get_item(item_id: int) -> dict:
    """Return item by id.

    Raises:
        ItemNotFoundError: when item_id is not in the store.
    """
    if item_id not in _STORE:
        raise ItemNotFoundError(f"Item {item_id} not found")
    return _STORE[item_id]


def process_item(item_id: int, *, verbose: bool = False) -> str:
    """Mark item as processed.

    Args:
        item_id: The item to process.
        verbose: Print debug output.

    Returns:
        Status string.

    Raises:
        ItemNotFoundError: when item_id is not in the store.
    """
    item = get_item(item_id)
    if verbose:
        print(f"[DEBUG] Processing item: {item}")
    _STORE[item_id]["status"] = "done"
    return f"status=done (was {item['status']})"
