import json
import pathlib
import shutil
import subprocess
import tempfile
import uuid
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LEGACY_ROOT = REPO_ROOT / "checkpoints"


class CheckpointFlowTests(unittest.TestCase):
    def setUp(self):
        if LEGACY_ROOT.exists():
            shutil.rmtree(LEGACY_ROOT, ignore_errors=True)
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
        if LEGACY_ROOT.exists() and not any(LEGACY_ROOT.iterdir()):
            shutil.rmtree(LEGACY_ROOT, ignore_errors=True)

    def test_create_checkpoint_writes_into_target_project_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "project"
            target.mkdir()
            (target / "sample.txt").write_text("alpha\n")
            checkpoint_root = target / ".local-agent" / "checkpoints"

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "unit-test", str(target)],
                capture_output=True,
                text=True,
                check=True,
            )

            checkpoint_path = pathlib.Path(result.stdout.strip().splitlines()[-1]).resolve()
            self.created_paths.append(checkpoint_path)
            self.created_paths.append(target / ".local-agent")
            self.assertEqual(checkpoint_path.parent.resolve(), checkpoint_root.resolve())
            self.assertTrue((checkpoint_path / "files" / "sample.txt").exists())
            metadata = json.loads((checkpoint_path / "metadata.json").read_text())
            self.assertEqual(pathlib.Path(metadata["source_dir"]).resolve(), target.resolve())

    def test_restore_checkpoint_accepts_runtime_legacy_layout_and_migrates_it(self):
        LEGACY_ROOT.mkdir(parents=True, exist_ok=True)
        legacy_dir = LEGACY_ROOT / f"19990101_000000-legacy-{uuid.uuid4().hex[:8]}"
        (legacy_dir / "files").mkdir(parents=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "restore-target"
            target.mkdir()
            (legacy_dir / "files" / "restored.txt").write_text("from legacy\n")
            (legacy_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "label": "legacy",
                        "source_dir": str(target.resolve()),
                        "created_at": "19990101_000000",
                        "checkpoint_path": str(legacy_dir),
                    }
                )
            )
            self.created_legacy.extend([legacy_dir, LEGACY_ROOT / "latest"])

            subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "restore_checkpoint.sh"), legacy_dir.name, str(target)],
                capture_output=True,
                text=True,
                env={**__import__("os").environ, "LOCAL_AGENT_APPROVE_ACTIONS": "restore"},
                check=True,
            )

            migrated_dir = target / ".local-agent" / "checkpoints" / legacy_dir.name
            self.created_paths.append(migrated_dir)
            self.created_paths.append(target / ".local-agent")
            self.assertFalse(legacy_dir.exists())
            self.assertTrue(migrated_dir.exists())
            self.assertEqual((target / "restored.txt").read_text(), "from legacy\n")

    def test_create_checkpoint_skips_runtime_repo_itself(self):
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "unit-test", str(REPO_ROOT)],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "(skipped)")
        self.assertFalse((REPO_ROOT / ".local-agent" / "checkpoints").exists())

    def test_restore_checkpoint_supports_dry_run_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "project"
            target.mkdir()
            (target / "sample.txt").write_text("current\n")

            checkpoint = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "unit-test", str(target)],
                capture_output=True,
                text=True,
                check=True,
            )
            checkpoint_path = pathlib.Path(checkpoint.stdout.strip().splitlines()[-1]).resolve()
            self.created_paths.append(checkpoint_path)
            self.created_paths.append(target / ".local-agent")
            (target / "sample.txt").write_text("modified\n")

            preview = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "restore_checkpoint.sh"), "--dry-run", str(checkpoint_path), str(target)],
                capture_output=True,
                text=True,
                check=True,
            )

            preview_path = pathlib.Path(preview.stdout.strip().splitlines()[-1]).resolve()
            self.created_paths.append(preview_path)
            self.assertTrue(preview_path.exists())
            self.assertIn("Restore Dry Run", preview_path.read_text())
            self.assertEqual((target / "sample.txt").read_text(), "modified\n")

    def test_restore_checkpoint_blocks_without_destructive_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "project"
            target.mkdir()
            (target / "keep.txt").write_text("keep\n")

            checkpoint = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "unit-test", str(target)],
                capture_output=True,
                text=True,
                check=True,
            )
            checkpoint_path = pathlib.Path(checkpoint.stdout.strip().splitlines()[-1]).resolve()
            self.created_paths.append(checkpoint_path)
            self.created_paths.append(target / ".local-agent")
            (target / "delete-me.txt").write_text("remove\n")

            blocked = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "restore_checkpoint.sh"), str(checkpoint_path), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(blocked.returncode, 2)
            self.assertIn("blocked pending approval", blocked.stderr)
            self.assertTrue((target / "delete-me.txt").exists())


if __name__ == "__main__":
    unittest.main()
