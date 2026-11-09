# gal-skills

Standalone skill collection for [GAL](https://github.com/gal-agent/gal-release)
— if you don't have the `gal` binary yet, grab a release there first. Skills are
plain directories (`SKILL.md` plus optional `scripts/`, `resources/`) that GAL
agents lazy-load via `load_skills`.

## Install

Clone the repo (or copy the skill directory you want) into `~/.gal/skills/`:

```bash
git clone <repo-url> /tmp/gal-skills
cp -r /tmp/gal-skills/skills/<name> ~/.gal/skills/<name>
```

Or clone the whole repo and symlink individual skills:

```bash
git clone <repo-url> ~/gal-skills
ln -s ~/gal-skills/skills/gal-skill-dev ~/.gal/skills/gal-skill-dev
```

After installing, attach the skill to an agent's `skills:` list in `~/.gal/agents/<agent>.yaml`
(chat: `/admin` mode manages this).

## Skills

| Skill | Description |
|-------|-------------|
| `gal-skill-dev` | Authoring guide for GAL skills — directory layout, SKILL.md frontmatter, the description-as-trigger rule, scripts vs prompt-only, security model. |
| `gal-k8s-safe` | Restricted Kubernetes safe-mode setup: read-only kubeconfig mounts, RBAC generation, protected namespace checks, guarded writes, 15-day backups. |
| `gal-docker-ro` | Read-only, redacted Docker observations for sensitive or shared environments. |
| `gal-docker-use` | Local Docker CLI control for trusted, non-sensitive development environments. |
| `code-standards` | Install and verify the v1.3 coding-agent engineering standard inside AGENTS.md, CLAUDE.md, kiro, cursor, windsurf and copilot targets; idempotent, version-checked, upgradeable. |

## Portability notice

Some skills in this repo are built to run under GAL's own security design -
safe-mode sandboxing, per-agent tool allowlists, JSON-stdin script tools, and
hidden credential directories. They rely on those guarantees and are **not
universally portable**. If you reuse them with other agent frameworks, review
each skill's scripts and assumptions first and provide equivalent guardrails
yourself; don't assume the surrounding runtime enforces the same restrictions.

## Authoring

Read `skills/gal-skill-dev/SKILL.md` for the full authoring guide. Key rules:

- A skill is a directory with `SKILL.md` (YAML frontmatter: `name`, `description`) and optional `scripts/`.
- The `description` frontmatter is the load trigger — agents load the skill when a task matches it.
- Scripts run with the GAL host process permissions; only ship trusted code.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE), the same
terms as [GAL](https://github.com/gal-agent/gal-release) itself.
