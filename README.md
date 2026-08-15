# gal-skills

Standalone skill collection for [GAL](https://github.com/zmysysz/gal). Skills are
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

## Authoring

Read `skills/gal-skill-dev/SKILL.md` for the full authoring guide. Key rules:

- A skill is a directory with `SKILL.md` (YAML frontmatter: `name`, `description`) and optional `scripts/`.
- The `description` frontmatter is the load trigger — agents load the skill when a task matches it.
- Scripts run with the GAL host process permissions; only ship trusted code.
