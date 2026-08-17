#!/usr/bin/env python3
"""Shared Docker CLI helpers for GAL Docker skills.

The caller supplies structured values only. This module always invokes Docker
without a shell and refuses remote daemon endpoints.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
from typing import Any, Sequence

DOCKER_ENV_BLOCKLIST = {
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY", "DOCKER_TLS", "DOCKER_API_VERSION", "DOCKER_BUILDKIT",
}


class DockerError(RuntimeError):
    """An expected Docker policy or execution failure."""


def local_docker_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in DOCKER_ENV_BLOCKLIST:
        env.pop(key, None)
    return env


def run_docker(argv: Sequence[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise DockerError("Docker arguments must be non-empty strings without NUL characters.")
    try:
        result = subprocess.run(
            ["docker", *argv],
            shell=False,
            env=local_docker_env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DockerError("Docker CLI was not found in the host PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerError(f"Docker command timed out after {timeout} seconds.") from exc
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or f"Docker exited with code {result.returncode}."
        raise DockerError(message)
    return result


def ensure_local_daemon() -> None:
    """Reject contexts whose Docker endpoint is a remote TCP/SSH endpoint."""
    endpoint = run_docker(["context", "inspect", "--format", "{{ .Endpoints.docker.Host }}"], timeout=15).stdout.strip()
    if not endpoint.startswith(("unix://", "npipe://")):
        raise DockerError(
            "The selected Docker context is not local (expected unix:// or npipe:// endpoint); remote Docker daemons are refused."
        )


def read_request() -> dict[str, Any]:
    import sys

    if len(sys.argv) != 1:
        raise DockerError("This tool accepts JSON through stdin only; do not use command-line arguments.")
    raw = sys.stdin.read()
    if not raw.strip():
        raise DockerError("A JSON request is required on stdin.")
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DockerError("Input must be a JSON object.") from exc
    if not isinstance(request, dict):
        raise DockerError("Input must be a JSON object.")
    return request


def platform_hint() -> str:
    if platform.system() == "Windows":
        return "Ensure Docker Desktop is running and the current user can use Docker."
    return "Ensure the Docker daemon is running and the current user can access its socket."


def fail(message: str) -> int:
    import sys

    print(json.dumps({"ok": False, "error": message, "hint": platform_hint()}), file=sys.stderr)
    return 1
