import sqlite3
import os

DB_PATH = ":memory:"

_connection = None

def get_connection():
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(DB_PATH)
        _connection.row_factory = sqlite3.Row
    return _connection


class Field:
    PYTHON_TO_SQL = {
        int: "INTEGER",
        float: "REAL",
        str: "TEXT",
        bool: "INTEGER",
        bytes: "BLOB",
    }

    def __init__(self, field_type=str, required=False, default=None):
        self.field_type = field_type
        self.required = required
        self.default = default
        self.name = None  # set by metaclass

    @property
    def sql_type(self):
        return self.PYTHON_TO_SQL.get(self.field_type, "TEXT")


class ModelMeta(type):
    def __new__(mcs, name, bases, namespace):
        fields = {}
        for key, value in list(namespace.items()):
            if isinstance(value, Field):
                value.name = key
                fields[key] = value
        for base in bases:
            if hasattr(base, "_fields"):
                for k, v in base._fields.items():
                    fields.setdefault(k, v)

        namespace["_fields"] = fields
        namespace["_table_name"] = name.lower()
        cls = super().__new__(mcs, name, bases, namespace)
        return cls


class Model(metaclass=ModelMeta):
    def __init__(self, **kwargs):
        for field_name, field in self._fields.items():
            if field_name in kwargs:
                value = kwargs[field_name]
                if value is not None and not isinstance(value, field.field_type):
                    value = field.field_type(value)
                setattr(self, field_name, value)
            elif field.default is not None:
                default = field.default() if callable(field.default) else field.default
                setattr(self, field_name, default)
            elif field.required:
                raise ValueError(f"Field '{field_name}' is required for {self.__class__.__name__}")
            else:
                setattr(self, field_name, None)
        self.id = kwargs.get("id", None)

    @classmethod
    def _create_table(cls):
        conn = get_connection()
        cols = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for name, field in cls._fields.items():
            col = f"{name} {field.sql_type}"
            if field.required:
                col += " NOT NULL"
            if field.default is not None and not callable(field.default):
                default = field.default
                if isinstance(default, str):
                    default = f"'{default}'"
                col += f" DEFAULT {default}"
            cols.append(col)
        sql = f"CREATE TABLE IF NOT EXISTS {cls._table_name} ({', '.join(cols)})"
        conn.execute(sql)
        conn.commit()

    def save(self):
        conn = get_connection()
        field_names = list(self._fields.keys())
        values = [getattr(self, f) for f in field_names]

        if self.id is None:
            placeholders = ", ".join(["?"] * len(field_names))
            cols = ", ".join(field_names)
            sql = f"INSERT INTO {self._table_name} ({cols}) VALUES ({placeholders})"
            cursor = conn.execute(sql, values)
            self.id = cursor.lastrowid
        else:
            set_clause = ", ".join([f"{f} = ?" for f in field_names])
            sql = f"UPDATE {self._table_name} SET {set_clause} WHERE id = ?"
            conn.execute(sql, values + [self.id])
        conn.commit()
        return self

    def delete(self):
        if self.id is None:
            raise ValueError("Cannot delete unsaved instance")
        conn = get_connection()
        conn.execute(f"DELETE FROM {self._table_name} WHERE id = ?", (self.id,))
        conn.commit()
        self.id = None

    @classmethod
    def find(cls, **kwargs):
        conn = get_connection()
        if kwargs:
            conditions = " AND ".join([f"{k} = ?" for k in kwargs])
            values = list(kwargs.values())
            sql = f"SELECT * FROM {cls._table_name} WHERE {conditions}"
            rows = conn.execute(sql, values).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM {cls._table_name}").fetchall()
        results = []
        for row in rows:
            data = dict(row)
            obj_id = data.pop("id")
            obj = cls(**data)
            obj.id = obj_id
            results.append(obj)
        return results

    @classmethod
    def find_one(cls, **kwargs):
        results = cls.find(**kwargs)
        return results[0] if results else None

    def __repr__(self):
        fields = ", ".join(f"{k}={getattr(self, k)!r}" for k in self._fields)
        return f"{self.__class__.__name__}(id={self.id}, {fields})"


# --- Define models ---

class User(Model):
    username = Field(str, required=True)
    email = Field(str, required=True)
    age = Field(int, default=0)


class Post(Model):
    title = Field(str, required=True)
    body = Field(str, default="")
    user_id = Field(int, required=True)


if __name__ == "__main__":
    # Create tables
    User._create_table()
    Post._create_table()

    # --- Test Field definitions ---
    assert "username" in User._fields
    assert "email" in User._fields
    assert "age" in User._fields
    assert User._fields["username"].required is True
    assert User._fields["age"].default == 0
    assert User._table_name == "user"
    assert Post._table_name == "post"

    # --- Test save (insert) ---
    alice = User(username="alice", email="alice@example.com", age=30)
    assert alice.id is None
    alice.save()
    assert alice.id is not None
    assert alice.id == 1

    bob = User(username="bob", email="bob@example.com")
    bob.save()
    assert bob.id == 2
    assert bob.age == 0  # default

    # --- Test find all ---
    users = User.find()
    assert len(users) == 2
    assert users[0].username == "alice"
    assert users[1].username == "bob"

    # --- Test find with filter ---
    results = User.find(username="alice")
    assert len(results) == 1
    assert results[0].email == "alice@example.com"
    assert results[0].age == 30

    # --- Test find_one ---
    found = User.find_one(username="bob")
    assert found is not None
    assert found.email == "bob@example.com"

    not_found = User.find_one(username="charlie")
    assert not_found is None

    # --- Test save (update) ---
    alice = User.find_one(username="alice")
    alice.age = 31
    alice.save()
    updated = User.find_one(username="alice")
    assert updated.age == 31

    # --- Test Post model with foreign key ---
    post1 = Post(title="Hello World", body="First post!", user_id=alice.id)
    post1.save()
    assert post1.id == 1

    post2 = Post(title="Second", body="Another post", user_id=alice.id)
    post2.save()

    post3 = Post(title="Bob's Post", body="Hi from Bob", user_id=bob.id)
    post3.save()

    # --- Test find posts by user ---
    alice_posts = Post.find(user_id=alice.id)
    assert len(alice_posts) == 2

    bob_posts = Post.find(user_id=bob.id)
    assert len(bob_posts) == 1
    assert bob_posts[0].title == "Bob's Post"

    # --- Test delete ---
    post3.delete()
    assert post3.id is None
    bob_posts = Post.find(user_id=bob.id)
    assert len(bob_posts) == 0

    all_posts = Post.find()
    assert len(all_posts) == 2

    # --- Test required field validation ---
    try:
        User(email="no_username@example.com")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "required" in str(e).lower()

    # --- Test delete unsaved raises ---
    try:
        User(username="tmp", email="tmp@example.com").delete()
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    # --- Test repr ---
    r = repr(alice)
    assert "User" in r
    assert "alice" in r

    print("All assertions passed.")
