from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
import uuid


@dataclass
class SubTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    status: str = "pending"  # pending|in_progress|done|blocked
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
    tasks: list = field(default_factory=list)  # list of SubTask
    priority: int = 1  # 1=high 2=medium 3=low
    depends_on: list = field(default_factory=list)  # epic ids


@dataclass
class Project:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    type: str = ""  # fastapi|nextjs|django|react|cli|pipeline|unknown
    description: str = ""
    status: str = "active"  # active|paused|done|archived
    path: str = ""  # absolute path to project on disk
    epics: list = field(default_factory=list)  # list of Epic
    tags: list = field(default_factory=list)
    velocity: float = 0.0  # tasks completed per day
    quality_avg: float = 0.0
    created: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    meta: dict = field(default_factory=dict)  # arbitrary extra data
