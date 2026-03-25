"""Dependency Injection Container with singleton support and circular dependency detection."""

from typing import Any, Callable, Dict, Set


class CircularDependencyError(Exception):
    pass


class DependencyNotFoundError(Exception):
    pass


class DIContainer:
    def __init__(self) -> None:
        self._factories: Dict[str, Callable[["DIContainer"], Any]] = {}
        self._singletons: Dict[str, Any] = {}
        self._singleton_flags: Dict[str, bool] = {}
        self._resolving: Set[str] = set()

    def register(
        self,
        name: str,
        factory: Callable[["DIContainer"], Any],
        singleton: bool = False,
    ) -> None:
        self._factories[name] = factory
        self._singleton_flags[name] = singleton
        if name in self._singletons:
            del self._singletons[name]

    def resolve(self, name: str) -> Any:
        if name not in self._factories:
            raise DependencyNotFoundError(f"No registration found for '{name}'")

        if name in self._singletons:
            return self._singletons[name]

        if name in self._resolving:
            chain = " -> ".join(self._resolving) + f" -> {name}"
            raise CircularDependencyError(f"Circular dependency detected: {chain}")

        self._resolving.add(name)
        try:
            instance = self._factories[name](self)
        finally:
            self._resolving.discard(name)

        if self._singleton_flags.get(name, False):
            self._singletons[name] = instance

        return instance


# --- 3-layer service architecture for testing ---

class DatabaseConnection:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.connected = True

    def query(self, sql: str) -> str:
        return f"Result of '{sql}' on {self.connection_string}"


class UserRepository:
    """Data-access layer (layer 1)."""
    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db

    def find_user(self, user_id: int) -> dict:
        raw = self.db.query(f"SELECT * FROM users WHERE id={user_id}")
        return {"id": user_id, "data": raw}


class AuthService:
    """Business-logic layer (layer 2)."""
    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    def authenticate(self, user_id: int, token: str) -> dict:
        user = self.user_repo.find_user(user_id)
        user["authenticated"] = token == "valid-token"
        return user


class ApiController:
    """Presentation layer (layer 3)."""
    def __init__(self, auth_service: AuthService) -> None:
        self.auth_service = auth_service

    def handle_login(self, user_id: int, token: str) -> dict:
        result = self.auth_service.authenticate(user_id, token)
        return {"status": "ok" if result["authenticated"] else "denied", "user": result}


if __name__ == "__main__":
    # --- Basic registration and resolution ---
    container = DIContainer()

    container.register("db", lambda c: DatabaseConnection("postgres://localhost/app"))
    container.register("user_repo", lambda c: UserRepository(c.resolve("db")))
    container.register("auth_service", lambda c: AuthService(c.resolve("user_repo")))
    container.register("api_controller", lambda c: ApiController(c.resolve("auth_service")))

    ctrl = container.resolve("api_controller")
    resp = ctrl.handle_login(1, "valid-token")
    assert resp["status"] == "ok", f"Expected 'ok', got {resp['status']}"
    assert resp["user"]["id"] == 1
    assert resp["user"]["authenticated"] is True

    resp2 = ctrl.handle_login(2, "bad-token")
    assert resp2["status"] == "denied"
    assert resp2["user"]["authenticated"] is False

    # --- Singleton support ---
    container2 = DIContainer()
    container2.register("db", lambda c: DatabaseConnection("postgres://localhost/app"), singleton=True)
    container2.register("user_repo", lambda c: UserRepository(c.resolve("db")))

    repo_a = container2.resolve("user_repo")
    repo_b = container2.resolve("user_repo")
    # Repos are different instances (not singleton)
    assert repo_a is not repo_b
    # But they share the same DB connection (singleton)
    assert repo_a.db is repo_b.db

    # Non-singleton produces different instances
    container3 = DIContainer()
    container3.register("db", lambda c: DatabaseConnection("postgres://localhost/app"), singleton=False)
    db1 = container3.resolve("db")
    db2 = container3.resolve("db")
    assert db1 is not db2

    # --- Circular dependency detection ---
    container4 = DIContainer()
    container4.register("a", lambda c: c.resolve("b"))
    container4.register("b", lambda c: c.resolve("c"))
    container4.register("c", lambda c: c.resolve("a"))

    try:
        container4.resolve("a")
        assert False, "Should have raised CircularDependencyError"
    except CircularDependencyError as e:
        assert "Circular dependency detected" in str(e)

    # --- Dependency not found ---
    try:
        container.resolve("nonexistent")
        assert False, "Should have raised DependencyNotFoundError"
    except DependencyNotFoundError as e:
        assert "nonexistent" in str(e)

    # --- Re-registration clears cached singleton ---
    container5 = DIContainer()
    container5.register("db", lambda c: DatabaseConnection("old://host"), singleton=True)
    old_db = container5.resolve("db")
    assert old_db.connection_string == "old://host"

    container5.register("db", lambda c: DatabaseConnection("new://host"), singleton=True)
    new_db = container5.resolve("db")
    assert new_db.connection_string == "new://host"
    assert old_db is not new_db

    print("All assertions passed.")
