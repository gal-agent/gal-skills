import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "docker.py"


def load_module():
    spec = importlib.util.spec_from_file_location("safe_docker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SafeDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_rejects_command_line_arguments(self):
        with patch.object(sys, "argv", [str(SCRIPT), "ps"]), patch("sys.stdin", io.StringIO("{}")):
            with self.assertRaises(self.module.DockerError):
                self.module.read_request()

    def test_log_tail_bounds(self):
        with self.assertRaises(self.module.DockerError):
            self.module.bounded_tail({"tail": 501})
        self.assertEqual(self.module.bounded_tail({"tail": 500}), 500)

    def test_summary_redacts_all_environment_values(self):
        self.assertEqual(
            self.module.redacted_environment(["API_TOKEN=value", "PORT=8080", "NO_VALUE"]),
            ["API_TOKEN=<redacted>", "PORT=<redacted>", "NO_VALUE"],
        )

    def test_rejects_unknown_action_without_running_docker(self):
        with self.assertRaises(self.module.DockerError):
            self.module.dispatch({"action": "container", "command": "rm"})


if __name__ == "__main__":
    unittest.main()
