"""Pydantic schemas for the Item resource."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, examples=["My item"])
    description: str | None = Field(None, examples=["A longer description"])
    is_active: bool = True


class ItemCreate(ItemBase):
    """Payload accepted by POST /items."""


class ItemUpdate(BaseModel):
    """Payload accepted by PATCH /items/{id} — all fields optional."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class ItemRead(ItemBase):
    """Shape returned by GET /items and write mutations."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
