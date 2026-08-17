import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "docker.py"


def load_module():
    spec = importlib.util.spec_from_file_location("docker_use", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DockerUseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_accepts_literal_shell_metacharacters(self):
        self.assertEqual(
            self.module.validate_argv({"argv": ["run", "alpine", "sh", "-c", "echo safe; whoami"]}),
            ["run", "alpine", "sh", "-c", "echo safe; whoami"],
        )

    def test_refuses_remote_connection_overrides(self):
        for option in ("-H", "--host=tcp://host:2375", "--context", "--config=/tmp/docker"):
            with self.assertRaises(self.module.DockerError, msg=option):
                self.module.validate_argv({"argv": [option]})

    def test_rejects_command_line_arguments(self):
        with patch.object(sys, "argv", [str(SCRIPT), "ps"]), patch("sys.stdin", io.StringIO("{}")):
            with self.assertRaises(self.module.DockerError):
                self.module.read_request()


if __name__ == "__main__":
    unittest.main()
