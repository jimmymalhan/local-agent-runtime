"""TDD tests for an RBAC Permissions system."""


class Permissions:
    """Role-Based Access Control permissions system."""

    def __init__(self, roles: dict, resources: list):
        self.roles = roles
        self.resources = resources

    def check(self, user: dict, action: str, resource: str) -> bool:
        role = user.get("role")
        if role not in self.roles:
            return False
        if resource not in self.resources:
            return False
        allowed_actions = self.roles.get(role, [])
        return action in allowed_actions


def make_permissions():
    roles = {
        "admin": ["read", "write", "delete"],
        "editor": ["read", "write"],
        "viewer": ["read"],
    }
    resources = ["document", "image", "video"]
    return Permissions(roles, resources)


def test_admin_can_read():
    p = make_permissions()
    assert p.check({"role": "admin"}, "read", "document") is True


def test_admin_can_write():
    p = make_permissions()
    assert p.check({"role": "admin"}, "write", "document") is True


def test_admin_can_delete():
    p = make_permissions()
    assert p.check({"role": "admin"}, "delete", "document") is True


def test_editor_can_read():
    p = make_permissions()
    assert p.check({"role": "editor"}, "read", "document") is True


def test_editor_can_write():
    p = make_permissions()
    assert p.check({"role": "editor"}, "write", "image") is True


def test_editor_cannot_delete():
    p = make_permissions()
    assert p.check({"role": "editor"}, "delete", "document") is False


def test_viewer_can_read():
    p = make_permissions()
    assert p.check({"role": "viewer"}, "read", "video") is True


def test_viewer_cannot_write():
    p = make_permissions()
    assert p.check({"role": "viewer"}, "write", "document") is False


def test_viewer_cannot_delete():
    p = make_permissions()
    assert p.check({"role": "viewer"}, "delete", "document") is False


def test_unknown_role_denied():
    p = make_permissions()
    assert p.check({"role": "guest"}, "read", "document") is False


def test_unknown_resource_denied():
    p = make_permissions()
    assert p.check({"role": "admin"}, "read", "secret") is False


def test_unknown_action_denied():
    p = make_permissions()
    assert p.check({"role": "admin"}, "execute", "document") is False


def test_missing_role_key_denied():
    p = make_permissions()
    assert p.check({}, "read", "document") is False


def test_all_roles_across_all_resources():
    p = make_permissions()
    resources = ["document", "image", "video"]
    for resource in resources:
        assert p.check({"role": "admin"}, "read", resource) is True
        assert p.check({"role": "admin"}, "write", resource) is True
        assert p.check({"role": "admin"}, "delete", resource) is True
        assert p.check({"role": "editor"}, "read", resource) is True
        assert p.check({"role": "editor"}, "write", resource) is True
        assert p.check({"role": "editor"}, "delete", resource) is False
        assert p.check({"role": "viewer"}, "read", resource) is True
        assert p.check({"role": "viewer"}, "write", resource) is False
        assert p.check({"role": "viewer"}, "delete", resource) is False


def test_empty_roles():
    p = Permissions({}, ["document"])
    assert p.check({"role": "admin"}, "read", "document") is False


def test_empty_resources():
    p = Permissions({"admin": ["read"]}, [])
    assert p.check({"role": "admin"}, "read", "document") is False


def test_role_with_no_permissions():
    p = Permissions({"intern": []}, ["document"])
    assert p.check({"role": "intern"}, "read", "document") is False


if __name__ == "__main__":
    tests = [
        test_admin_can_read,
        test_admin_can_write,
        test_admin_can_delete,
        test_editor_can_read,
        test_editor_can_write,
        test_editor_cannot_delete,
        test_viewer_can_read,
        test_viewer_cannot_write,
        test_viewer_cannot_delete,
        test_unknown_role_denied,
        test_unknown_resource_denied,
        test_unknown_action_denied,
        test_missing_role_key_denied,
        test_all_roles_across_all_resources,
        test_empty_roles,
        test_empty_resources,
        test_role_with_no_permissions,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")
