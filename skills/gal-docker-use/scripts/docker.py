#!/usr/bin/env python3
"""Run literal Docker CLI argv for gal-docker-use development environments."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "resources"))
from docker_common import DockerError, ensure_local_daemon, fail, read_request, run_docker  # noqa: E402

FORBIDDEN_GLOBAL_OPTIONS = {"-H", "--host", "--context", "--config"}
FORBIDDEN_PREFIXES = ("--host=", "--context=", "--config=")


def validate_argv(request: dict[str, Any]) -> list[str]:
    argv = request.get("argv")
    if not isinstance(argv, list) or not argv:
        raise DockerError("argv must be a non-empty JSON array of strings.")
    if len(argv) > 128:
        raise DockerError("argv may contain at most 128 arguments.")
    result: list[str] = []
    for value in argv:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise DockerError("Every argv value must be a non-empty string without NUL characters.")
        if value in FORBIDDEN_GLOBAL_OPTIONS or value.startswith(FORBIDDEN_PREFIXES):
            raise DockerError(f"Docker connection override {value!r} is forbidden; this skill only uses the local daemon.")
        result.append(value)
    return result


def main() -> int:
    try:
        request = read_request()
        argv = validate_argv(request)
        ensure_local_daemon()
        timeout = request.get("timeout", 300)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 1800:
            raise DockerError("timeout must be an integer from 1 to 1800 seconds.")
        result = run_docker(argv, timeout=timeout, check=False)
        print(json.dumps({
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }, ensure_ascii=False))
        return result.returncode
    except DockerError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
