from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TodoCreate(BaseModel):
    title: str
    description: str = ""
    completed: bool = False


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None


class TodoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    completed: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
