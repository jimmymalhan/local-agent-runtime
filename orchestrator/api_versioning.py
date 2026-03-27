#!/usr/bin/env python3
"""
api_versioning.py — API Versioning & Backward Compatibility
============================================================
Provides:
  1. VersionedAPI router that mounts endpoints under /v1, /v2, etc.
  2. Schema transformers that up/down-convert payloads between versions.
  3. Deprecation headers and sunset dates on older versions.
  4. Middleware that resolves the requested version from URL path,
     Accept header, or query parameter.
  5. Backward-compatible field mapping so old clients keep working.

Usage:
    from orchestrator.api_versioning import VersionedAPI, SchemaTransformer

    api = VersionedAPI()
    api.register_version("v1", schema_v1, sunset="2026-06-01")
    api.register_version("v2", schema_v2)
    resolved = api.resolve("/v1/tasks")       # → VersionContext(version="v1", ...)
    payload  = api.transform(data, from_v="v2", to_v="v1")
"""

import copy
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Version context returned after resolution
# ---------------------------------------------------------------------------
@dataclass
class VersionContext:
    """Resolved API version with metadata."""
    version: str           # e.g. "v1", "v2"
    major: int             # parsed integer 1, 2, …
    deprecated: bool       # True if past sunset or marked deprecated
    sunset_date: Optional[str]  # ISO date when version will be removed
    path: str              # original request path
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Field mapping rule
# ---------------------------------------------------------------------------
@dataclass
class FieldMapping:
    """Describes how a field changed between versions."""
    old_name: str
    new_name: str
    transform_up: Optional[Callable[[Any], Any]] = None   # old → new
    transform_down: Optional[Callable[[Any], Any]] = None  # new → old


# ---------------------------------------------------------------------------
# Schema definition per version
# ---------------------------------------------------------------------------
@dataclass
class VersionSchema:
    """Schema contract for one API version."""
    version: str
    fields: Dict[str, str]  # field_name → type hint string
    required: Set[str] = field(default_factory=set)
    defaults: Dict[str, Any] = field(default_factory=dict)
    removed_fields: Set[str] = field(default_factory=set)
    added_fields: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Schema transformer — converts payloads between versions
# ---------------------------------------------------------------------------
class SchemaTransformer:
    """Transforms API payloads between different schema versions."""

    def __init__(self):
        self._mappings: Dict[Tuple[str, str], List[FieldMapping]] = {}

    def add_mapping(self, from_version: str, to_version: str,
                    mappings: List[FieldMapping]):
        """Register field mappings for a version pair."""
        key = (from_version, to_version)
        self._mappings[key] = list(mappings)
        # Auto-generate reverse mappings
        reverse_key = (to_version, from_version)
        if reverse_key not in self._mappings:
            reverse = []
            for m in mappings:
                reverse.append(FieldMapping(
                    old_name=m.new_name,
                    new_name=m.old_name,
                    transform_up=m.transform_down,
                    transform_down=m.transform_up,
                ))
            self._mappings[reverse_key] = reverse

    def transform(self, data: Dict[str, Any], from_version: str,
                  to_version: str) -> Dict[str, Any]:
        """Transform a payload from one version to another.

        Supports direct mappings and multi-hop chains (v1→v2→v3).
        """
        if from_version == to_version:
            return copy.deepcopy(data)

        # Try direct mapping first
        key = (from_version, to_version)
        if key in self._mappings:
            return self._apply_mappings(data, self._mappings[key])

        # Try multi-hop via intermediate versions
        path = self._find_path(from_version, to_version)
        if path is None:
            raise ValueError(
                f"No transformation path from {from_version} to {to_version}"
            )

        result = copy.deepcopy(data)
        for i in range(len(path) - 1):
            hop_key = (path[i], path[i + 1])
            result = self._apply_mappings(result, self._mappings[hop_key])
        return result

    def _apply_mappings(self, data: Dict[str, Any],
                        mappings: List[FieldMapping]) -> Dict[str, Any]:
        """Apply a list of field mappings to a payload."""
        result = copy.deepcopy(data)
        for m in mappings:
            if m.old_name in result:
                value = result.pop(m.old_name)
                if m.transform_up is not None:
                    value = m.transform_up(value)
                result[m.new_name] = value
        return result

    def _find_path(self, start: str, end: str) -> Optional[List[str]]:
        """BFS to find shortest transformation path."""
        # Collect all known versions from mapping keys
        all_versions: Set[str] = set()
        graph: Dict[str, Set[str]] = {}
        for (f, t) in self._mappings:
            all_versions.add(f)
            all_versions.add(t)
            graph.setdefault(f, set()).add(t)

        # BFS
        visited = {start}
        queue: List[List[str]] = [[start]]
        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == end:
                return path
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return None


# ---------------------------------------------------------------------------
# Deprecation manager
# ---------------------------------------------------------------------------
class DeprecationManager:
    """Tracks version lifecycle: active, deprecated, sunset."""

    def __init__(self):
        self._versions: Dict[str, Dict[str, Any]] = {}

    def register(self, version: str, sunset_date: Optional[str] = None,
                 deprecated: bool = False):
        """Register a version with optional sunset date."""
        self._versions[version] = {
            "sunset_date": sunset_date,
            "deprecated": deprecated,
            "registered_at": datetime.utcnow().isoformat(),
        }

    def is_deprecated(self, version: str) -> bool:
        info = self._versions.get(version)
        if info is None:
            return False
        if info["deprecated"]:
            return True
        if info["sunset_date"]:
            try:
                sunset = date.fromisoformat(info["sunset_date"])
                return date.today() >= sunset
            except ValueError:
                return False
        return False

    def get_sunset_date(self, version: str) -> Optional[str]:
        info = self._versions.get(version)
        return info["sunset_date"] if info else None

    def get_deprecation_headers(self, version: str) -> Dict[str, str]:
        """Return HTTP headers to attach to responses for deprecated versions."""
        headers = {}
        if self.is_deprecated(version):
            headers["Deprecation"] = "true"
            sunset = self.get_sunset_date(version)
            if sunset:
                headers["Sunset"] = sunset
            headers["Link"] = '</v{}>; rel="successor-version"'.format(
                self._latest_major()
            )
            headers["X-API-Warn"] = (
                f"API version {version} is deprecated. "
                f"Please migrate to v{self._latest_major()}."
            )
        return headers

    def _latest_major(self) -> int:
        majors = []
        for v in self._versions:
            m = re.match(r"v(\d+)", v)
            if m:
                majors.append(int(m.group(1)))
        return max(majors) if majors else 1

    def list_versions(self) -> List[Dict[str, Any]]:
        result = []
        for version, info in sorted(self._versions.items()):
            result.append({
                "version": version,
                "deprecated": self.is_deprecated(version),
                "sunset_date": info["sunset_date"],
                "status": "deprecated" if self.is_deprecated(version) else "active",
            })
        return result


# ---------------------------------------------------------------------------
# Version resolver — extracts version from path / header / query
# ---------------------------------------------------------------------------
class VersionResolver:
    """Resolves the API version from a request."""

    VERSION_PATH_RE = re.compile(r"^/v(\d+)(/.*)?$")
    ACCEPT_RE = re.compile(r"application/vnd\.localagent\.v(\d+)\+json")

    def __init__(self, default_version: str = "v2",
                 supported: Optional[Set[str]] = None):
        self.default_version = default_version
        self.supported = supported or {"v1", "v2"}

    def resolve(self, path: str, accept_header: Optional[str] = None,
                query_version: Optional[str] = None) -> VersionContext:
        """Resolve version from (in priority order):
        1. URL path prefix (/v1/...)
        2. Accept header (application/vnd.localagent.v1+json)
        3. Query parameter (?version=v1)
        4. Default version
        """
        version = None
        source = "default"

        # 1. URL path
        m = self.VERSION_PATH_RE.match(path)
        if m:
            version = f"v{m.group(1)}"
            source = "path"

        # 2. Accept header
        if version is None and accept_header:
            am = self.ACCEPT_RE.search(accept_header)
            if am:
                version = f"v{am.group(1)}"
                source = "header"

        # 3. Query parameter
        if version is None and query_version:
            version = query_version if query_version.startswith("v") \
                else f"v{query_version}"
            source = "query"

        # 4. Default
        if version is None:
            version = self.default_version

        # Validate
        ctx_warnings = []
        if version not in self.supported:
            ctx_warnings.append(
                f"Version {version} is not supported. "
                f"Falling back to {self.default_version}."
            )
            version = self.default_version

        major = int(re.match(r"v(\d+)", version).group(1))

        return VersionContext(
            version=version,
            major=major,
            deprecated=False,  # Caller enriches via DeprecationManager
            sunset_date=None,
            path=path,
            warnings=ctx_warnings,
        )


# ---------------------------------------------------------------------------
# Backward-compatible response builder
# ---------------------------------------------------------------------------
class BackwardCompatibleResponse:
    """Wraps a response payload so old clients get the fields they expect."""

    def __init__(self, transformer: SchemaTransformer,
                 current_version: str = "v2"):
        self.transformer = transformer
        self.current_version = current_version

    def build(self, data: Dict[str, Any],
              target_version: str) -> Dict[str, Any]:
        """Build a response payload compatible with target_version."""
        result = self.transformer.transform(
            data, from_version=self.current_version, to_version=target_version
        )
        # Always include version metadata
        result["_meta"] = {
            "api_version": target_version,
            "current_version": self.current_version,
        }
        if target_version != self.current_version:
            result["_meta"]["migration_notice"] = (
                f"You are using {target_version}. "
                f"Please migrate to {self.current_version}."
            )
        return result


# ---------------------------------------------------------------------------
# VersionedAPI — top-level orchestrator
# ---------------------------------------------------------------------------
class VersionedAPI:
    """Central coordinator for multi-version API support.

    Wires together resolution, transformation, deprecation, and response
    building into a single coherent interface.
    """

    def __init__(self, default_version: str = "v2"):
        self.default_version = default_version
        self.schemas: Dict[str, VersionSchema] = {}
        self.deprecation = DeprecationManager()
        self.transformer = SchemaTransformer()
        self.resolver: Optional[VersionResolver] = None
        self.response_builder = BackwardCompatibleResponse(
            self.transformer, current_version=default_version
        )

    def register_version(self, version: str, schema: VersionSchema,
                         sunset: Optional[str] = None,
                         deprecated: bool = False):
        """Register an API version with its schema and lifecycle info."""
        self.schemas[version] = schema
        self.deprecation.register(version, sunset_date=sunset,
                                  deprecated=deprecated)
        # Rebuild resolver with updated supported set
        self.resolver = VersionResolver(
            default_version=self.default_version,
            supported=set(self.schemas.keys()),
        )

    def register_mappings(self, from_version: str, to_version: str,
                          mappings: List[FieldMapping]):
        """Register field mappings between two versions."""
        self.transformer.add_mapping(from_version, to_version, mappings)

    def resolve(self, path: str, accept_header: Optional[str] = None,
                query_version: Optional[str] = None) -> VersionContext:
        """Resolve version and enrich with deprecation info."""
        if self.resolver is None:
            raise RuntimeError("No versions registered")
        ctx = self.resolver.resolve(path, accept_header, query_version)
        ctx.deprecated = self.deprecation.is_deprecated(ctx.version)
        ctx.sunset_date = self.deprecation.get_sunset_date(ctx.version)
        if ctx.deprecated:
            ctx.warnings.append(
                f"API version {ctx.version} is deprecated."
            )
        return ctx

    def transform(self, data: Dict[str, Any], from_version: str,
                  to_version: str) -> Dict[str, Any]:
        """Transform a payload between versions."""
        return self.transformer.transform(data, from_version, to_version)

    def build_response(self, data: Dict[str, Any],
                       target_version: str) -> Dict[str, Any]:
        """Build a backward-compatible response."""
        return self.response_builder.build(data, target_version)

    def get_headers(self, version: str) -> Dict[str, str]:
        """Get any deprecation/sunset headers for a version."""
        return self.deprecation.get_deprecation_headers(version)

    def list_versions(self) -> List[Dict[str, Any]]:
        """List all registered versions and their status."""
        return self.deprecation.list_versions()

    def apply_defaults(self, data: Dict[str, Any],
                       version: str) -> Dict[str, Any]:
        """Fill missing fields with schema defaults for a version."""
        schema = self.schemas.get(version)
        if schema is None:
            return data
        result = copy.deepcopy(data)
        for field_name, default in schema.defaults.items():
            if field_name not in result:
                result[field_name] = (
                    default() if callable(default) else copy.deepcopy(default)
                )
        return result

    def validate_required(self, data: Dict[str, Any],
                          version: str) -> List[str]:
        """Check for missing required fields. Returns list of errors."""
        schema = self.schemas.get(version)
        if schema is None:
            return []
        errors = []
        for req in schema.required:
            if req not in data:
                errors.append(f"Missing required field: {req}")
        return errors


# ---------------------------------------------------------------------------
# __main__ — assertions verifying correctness
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    # -- 1. Define schemas for v1 and v2 --

    schema_v1 = VersionSchema(
        version="v1",
        fields={
            "task_id": "int",
            "task_name": "str",
            "is_done": "bool",
            "quality": "int",
            "agent": "str",
        },
        required={"task_id", "task_name"},
        defaults={"is_done": False, "quality": 0, "agent": "executor"},
    )

    schema_v2 = VersionSchema(
        version="v2",
        fields={
            "id": "int",
            "title": "str",
            "status": "str",
            "quality_score": "float",
            "agent_name": "str",
            "priority": "str",
        },
        required={"id", "title"},
        defaults={
            "status": "pending",
            "quality_score": 0.0,
            "agent_name": "executor",
            "priority": "medium",
        },
        added_fields={"priority"},
    )

    schema_v3 = VersionSchema(
        version="v3",
        fields={
            "id": "int",
            "title": "str",
            "status": "str",
            "quality_score": "float",
            "agent_name": "str",
            "priority": "str",
            "tags": "list",
            "trace_id": "str",
        },
        required={"id", "title"},
        defaults={
            "status": "pending",
            "quality_score": 0.0,
            "agent_name": "executor",
            "priority": "medium",
            "tags": [],
            "trace_id": "",
        },
        added_fields={"tags", "trace_id"},
    )

    # -- 2. Register versions --

    api = VersionedAPI(default_version="v3")
    api.register_version("v1", schema_v1, sunset="2025-12-31",
                         deprecated=True)
    api.register_version("v2", schema_v2, sunset="2026-12-31")
    api.register_version("v3", schema_v3)

    # -- 3. Define field mappings --

    v1_to_v2_mappings = [
        FieldMapping(
            old_name="task_id", new_name="id",
        ),
        FieldMapping(
            old_name="task_name", new_name="title",
        ),
        FieldMapping(
            old_name="is_done", new_name="status",
            transform_up=lambda v: "completed" if v else "pending",
            transform_down=lambda v: v == "completed",
        ),
        FieldMapping(
            old_name="quality", new_name="quality_score",
            transform_up=lambda v: float(v),
            transform_down=lambda v: int(v),
        ),
        FieldMapping(
            old_name="agent", new_name="agent_name",
        ),
    ]

    v2_to_v3_mappings = [
        # v2 → v3 is additive: same fields, new ones get defaults
        # No renames needed — just pass through
    ]

    api.register_mappings("v1", "v2", v1_to_v2_mappings)
    api.register_mappings("v2", "v3", v2_to_v3_mappings)

    # -----------------------------------------------------------------------
    # TEST 1: Version resolution from URL path
    # -----------------------------------------------------------------------
    ctx = api.resolve("/v1/tasks")
    assert ctx.version == "v1", f"Expected v1, got {ctx.version}"
    assert ctx.major == 1
    assert ctx.deprecated is True, "v1 should be deprecated"
    assert ctx.sunset_date == "2025-12-31"
    assert any("deprecated" in w for w in ctx.warnings)
    print("[PASS] Test 1: URL path version resolution")

    ctx2 = api.resolve("/v2/tasks/123")
    assert ctx2.version == "v2"
    assert ctx2.major == 2
    print("[PASS] Test 1b: URL path v2 resolution")

    # -----------------------------------------------------------------------
    # TEST 2: Version resolution from Accept header
    # -----------------------------------------------------------------------
    ctx3 = api.resolve(
        "/tasks",
        accept_header="application/vnd.localagent.v2+json"
    )
    assert ctx3.version == "v2"
    print("[PASS] Test 2: Accept header version resolution")

    # -----------------------------------------------------------------------
    # TEST 3: Version resolution from query parameter
    # -----------------------------------------------------------------------
    ctx4 = api.resolve("/tasks", query_version="v1")
    assert ctx4.version == "v1"
    print("[PASS] Test 3: Query param version resolution")

    # -----------------------------------------------------------------------
    # TEST 4: Default version fallback
    # -----------------------------------------------------------------------
    ctx5 = api.resolve("/tasks")
    assert ctx5.version == "v3"
    print("[PASS] Test 4: Default version fallback to v3")

    # -----------------------------------------------------------------------
    # TEST 5: Unsupported version falls back to default
    # -----------------------------------------------------------------------
    ctx6 = api.resolve("/v99/tasks")
    assert ctx6.version == "v3"
    assert len(ctx6.warnings) > 0
    print("[PASS] Test 5: Unsupported version falls back to default")

    # -----------------------------------------------------------------------
    # TEST 6: Transform v1 payload → v2
    # -----------------------------------------------------------------------
    v1_payload = {
        "task_id": 42,
        "task_name": "Fix executor retry",
        "is_done": True,
        "quality": 85,
        "agent": "executor",
    }

    v2_result = api.transform(v1_payload, "v1", "v2")
    assert v2_result["id"] == 42
    assert v2_result["title"] == "Fix executor retry"
    assert v2_result["status"] == "completed"
    assert v2_result["quality_score"] == 85.0
    assert v2_result["agent_name"] == "executor"
    assert "task_id" not in v2_result, "Old field should be removed"
    print("[PASS] Test 6: v1 → v2 transformation")

    # -----------------------------------------------------------------------
    # TEST 7: Transform v2 payload → v1 (backward)
    # -----------------------------------------------------------------------
    v2_payload = {
        "id": 99,
        "title": "Add tracing",
        "status": "completed",
        "quality_score": 92.5,
        "agent_name": "architect",
        "priority": "high",
    }

    v1_result = api.transform(v2_payload, "v2", "v1")
    assert v1_result["task_id"] == 99
    assert v1_result["task_name"] == "Add tracing"
    assert v1_result["is_done"] is True
    assert v1_result["quality"] == 92
    assert v1_result["agent"] == "architect"
    # priority has no v1 equivalent, so it stays as-is
    print("[PASS] Test 7: v2 → v1 backward transformation")

    # -----------------------------------------------------------------------
    # TEST 8: Multi-hop transform v1 → v3
    # -----------------------------------------------------------------------
    v3_result = api.transform(v1_payload, "v1", "v3")
    assert v3_result["id"] == 42
    assert v3_result["title"] == "Fix executor retry"
    assert v3_result["status"] == "completed"
    assert v3_result["quality_score"] == 85.0
    print("[PASS] Test 8: Multi-hop v1 → v3 transformation")

    # -----------------------------------------------------------------------
    # TEST 9: Identity transform (same version)
    # -----------------------------------------------------------------------
    same = api.transform(v2_payload, "v2", "v2")
    assert same == v2_payload
    print("[PASS] Test 9: Identity transform (v2 → v2)")

    # -----------------------------------------------------------------------
    # TEST 10: Deprecation headers
    # -----------------------------------------------------------------------
    headers = api.get_headers("v1")
    assert headers["Deprecation"] == "true"
    assert "Sunset" in headers
    assert "successor-version" in headers["Link"]
    print("[PASS] Test 10: Deprecation headers for v1")

    headers_v3 = api.get_headers("v3")
    assert len(headers_v3) == 0, "v3 should have no deprecation headers"
    print("[PASS] Test 10b: No deprecation headers for v3 (active)")

    # -----------------------------------------------------------------------
    # TEST 11: Backward-compatible response builder
    # -----------------------------------------------------------------------
    api.response_builder.current_version = "v3"
    v3_data = {
        "id": 10,
        "title": "Deploy mesh",
        "status": "pending",
        "quality_score": 0.0,
        "agent_name": "architect",
        "priority": "high",
        "tags": ["infra"],
        "trace_id": "tr-abc",
    }

    # Build response for a v2 client
    compat_resp = api.build_response(v3_data, "v2")
    assert "_meta" in compat_resp
    assert compat_resp["_meta"]["api_version"] == "v2"
    assert "migration_notice" in compat_resp["_meta"]
    print("[PASS] Test 11: Backward-compatible response with _meta")

    # Build response for current version
    current_resp = api.build_response(v3_data, "v3")
    assert current_resp["_meta"]["api_version"] == "v3"
    assert "migration_notice" not in current_resp["_meta"]
    print("[PASS] Test 11b: Current version response (no migration notice)")

    # -----------------------------------------------------------------------
    # TEST 12: Schema defaults
    # -----------------------------------------------------------------------
    sparse = {"id": 1, "title": "Sparse task"}
    filled = api.apply_defaults(sparse, "v3")
    assert filled["status"] == "pending"
    assert filled["quality_score"] == 0.0
    assert filled["agent_name"] == "executor"
    assert filled["priority"] == "medium"
    assert filled["tags"] == []
    assert filled["trace_id"] == ""
    print("[PASS] Test 12: Schema defaults applied for v3")

    filled_v1 = api.apply_defaults({"task_id": 1, "task_name": "T"}, "v1")
    assert filled_v1["is_done"] is False
    assert filled_v1["quality"] == 0
    assert filled_v1["agent"] == "executor"
    print("[PASS] Test 12b: Schema defaults applied for v1")

    # -----------------------------------------------------------------------
    # TEST 13: Required field validation
    # -----------------------------------------------------------------------
    errors = api.validate_required({}, "v2")
    assert "Missing required field: id" in errors
    assert "Missing required field: title" in errors
    print("[PASS] Test 13: Required field validation catches missing fields")

    no_errors = api.validate_required({"id": 1, "title": "OK"}, "v2")
    assert len(no_errors) == 0
    print("[PASS] Test 13b: Valid payload passes required check")

    # -----------------------------------------------------------------------
    # TEST 14: List versions with status
    # -----------------------------------------------------------------------
    versions = api.list_versions()
    assert len(versions) == 3
    v1_info = next(v for v in versions if v["version"] == "v1")
    assert v1_info["status"] == "deprecated"
    v3_info = next(v for v in versions if v["version"] == "v3")
    assert v3_info["status"] == "active"
    print("[PASS] Test 14: Version listing with correct statuses")

    # -----------------------------------------------------------------------
    # TEST 15: Priority order — path > header > query > default
    # -----------------------------------------------------------------------
    ctx_priority = api.resolve(
        "/v1/tasks",
        accept_header="application/vnd.localagent.v2+json",
        query_version="v3",
    )
    assert ctx_priority.version == "v1", "Path should take priority"
    print("[PASS] Test 15: Version priority order (path > header > query)")

    # -----------------------------------------------------------------------
    # TEST 16: Transform preserves extra fields
    # -----------------------------------------------------------------------
    v1_with_extra = {
        "task_id": 7,
        "task_name": "Extra test",
        "is_done": False,
        "quality": 50,
        "agent": "planner",
        "custom_field": "should_survive",
    }
    v2_extra = api.transform(v1_with_extra, "v1", "v2")
    assert v2_extra["custom_field"] == "should_survive"
    print("[PASS] Test 16: Extra fields preserved during transformation")

    # -----------------------------------------------------------------------
    # TEST 17: SchemaTransformer — no path raises ValueError
    # -----------------------------------------------------------------------
    isolated = SchemaTransformer()
    try:
        isolated.transform({"x": 1}, "v10", "v20")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "No transformation path" in str(e)
    print("[PASS] Test 17: Missing path raises ValueError")

    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("ALL 17 TESTS PASSED — API versioning is correct")
    print("=" * 60)
