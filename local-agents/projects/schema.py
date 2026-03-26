from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class SubTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    status: str = "pending"
    category: str = "code_gen"
    agent: str = ""
    result: dict = field(default_factory=dict)
    quality: int = 0
    created: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Epic:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    status: str = "pending"
    tasks: list = field(default_factory=list)
    priority: int = 1
    depends_on: list = field(default_factory=list)


@dataclass
class Project:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    type: str = ""
    description: str = ""
    status: str = "active"
    path: str = ""
    epics: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    velocity: float = 0.0
    quality_avg: float = 0.0
    created: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    meta: dict = field(default_factory=dict)
