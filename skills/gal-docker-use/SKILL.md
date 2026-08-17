---
name: gal-docker-use
description: Local Docker dev control (trusted env). Load when user mentions or task matches docker, docker ps/logs/build/run/exec, compose up, 容器, 镜像, 容器日志, 重启/进入容器, 清理容器/镜像, 端口映射, or local container debugging.
---

# Local Docker Development Use

`gal-docker-use` provides normal local Docker CLI control for a trusted,
non-sensitive development environment. Do **not** install it on production,
shared, or sensitive hosts, and do **not** install it together with
`gal-docker-ro`.

The script runs outside GAL safe mode because Docker Desktop named pipes and
Docker Engine sockets are host resources. It accepts only JSON stdin and starts
only the installed `docker` CLI with literal arguments, never a shell. It also
removes Docker remote-host/context/config environment overrides and refuses
`-H`/`--host`, `--context`, and `--config`, so requests stay on the local Docker
daemon.

> Docker daemon access is highly privileged. Installing this Skill means the
> agent may perform normal local Docker operations, including operations that
> can create, remove, or run containers. This is intentional only for a trusted
> development environment.

## Tool

Use `skill_gal-docker-use_docker`. Pass exactly one JSON object in `input` and
leave `args` empty:

```json
{"argv":["ps","-a"]}
```

The `argv` array maps directly to the arguments after `docker`, with no shell
syntax or expansion. Examples:

```json
{"argv":["compose","up","-d","--build"],"timeout":600}
{"argv":["run","--rm","hello-world"]}
{"argv":["logs","--tail","200","my-service"]}
{"argv":["container","restart","my-service"]}
```

`timeout` is optional and must be an integer from 1 to 1800 seconds; its default
is 300 seconds. The tool returns Docker stdout, stderr, and exit code.

## Rules

- Do not use `args`: the script rejects command-line arguments.
- Do not request remote Docker endpoints, contexts, or config directories; the
  tool rejects them and clears `DOCKER_HOST`, `DOCKER_CONTEXT`, `DOCKER_CONFIG`,
  and related Docker connection variables.
- Never include credentials or secrets in Docker command arguments or output.
  In particular, do not use `docker login` through this skill.
- Before destructive actions, explain the affected containers, images, networks,
  or volumes and obtain explicit user confirmation with GAL's interactive tool.
- Prefer `docker compose` scoped to the current development project rather than
  broad cleanup commands. Warn clearly before `system prune`, volume removal,
  or image removal.

## Host prerequisites

- Docker CLI must be on the host `PATH`.
- Docker Desktop must be running on Windows, or Docker Engine must be running on
  Linux.
- The host user must already have local Docker permission.

The skill does not install Docker, change daemon configuration, change user/group
membership, repair ACLs, or start/restart Docker services.
