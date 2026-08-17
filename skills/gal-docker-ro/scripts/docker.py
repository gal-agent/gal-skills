#!/usr/bin/env python3
"""Read-only, redacted Docker observations for gal-docker-ro."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "resources"))
from docker_common import DockerError, docker_json, ensure_local_daemon, fail, read_request, run_docker  # noqa: E402

MAX_LOG_LINES = 500
MAX_STATS_CONTAINERS = 100
SENSITIVE_KEYWORDS = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key", "credential")


def require_string(request: dict[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DockerError(f"{key!r} must be a non-empty string without NUL characters.")
    return value


def bounded_tail(request: dict[str, Any]) -> int:
    tail = request.get("tail", 100)
    if not isinstance(tail, int) or isinstance(tail, bool) or not 1 <= tail <= MAX_LOG_LINES:
        raise DockerError(f"tail must be an integer from 1 to {MAX_LOG_LINES}.")
    return tail


def redacted_environment(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for entry in values:
        if not isinstance(entry, str):
            continue
        key, separator, value = entry.partition("=")
        if any(word in key.lower() for word in SENSITIVE_KEYWORDS):
            result.append(f"{key}=<redacted>")
        elif separator:
            result.append(f"{key}=<redacted>")
        else:
            result.append(key)
    return result


def containers(request: dict[str, Any]) -> Any:
    all_containers = request.get("all", False)
    if not isinstance(all_containers, bool):
        raise DockerError("all must be a boolean.")
    return docker_json(["ps", "-a" if all_containers else "--no-trunc", "--format", "{{json .}}"] if all_containers else ["ps", "--format", "{{json .}}"])


def json_lines(argv: list[str]) -> list[Any]:
    output = run_docker(argv).stdout
    result = []
    for line in output.splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def container_summary(request: dict[str, Any]) -> dict[str, Any]:
    name = require_string(request, "container")
    data = docker_json(["inspect", "--type", "container", name])
    if not isinstance(data, list) or len(data) != 1:
        raise DockerError("Docker returned an unexpected container inspection response.")
    item = data[0]
    config = item.get("Config", {})
    state = item.get("State", {})
    host_config = item.get("HostConfig", {})
    return {
        "id": item.get("Id", "")[:12],
        "name": item.get("Name", "").lstrip("/"),
        "image": config.get("Image"),
        "created": item.get("Created"),
        "state": {key: state.get(key) for key in ("Status", "Running", "Paused", "Restarting", "OOMKilled", "ExitCode", "Error", "StartedAt", "FinishedAt")},
        "ports": item.get("NetworkSettings", {}).get("Ports", {}),
        "restart_policy": host_config.get("RestartPolicy", {}).get("Name"),
        "environment": redacted_environment(config.get("Env")),
    }


def logs(request: dict[str, Any]) -> str:
    name = require_string(request, "container")
    tail = bounded_tail(request)
    return run_docker(["logs", "--tail", str(tail), name], timeout=30, check=True).stdout


def dispatch(request: dict[str, Any]) -> Any:
    action = request.get("action")
    if not isinstance(action, str):
        raise DockerError("action must be a string.")
    if action == "version":
        return docker_json(["version", "--format", "{{json .}}"])
    if action == "info":
        return docker_json(["info", "--format", "{{json .}}"])
    if action == "containers":
        return json_lines(["ps", "-a" if request.get("all", False) else "", "--format", "{{json .}}"] if request.get("all", False) else ["ps", "--format", "{{json .}}"])
    if action == "images":
        return json_lines(["images", "--format", "{{json .}}"])
    if action == "networks":
        return json_lines(["network", "ls", "--format", "{{json .}}"])
    if action == "volumes":
        return json_lines(["volume", "ls", "--format", "{{json .}}"])
    if action == "container-summary":
        return container_summary(request)
    if action == "logs":
        return {"logs": logs(request), "truncated_to_lines": bounded_tail(request)}
    if action == "stats":
        return json_lines(["stats", "--no-stream", "--format", "{{json .}}"])
    if action == "port":
        return {"ports": run_docker(["port", require_string(request, "container")]).stdout}
    if action == "top":
        return {"processes": run_docker(["top", require_string(request, "container")]).stdout}
    if action == "diff":
        return {"changes": run_docker(["diff", require_string(request, "container")]).stdout}
    raise DockerError(f"Unsupported read-only action: {action!r}.")


def main() -> int:
    try:
        ensure_local_daemon()
        result = dispatch(read_request())
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except DockerError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
