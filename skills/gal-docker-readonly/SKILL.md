---
name: gal-docker-readonly
description: Read-only Docker checks (sensitive/shared hosts). Load when user mentions or task matches docker, docker ps/info/logs/stats, 查看容器, 容器状态, 容器日志, 镜像列表, 网络, 数据卷, or read-only container inspection.
---

# Read-only Docker Observation

`gal-docker-readonly` provides only bounded, read-only Docker observations. Install it
on sensitive or shared hosts. Do **not** install it together with
`gal-docker-use`, which intentionally permits normal Docker development control.

The script runs outside GAL safe mode but only accepts JSON through stdin and
uses a fixed read-only Docker command allowlist. It invokes the local Docker CLI,
so it works with Docker Desktop on Windows and Docker Engine on Linux without
accessing named pipes or sockets directly.

## Tool

Use `skill_gal-docker-readonly_docker`. Put the request in `input`; leave `args`
empty. The input must be one JSON object.

| Action | JSON input |
|---|---|
| Docker client/server versions | `{"action":"version"}` |
| Docker engine information | `{"action":"info"}` |
| Running containers | `{"action":"containers"}` |
| All containers | `{"action":"containers","all":true}` |
| Images, networks, or volumes | `{"action":"images"}`, `{"action":"networks"}`, `{"action":"volumes"}` |
| Redacted container summary | `{"action":"container-summary","container":"app"}` |
| Bounded logs | `{"action":"logs","container":"app","tail":200}` |
| One resource snapshot | `{"action":"stats"}` |
| Ports, processes, filesystem diff | `{"action":"port","container":"app"}`, `{"action":"top","container":"app"}`, `{"action":"diff","container":"app"}` |

`logs.tail` is required to be from 1 to 500; follow mode is not supported.
Container summaries redact environment values. Docker output and logs can still
contain operationally sensitive information; return only what the user needs.

## Write requests

This skill intentionally cannot start, stop, restart, delete, build, pull, run,
or execute into a container. Do not attempt to bypass this policy through another
Docker path.

Explain the planned state-changing command and ask the user to reissue the
request with `/sudo`. In that one bypassed turn, normal `bash` can invoke Docker
on the host after the user has explicitly approved the request. Do not ask the
user to expose Docker sockets or named pipes to safe mode.

## Host prerequisites

- Docker CLI must be on the host `PATH`.
- Docker Desktop must be running on Windows, or Docker Engine must be running on
  Linux.
- The host user must already have Docker permission.

This skill does not install Docker, change Docker group membership, repair ACLs,
or start/restart the Docker daemon.
