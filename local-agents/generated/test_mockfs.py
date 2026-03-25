"""TDD tests for MockFS: a mock file system."""

import unittest


class MockFS:
    """In-memory mock file system supporting files and directories."""

    def __init__(self):
        # Store entries: path -> content (str) for files, path -> None for directories
        self._files = {}
        self._dirs = {"/"}

    def _parent(self, path: str) -> str:
        parts = path.rsplit("/", 1)
        return parts[0] if parts[0] else "/"

    def _ensure_parent_exists(self, path: str):
        parent = self._parent(path)
        if parent not in self._dirs:
            raise FileNotFoundError(f"Parent directory not found: {parent}")

    def mkdir(self, path: str):
        if path in self._dirs:
            raise FileExistsError(f"Directory already exists: {path}")
        if path in self._files:
            raise FileExistsError(f"A file already exists at: {path}")
        self._ensure_parent_exists(path)
        self._dirs.add(path)

    def create_file(self, path: str, content: str = ""):
        if path in self._dirs:
            raise IsADirectoryError(f"Is a directory: {path}")
        if path in self._files:
            raise FileExistsError(f"File already exists: {path}")
        self._ensure_parent_exists(path)
        self._files[path] = content

    def read_file(self, path: str) -> str:
        if path in self._dirs:
            raise IsADirectoryError(f"Is a directory: {path}")
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        return self._files[path]

    def write_file(self, path: str, content: str):
        if path in self._dirs:
            raise IsADirectoryError(f"Is a directory: {path}")
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        self._files[path] = content

    def delete_file(self, path: str):
        if path in self._dirs:
            raise IsADirectoryError(f"Is a directory: {path}")
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        del self._files[path]

    def list_dir(self, path: str) -> list[str]:
        if path in self._files:
            raise NotADirectoryError(f"Not a directory: {path}")
        if path not in self._dirs:
            raise FileNotFoundError(f"Directory not found: {path}")
        prefix = path if path == "/" else path + "/"
        entries = []
        for f in self._files:
            if f.startswith(prefix) and "/" not in f[len(prefix):]:
                entries.append(f[len(prefix):])
        for d in self._dirs:
            if d != path and d.startswith(prefix) and "/" not in d[len(prefix):]:
                entries.append(d[len(prefix):])
        return sorted(entries)


class TestMockFSMkdir(unittest.TestCase):
    def setUp(self):
        self.fs = MockFS()

    def test_mkdir_creates_directory(self):
        self.fs.mkdir("/home")
        self.assertIn("/home", self.fs._dirs)

    def test_mkdir_nested(self):
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/user")
        self.assertIn("/home/user", self.fs._dirs)

    def test_mkdir_no_parent_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.mkdir("/home/user")

    def test_mkdir_duplicate_raises(self):
        self.fs.mkdir("/home")
        with self.assertRaises(FileExistsError):
            self.fs.mkdir("/home")

    def test_mkdir_conflict_with_file_raises(self):
        self.fs.create_file("/myfile", "data")
        with self.assertRaises(FileExistsError):
            self.fs.mkdir("/myfile")


class TestMockFSCreateFile(unittest.TestCase):
    def setUp(self):
        self.fs = MockFS()

    def test_create_file_in_root(self):
        self.fs.create_file("/hello.txt", "hello")
        self.assertEqual(self.fs._files["/hello.txt"], "hello")

    def test_create_file_default_empty_content(self):
        self.fs.create_file("/empty.txt")
        self.assertEqual(self.fs._files["/empty.txt"], "")

    def test_create_file_in_subdir(self):
        self.fs.mkdir("/docs")
        self.fs.create_file("/docs/readme.md", "# Readme")
        self.assertEqual(self.fs._files["/docs/readme.md"], "# Readme")

    def test_create_file_no_parent_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.create_file("/nodir/file.txt", "data")

    def test_create_file_duplicate_raises(self):
        self.fs.create_file("/a.txt", "first")
        with self.assertRaises(FileExistsError):
            self.fs.create_file("/a.txt", "second")

    def test_create_file_on_directory_raises(self):
        self.fs.mkdir("/mydir")
        with self.assertRaises(IsADirectoryError):
            self.fs.create_file("/mydir", "data")


class TestMockFSReadFile(unittest.TestCase):
    def setUp(self):
        self.fs = MockFS()
        self.fs.create_file("/data.txt", "contents")
        self.fs.mkdir("/adir")

    def test_read_file_returns_content(self):
        self.assertEqual(self.fs.read_file("/data.txt"), "contents")

    def test_read_file_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.read_file("/nonexistent.txt")

    def test_read_directory_raises(self):
        with self.assertRaises(IsADirectoryError):
            self.fs.read_file("/adir")


class TestMockFSWriteFile(unittest.TestCase):
    def setUp(self):
        self.fs = MockFS()
        self.fs.create_file("/data.txt", "old")
        self.fs.mkdir("/adir")

    def test_write_file_updates_content(self):
        self.fs.write_file("/data.txt", "new")
        self.assertEqual(self.fs.read_file("/data.txt"), "new")

    def test_write_file_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.write_file("/missing.txt", "data")

    def test_write_directory_raises(self):
        with self.assertRaises(IsADirectoryError):
            self.fs.write_file("/adir", "data")


class TestMockFSDeleteFile(unittest.TestCase):
    def setUp(self):
        self.fs = MockFS()
        self.fs.create_file("/removeme.txt", "bye")
        self.fs.mkdir("/keepdir")

    def test_delete_file_removes_it(self):
        self.fs.delete_file("/removeme.txt")
        self.assertNotIn("/removeme.txt", self.fs._files)

    def test_delete_file_then_read_raises(self):
        self.fs.delete_file("/removeme.txt")
        with self.assertRaises(FileNotFoundError):
            self.fs.read_file("/removeme.txt")

    def test_delete_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.delete_file("/ghost.txt")

    def test_delete_directory_raises(self):
        with self.assertRaises(IsADirectoryError):
            self.fs.delete_file("/keepdir")


class TestMockFSListDir(unittest.TestCase):
    def setUp(self):
        self.fs = MockFS()
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/user")
        self.fs.create_file("/home/readme.md", "hi")
        self.fs.create_file("/home/user/config", "x=1")
        self.fs.create_file("/rootfile.txt", "root")

    def test_list_root(self):
        entries = self.fs.list_dir("/")
        self.assertIn("home", entries)
        self.assertIn("rootfile.txt", entries)

    def test_list_subdir(self):
        entries = self.fs.list_dir("/home")
        self.assertEqual(sorted(entries), ["readme.md", "user"])

    def test_list_does_not_include_nested(self):
        entries = self.fs.list_dir("/home")
        self.assertNotIn("config", entries)

    def test_list_empty_dir(self):
        self.fs.mkdir("/empty")
        self.assertEqual(self.fs.list_dir("/empty"), [])

    def test_list_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.list_dir("/nope")

    def test_list_file_raises(self):
        with self.assertRaises(NotADirectoryError):
            self.fs.list_dir("/rootfile.txt")


if __name__ == "__main__":
    # Run via unittest
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Additional standalone assertions for quick verification
    print("\n--- Standalone assertions ---")
    fs = MockFS()

    # mkdir + list_dir
    fs.mkdir("/a")
    fs.mkdir("/a/b")
    assert fs.list_dir("/") == ["a"], f"Expected ['a'], got {fs.list_dir('/')}"
    assert fs.list_dir("/a") == ["b"], f"Expected ['b'], got {fs.list_dir('/a')}"

    # create + read
    fs.create_file("/a/b/file.txt", "hello world")
    assert fs.read_file("/a/b/file.txt") == "hello world"

    # write overwrites
    fs.write_file("/a/b/file.txt", "updated")
    assert fs.read_file("/a/b/file.txt") == "updated"

    # delete removes
    fs.delete_file("/a/b/file.txt")
    try:
        fs.read_file("/a/b/file.txt")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass

    # IsADirectoryError on read/write/delete of directory
    for op in ["read_file", "write_file", "delete_file"]:
        try:
            if op == "write_file":
                getattr(fs, op)("/a", "x")
            else:
                getattr(fs, op)("/a")
            assert False, f"{op} on directory should raise IsADirectoryError"
        except IsADirectoryError:
            pass

    # FileNotFoundError on missing file
    for op in ["read_file", "write_file", "delete_file"]:
        try:
            if op == "write_file":
                getattr(fs, op)("/missing", "x")
            else:
                getattr(fs, op)("/missing")
            assert False, f"{op} on missing file should raise FileNotFoundError"
        except FileNotFoundError:
            pass

    print("All standalone assertions passed.")

    # Exit with proper code
    exit(0 if result.wasSuccessful() else 1)
