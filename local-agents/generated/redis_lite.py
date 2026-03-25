"""
RedisLite: Thread-safe in-memory key-value store with Redis-like commands.
Supports: SET/GET/DEL, EXPIRE/TTL, LPUSH/LPOP/LRANGE, HSET/HGET/HGETALL.
"""

import threading
import time
from collections import OrderedDict


class RedisLite:
    def __init__(self):
        self._data = {}
        self._expires = {}
        self._lock = threading.RLock()

    def _is_expired(self, key):
        if key in self._expires:
            if time.monotonic() >= self._expires[key]:
                del self._data[key]
                del self._expires[key]
                return True
        return False

    def _check_type(self, key, expected_type):
        if key in self._data and not isinstance(self._data[key], expected_type):
            raise TypeError(f"WRONGTYPE Operation against a key holding the wrong kind of value")

    # ── String commands ──

    def set(self, key, value, ex=None, px=None):
        with self._lock:
            self._data[key] = str(value)
            if ex is not None:
                self._expires[key] = time.monotonic() + ex
            elif px is not None:
                self._expires[key] = time.monotonic() + px / 1000.0
            else:
                self._expires.pop(key, None)
            return True

    def get(self, key):
        with self._lock:
            if self._is_expired(key):
                return None
            val = self._data.get(key)
            if val is not None and not isinstance(val, str):
                raise TypeError("WRONGTYPE Operation against a key holding the wrong kind of value")
            return val

    def delete(self, *keys):
        with self._lock:
            count = 0
            for key in keys:
                self._is_expired(key)
                if key in self._data:
                    del self._data[key]
                    self._expires.pop(key, None)
                    count += 1
            return count

    def exists(self, *keys):
        with self._lock:
            count = 0
            for key in keys:
                if not self._is_expired(key) and key in self._data:
                    count += 1
            return count

    def keys(self, pattern=None):
        with self._lock:
            result = []
            for key in list(self._data.keys()):
                if not self._is_expired(key):
                    if pattern is None or pattern == "*":
                        result.append(key)
            return result

    def flushall(self):
        with self._lock:
            self._data.clear()
            self._expires.clear()
            return True

    # ── Expiry commands ──

    def expire(self, key, seconds):
        with self._lock:
            if self._is_expired(key):
                return False
            if key not in self._data:
                return False
            self._expires[key] = time.monotonic() + seconds
            return True

    def pexpire(self, key, milliseconds):
        return self.expire(key, milliseconds / 1000.0)

    def ttl(self, key):
        with self._lock:
            if self._is_expired(key):
                return -2
            if key not in self._data:
                return -2
            if key not in self._expires:
                return -1
            remaining = self._expires[key] - time.monotonic()
            if remaining <= 0:
                self._is_expired(key)
                return -2
            return int(remaining) if remaining >= 1 else 0

    def pttl(self, key):
        with self._lock:
            if self._is_expired(key):
                return -2
            if key not in self._data:
                return -2
            if key not in self._expires:
                return -1
            remaining = self._expires[key] - time.monotonic()
            if remaining <= 0:
                self._is_expired(key)
                return -2
            return int(remaining * 1000)

    def persist(self, key):
        with self._lock:
            if self._is_expired(key):
                return False
            if key not in self._data:
                return False
            if key in self._expires:
                del self._expires[key]
                return True
            return False

    # ── Numeric commands ──

    def incr(self, key):
        return self.incrby(key, 1)

    def decr(self, key):
        return self.incrby(key, -1)

    def incrby(self, key, amount):
        with self._lock:
            self._is_expired(key)
            if key not in self._data:
                self._data[key] = "0"
            self._check_type(key, str)
            try:
                val = int(self._data[key]) + amount
            except ValueError:
                raise ValueError("ERR value is not an integer or out of range")
            self._data[key] = str(val)
            return val

    # ── List commands ──

    def lpush(self, key, *values):
        with self._lock:
            self._is_expired(key)
            if key not in self._data:
                self._data[key] = []
            self._check_type(key, list)
            for v in values:
                self._data[key].insert(0, str(v))
            return len(self._data[key])

    def rpush(self, key, *values):
        with self._lock:
            self._is_expired(key)
            if key not in self._data:
                self._data[key] = []
            self._check_type(key, list)
            for v in values:
                self._data[key].append(str(v))
            return len(self._data[key])

    def lpop(self, key):
        with self._lock:
            if self._is_expired(key):
                return None
            if key not in self._data:
                return None
            self._check_type(key, list)
            lst = self._data[key]
            if not lst:
                return None
            val = lst.pop(0)
            if not lst:
                del self._data[key]
                self._expires.pop(key, None)
            return val

    def rpop(self, key):
        with self._lock:
            if self._is_expired(key):
                return None
            if key not in self._data:
                return None
            self._check_type(key, list)
            lst = self._data[key]
            if not lst:
                return None
            val = lst.pop()
            if not lst:
                del self._data[key]
                self._expires.pop(key, None)
            return val

    def lrange(self, key, start, stop):
        with self._lock:
            if self._is_expired(key):
                return []
            if key not in self._data:
                return []
            self._check_type(key, list)
            lst = self._data[key]
            length = len(lst)
            if start < 0:
                start = max(length + start, 0)
            if stop < 0:
                stop = length + stop
            stop = min(stop, length - 1)
            if start > stop:
                return []
            return lst[start:stop + 1]

    def llen(self, key):
        with self._lock:
            if self._is_expired(key):
                return 0
            if key not in self._data:
                return 0
            self._check_type(key, list)
            return len(self._data[key])

    # ── Hash commands ──

    def hset(self, key, field, value):
        with self._lock:
            self._is_expired(key)
            if key not in self._data:
                self._data[key] = {}
            self._check_type(key, dict)
            is_new = field not in self._data[key]
            self._data[key][field] = str(value)
            return 1 if is_new else 0

    def hget(self, key, field):
        with self._lock:
            if self._is_expired(key):
                return None
            if key not in self._data:
                return None
            self._check_type(key, dict)
            return self._data[key].get(field)

    def hgetall(self, key):
        with self._lock:
            if self._is_expired(key):
                return {}
            if key not in self._data:
                return {}
            self._check_type(key, dict)
            return dict(self._data[key])

    def hdel(self, key, *fields):
        with self._lock:
            if self._is_expired(key):
                return 0
            if key not in self._data:
                return 0
            self._check_type(key, dict)
            count = 0
            for f in fields:
                if f in self._data[key]:
                    del self._data[key][f]
                    count += 1
            if not self._data[key]:
                del self._data[key]
                self._expires.pop(key, None)
            return count

    def hexists(self, key, field):
        with self._lock:
            if self._is_expired(key):
                return False
            if key not in self._data:
                return False
            self._check_type(key, dict)
            return field in self._data[key]

    def hlen(self, key):
        with self._lock:
            if self._is_expired(key):
                return 0
            if key not in self._data:
                return 0
            self._check_type(key, dict)
            return len(self._data[key])

    # ── Utility ──

    def type(self, key):
        with self._lock:
            if self._is_expired(key):
                return "none"
            if key not in self._data:
                return "none"
            val = self._data[key]
            if isinstance(val, str):
                return "string"
            if isinstance(val, list):
                return "list"
            if isinstance(val, dict):
                return "hash"
            return "none"

    def dbsize(self):
        with self._lock:
            for key in list(self._data.keys()):
                self._is_expired(key)
            return len(self._data)


# ── Tests ──

import unittest


class TestRedisLiteStrings(unittest.TestCase):
    def setUp(self):
        self.r = RedisLite()

    def test_set_get(self):
        self.r.set("name", "alice")
        assert self.r.get("name") == "alice"

    def test_get_missing(self):
        assert self.r.get("nope") is None

    def test_set_overwrite(self):
        self.r.set("k", "v1")
        self.r.set("k", "v2")
        assert self.r.get("k") == "v2"

    def test_delete(self):
        self.r.set("k", "v")
        assert self.r.delete("k") == 1
        assert self.r.get("k") is None

    def test_delete_missing(self):
        assert self.r.delete("nope") == 0

    def test_delete_multiple(self):
        self.r.set("a", "1")
        self.r.set("b", "2")
        assert self.r.delete("a", "b", "c") == 2

    def test_exists(self):
        self.r.set("k", "v")
        assert self.r.exists("k") == 1
        assert self.r.exists("nope") == 0

    def test_incr_decr(self):
        self.r.set("counter", "10")
        assert self.r.incr("counter") == 11
        assert self.r.decr("counter") == 10
        assert self.r.incrby("counter", 5) == 15

    def test_incr_new_key(self):
        assert self.r.incr("new") == 1

    def test_incr_non_integer(self):
        self.r.set("k", "abc")
        with self.assertRaises(ValueError):
            self.r.incr("k")

    def test_type_string(self):
        self.r.set("k", "v")
        assert self.r.type("k") == "string"

    def test_type_missing(self):
        assert self.r.type("nope") == "none"

    def test_dbsize(self):
        self.r.set("a", "1")
        self.r.set("b", "2")
        assert self.r.dbsize() == 2

    def test_flushall(self):
        self.r.set("a", "1")
        self.r.flushall()
        assert self.r.dbsize() == 0

    def test_keys(self):
        self.r.set("a", "1")
        self.r.set("b", "2")
        assert sorted(self.r.keys()) == ["a", "b"]


class TestRedisLiteExpiry(unittest.TestCase):
    def setUp(self):
        self.r = RedisLite()

    def test_set_with_ex(self):
        self.r.set("k", "v", ex=10)
        assert self.r.get("k") == "v"
        ttl = self.r.ttl("k")
        assert 0 <= ttl <= 10

    def test_expire(self):
        self.r.set("k", "v")
        assert self.r.ttl("k") == -1
        self.r.expire("k", 10)
        assert 0 <= self.r.ttl("k") <= 10

    def test_ttl_missing(self):
        assert self.r.ttl("nope") == -2

    def test_ttl_no_expiry(self):
        self.r.set("k", "v")
        assert self.r.ttl("k") == -1

    def test_persist(self):
        self.r.set("k", "v", ex=10)
        assert self.r.persist("k") is True
        assert self.r.ttl("k") == -1

    def test_persist_no_expiry(self):
        self.r.set("k", "v")
        assert self.r.persist("k") is False

    def test_persist_missing(self):
        assert self.r.persist("nope") is False

    def test_expire_missing(self):
        assert self.r.expire("nope", 10) is False

    def test_key_expires(self):
        self.r.set("k", "v", px=50)
        time.sleep(0.1)
        assert self.r.get("k") is None
        assert self.r.ttl("k") == -2

    def test_pttl(self):
        self.r.set("k", "v", ex=10)
        pttl = self.r.pttl("k")
        assert 0 < pttl <= 10000

    def test_pttl_missing(self):
        assert self.r.pttl("nope") == -2

    def test_pttl_no_expiry(self):
        self.r.set("k", "v")
        assert self.r.pttl("k") == -1

    def test_set_ex_clears_old_expiry(self):
        self.r.set("k", "v", ex=5)
        self.r.set("k", "v2")
        assert self.r.ttl("k") == -1


class TestRedisLiteLists(unittest.TestCase):
    def setUp(self):
        self.r = RedisLite()

    def test_lpush_lpop(self):
        self.r.lpush("list", "a", "b", "c")
        assert self.r.lpop("list") == "c"
        assert self.r.lpop("list") == "b"
        assert self.r.lpop("list") == "a"
        assert self.r.lpop("list") is None

    def test_rpush_rpop(self):
        self.r.rpush("list", "a", "b", "c")
        assert self.r.rpop("list") == "c"
        assert self.r.rpop("list") == "b"

    def test_lrange(self):
        self.r.rpush("list", "a", "b", "c", "d")
        assert self.r.lrange("list", 0, -1) == ["a", "b", "c", "d"]
        assert self.r.lrange("list", 1, 2) == ["b", "c"]
        assert self.r.lrange("list", 0, 0) == ["a"]

    def test_lrange_negative_indices(self):
        self.r.rpush("list", "a", "b", "c")
        assert self.r.lrange("list", -2, -1) == ["b", "c"]

    def test_lrange_out_of_bounds(self):
        self.r.rpush("list", "a", "b")
        assert self.r.lrange("list", 0, 100) == ["a", "b"]

    def test_lrange_empty(self):
        assert self.r.lrange("nope", 0, -1) == []

    def test_llen(self):
        self.r.rpush("list", "a", "b", "c")
        assert self.r.llen("list") == 3

    def test_llen_missing(self):
        assert self.r.llen("nope") == 0

    def test_lpop_empty(self):
        assert self.r.lpop("nope") is None

    def test_rpop_empty(self):
        assert self.r.rpop("nope") is None

    def test_lpush_return_length(self):
        assert self.r.lpush("list", "a") == 1
        assert self.r.lpush("list", "b") == 2

    def test_type_list(self):
        self.r.lpush("list", "a")
        assert self.r.type("list") == "list"

    def test_wrongtype_get_on_list(self):
        self.r.lpush("list", "a")
        with self.assertRaises(TypeError):
            self.r.get("list")

    def test_wrongtype_lpush_on_string(self):
        self.r.set("k", "v")
        with self.assertRaises(TypeError):
            self.r.lpush("k", "a")

    def test_auto_delete_empty_list(self):
        self.r.lpush("list", "a")
        self.r.lpop("list")
        assert self.r.exists("list") == 0


class TestRedisLiteHashes(unittest.TestCase):
    def setUp(self):
        self.r = RedisLite()

    def test_hset_hget(self):
        self.r.hset("user", "name", "alice")
        assert self.r.hget("user", "name") == "alice"

    def test_hget_missing_key(self):
        assert self.r.hget("nope", "field") is None

    def test_hget_missing_field(self):
        self.r.hset("user", "name", "alice")
        assert self.r.hget("user", "nope") is None

    def test_hgetall(self):
        self.r.hset("user", "name", "alice")
        self.r.hset("user", "age", "30")
        assert self.r.hgetall("user") == {"name": "alice", "age": "30"}

    def test_hgetall_missing(self):
        assert self.r.hgetall("nope") == {}

    def test_hdel(self):
        self.r.hset("user", "name", "alice")
        self.r.hset("user", "age", "30")
        assert self.r.hdel("user", "name") == 1
        assert self.r.hget("user", "name") is None
        assert self.r.hget("user", "age") == "30"

    def test_hdel_missing_field(self):
        self.r.hset("user", "name", "alice")
        assert self.r.hdel("user", "nope") == 0

    def test_hdel_missing_key(self):
        assert self.r.hdel("nope", "field") == 0

    def test_hexists(self):
        self.r.hset("user", "name", "alice")
        assert self.r.hexists("user", "name") is True
        assert self.r.hexists("user", "nope") is False

    def test_hlen(self):
        self.r.hset("user", "name", "alice")
        self.r.hset("user", "age", "30")
        assert self.r.hlen("user") == 2

    def test_hlen_missing(self):
        assert self.r.hlen("nope") == 0

    def test_hset_returns_new(self):
        assert self.r.hset("user", "name", "alice") == 1
        assert self.r.hset("user", "name", "bob") == 0

    def test_type_hash(self):
        self.r.hset("user", "name", "alice")
        assert self.r.type("user") == "hash"

    def test_wrongtype_hset_on_string(self):
        self.r.set("k", "v")
        with self.assertRaises(TypeError):
            self.r.hset("k", "f", "v")

    def test_auto_delete_empty_hash(self):
        self.r.hset("h", "f", "v")
        self.r.hdel("h", "f")
        assert self.r.exists("h") == 0

    def test_delete_hash(self):
        self.r.hset("user", "name", "alice")
        self.r.delete("user")
        assert self.r.hgetall("user") == {}

    def test_expire_hash(self):
        self.r.hset("user", "name", "alice")
        self.r.expire("user", 10)
        assert self.r.hget("user", "name") == "alice"


class TestRedisLiteThreadSafety(unittest.TestCase):
    def test_concurrent_incr(self):
        r = RedisLite()
        r.set("counter", "0")
        threads = []
        for _ in range(100):
            t = threading.Thread(target=lambda: [r.incr("counter") for _ in range(100)])
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert r.get("counter") == "10000"

    def test_concurrent_lpush_lpop(self):
        r = RedisLite()
        results = []

        def push_work():
            for i in range(50):
                r.lpush("q", str(i))

        def pop_work():
            popped = []
            for _ in range(50):
                val = r.lpop("q")
                if val is not None:
                    popped.append(val)
            results.append(popped)

        pushers = [threading.Thread(target=push_work) for _ in range(4)]
        for t in pushers:
            t.start()
        for t in pushers:
            t.join()

        assert r.llen("q") == 200

        poppers = [threading.Thread(target=pop_work) for _ in range(4)]
        for t in poppers:
            t.start()
        for t in poppers:
            t.join()

        total_popped = sum(len(p) for p in results)
        assert total_popped == 200

    def test_concurrent_hset(self):
        r = RedisLite()

        def hset_work(thread_id):
            for i in range(100):
                r.hset("hash", f"t{thread_id}_f{i}", str(i))

        threads = [threading.Thread(target=hset_work, args=(tid,)) for tid in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert r.hlen("hash") == 1000


if __name__ == "__main__":
    # Quick smoke test with assertions
    r = RedisLite()

    # SET/GET/DEL
    r.set("hello", "world")
    assert r.get("hello") == "world"
    assert r.delete("hello") == 1
    assert r.get("hello") is None

    # EXPIRE/TTL
    r.set("temp", "data", ex=10)
    assert r.get("temp") == "data"
    assert 0 <= r.ttl("temp") <= 10
    r.persist("temp")
    assert r.ttl("temp") == -1

    # LPUSH/LPOP/LRANGE
    r.lpush("mylist", "a", "b", "c")
    assert r.lrange("mylist", 0, -1) == ["c", "b", "a"]
    assert r.lpop("mylist") == "c"
    assert r.lrange("mylist", 0, -1) == ["b", "a"]

    # HSET/HGET/HGETALL
    r.hset("user:1", "name", "Alice")
    r.hset("user:1", "age", "30")
    assert r.hget("user:1", "name") == "Alice"
    assert r.hgetall("user:1") == {"name": "Alice", "age": "30"}

    # Thread safety
    r.set("counter", "0")
    threads = []
    for _ in range(10):
        t = threading.Thread(target=lambda: [r.incr("counter") for _ in range(1000)])
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert r.get("counter") == "10000"

    print("All assertions passed.")

    # Run full test suite
    unittest.main(argv=[""], exit=True, verbosity=2)
