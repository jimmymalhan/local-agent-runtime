import os
import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import runtime_env


class RuntimeEnvTests(unittest.TestCase):
    def test_load_runtime_env_sets_process_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = pathlib.Path(tmp) / "runtime.env"
            env_path.write_text("LOCAL_AGENT_PROVIDER_PREFERENCE=openclaw\nOPENCLAW_BASE_URL=http://127.0.0.1:19000\n")
            with mock.patch.dict(os.environ, {}, clear=True):
                values = runtime_env.load_runtime_env(env_path)
                self.assertEqual(values["LOCAL_AGENT_PROVIDER_PREFERENCE"], "openclaw")
                self.assertEqual(os.environ["OPENCLAW_BASE_URL"], "http://127.0.0.1:19000")

    def test_openclaw_runtime_values_derive_from_local_config(self):
        config = {"gateway": {"port": 19000, "auth": {"token": "secret"}}}
        values = runtime_env.openclaw_runtime_values(config)
        self.assertEqual(values["LOCAL_AGENT_ENABLE_OPENCLAW"], "1")
        self.assertEqual(values["LOCAL_AGENT_PROVIDER_PREFERENCE"], "openclaw")
        self.assertEqual(values["OPENCLAW_BASE_URL"], "http://127.0.0.1:19000")
        self.assertEqual(values["OPENCLAW_GATEWAY_TOKEN"], "secret")

    def test_write_runtime_env_merges_existing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = pathlib.Path(tmp) / "runtime.env"
            env_path.write_text("LOCAL_AGENT_MODE=fast\n")
            runtime_env.write_runtime_env({"OPENCLAW_BASE_URL": "http://127.0.0.1:19000"}, env_path)
            body = env_path.read_text()
            self.assertIn("LOCAL_AGENT_MODE=fast", body)
            self.assertIn("OPENCLAW_BASE_URL=http://127.0.0.1:19000", body)


if __name__ == "__main__":
    unittest.main()
