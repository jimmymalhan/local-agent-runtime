import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKPOINT_ROOT = REPO_ROOT / "state" / "checkpoints"
LEGACY_ROOT = REPO_ROOT / "checkpoints"


class CheckpointFlowTests(unittest.TestCase):
    def setUp(self):
        CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
        self.created_paths = []
        self.created_legacy = []

    def tearDown(self):
        for path in self.created_paths:
            if path.exists() or path.is_symlink():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        for path in self.created_legacy:
            if path.exists() or path.is_symlink():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        if CHECKPOINT_ROOT.exists() and not any(CHECKPOINT_ROOT.iterdir()):
            shutil.rmtree(CHECKPOINT_ROOT, ignore_errors=True)
        if LEGACY_ROOT.exists() and not any(LEGACY_ROOT.iterdir()):
            shutil.rmtree(LEGACY_ROOT, ignore_errors=True)

    def test_create_checkpoint_writes_into_state_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "project"
            target.mkdir()
            (target / "sample.txt").write_text("alpha\n")

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "unit-test", str(target)],
                capture_output=True,
                text=True,
                check=True,
            )

            checkpoint_path = pathlib.Path(result.stdout.strip().splitlines()[-1])
            self.created_paths.append(checkpoint_path)
            self.created_paths.append(CHECKPOINT_ROOT / "latest")
            self.assertTrue(str(checkpoint_path).startswith(str(CHECKPOINT_ROOT)))
            self.assertTrue((checkpoint_path / "files" / "sample.txt").exists())
            metadata = json.loads((checkpoint_path / "metadata.json").read_text())
            self.assertEqual(pathlib.Path(metadata["source_dir"]).resolve(), target.resolve())

    def test_restore_checkpoint_accepts_legacy_layout_and_migrates_it(self):
        LEGACY_ROOT.mkdir(parents=True, exist_ok=True)
        legacy_dir = LEGACY_ROOT / "19990101_000000-legacy"
        (legacy_dir / "files").mkdir(parents=True)
        (legacy_dir / "files" / "restored.txt").write_text("from legacy\n")
        (legacy_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "label": "legacy",
                    "source_dir": "/tmp/legacy",
                    "created_at": "19990101_000000",
                    "checkpoint_path": str(legacy_dir),
                }
            )
        )
        self.created_legacy.extend([legacy_dir, LEGACY_ROOT / "latest"])

        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "restore-target"
            target.mkdir()

            subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "restore_checkpoint.sh"), legacy_dir.name, str(target)],
                capture_output=True,
                text=True,
                check=True,
            )

            migrated_dir = CHECKPOINT_ROOT / legacy_dir.name
            self.created_paths.append(migrated_dir)
            self.created_paths.append(CHECKPOINT_ROOT / "latest")
            self.assertFalse(legacy_dir.exists())
            self.assertTrue(migrated_dir.exists())
            self.assertEqual((target / "restored.txt").read_text(), "from legacy\n")


if __name__ == "__main__":
    unittest.main()
