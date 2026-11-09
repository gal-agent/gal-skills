---
name: code-standards
description: Install and verify the v1.3 coding-agent engineering standard in AGENTS.md, CLAUDE.md, kiro, cursor, copilot. Load when user mentions 安装规范, AGENTS.md, CLAUDE.md, cursor rules, code-standards.
---

# Code Standards

An engineering standard for AI coding agents (v1.3, 10 sections, 55 rules),
installable into any repository. Once installed it lives as a versioned marker
block inside `AGENTS.md` / `CLAUDE.md` and the agent follows it on every read.

This skill **installs, upgrades, verifies and removes** it. The standard text
itself is not here — it lives in `resources/`.

## Check first whether to act

One grep in the target repo root:

```powershell
Select-String -Path AGENTS.md,CLAUDE.md -Pattern 'code-standards' -ErrorAction SilentlyContinue
```

**If `<!-- BEGIN code-standards v... -->` is already there, stop.** The first
three lines of the block state the version, the sha, and "do not probe or
install again". Unless the user asks for an upgrade or a verification, this skill
is done.

Only continue when nothing is installed.

## Script location

`install.py` sits in this skill's `scripts/`, the standard sources in
`resources/`, and the target definitions in `scripts/targets.json`. The relative
layout is fixed — the script resolves `../resources` from its own location, so
the directory can be moved or copied as a whole.

- Installed: `~/.gal/skills/code-standards/scripts/install.py`
- Dev copy: `./skills/code-standards/scripts/install.py`

Written below as `<skill>/scripts/install.py`.

## Four commands

```powershell
# 1 probe: which carriers this repo has, writes nothing
python <skill>/scripts/install.py --repo . --detect

# 2 install / upgrade (idempotent, safe to repeat)
python <skill>/scripts/install.py --repo . --apply

# 3 verify: exit 1 unless every target is ok
python <skill>/scripts/install.py --repo . --check

# 4 uninstall: remove the block, keep content outside it
python <skill>/scripts/install.py --repo . --uninstall
```

Options: `--targets agents,claude`, `--lang en|zh` (**default en**), `--json`.

English is the default; add `--lang zh` only when the user explicitly asks for
Chinese.

The `--check` exit code is the only trustworthy completion signal. Do not report
"installed" while it is non-zero.

## Install targets

| Target | Path | Detected when |
|---|---|---|
| agents | `AGENTS.md` | always |
| claude | `CLAUDE.md` | `CLAUDE.md` or `.claude/` exists |
| kiro | `.kiro/steering/code-standards.md` | `.kiro/` exists |
| cursor | `.cursor/rules/code-standards.mdc` | `.cursor/` exists |
| copilot | `.github/copilot-instructions.md` | `.github/` exists |
| windsurf | `.windsurf/rules/code-standards.md` | `.windsurf/` exists |
| cline | `.clinerules` | `.clinerules` exists |

`AGENTS.md` is an open convention, so it is always installed. The dedicated
files (kiro, cursor, windsurf) are generated whole, each with its own
frontmatter.

## What lands in the repo

```markdown
<!-- BEGIN code-standards v1.3 sha=6c1afde2 lang=en -->
> **Installed** Coding Agent Engineering Standards v1.3 · sha 6c1afde2
> Managed by install.py, do not edit by hand; use --apply to upgrade, --check to verify.
> Seeing this line means the standard is already in place: do not probe or install again.

(the standard text, 10 sections and 55 rules)

<!-- END code-standards -->
```

Those three status lines are why this skill does not need to fire during ordinary
coding work: **the decision input sits in the prompt, not in an extra tool call.**

Idempotence: with a marker present only the block interior is replaced, nothing
outside it is touched; without a marker the block is appended and
`<file>.code-standards.bak` is written first.

## Editing the standard itself

Never edit the block inside a target repo — the next `--apply` overwrites it.
The correct path:

1. Edit `resources/code-standards.md` (keep `code-standards.en.md` in sync)
2. Record the change in `resources/CHANGELOG.md` — what changed and why
3. Run `--apply` against every installed repo, confirm with `--check`

The version is read from the `v1.3` token in the file; any body edit changes the
sha and makes `--check` report older blocks as `outdated`.

## Boundaries

- Only the marker interior is touched; everything outside it is left alone
- Language is part of the identity: a repo installed with `--lang zh` reports
  `outdated` when checked without `--lang zh`. CI and local must agree
- The legacy `agent-standards` marker is still recognised; `--apply` renames it
  in place rather than appending a second block
- Legacy target files (`.cursor/rules/agent-standards.mdc`,
  `.kiro/steering/engineering-standards.md`) are never deleted automatically —
  the script prints them on stderr for manual cleanup
- Uninstalling a dedicated file removes the file; a block target keeps the rest
  of its content

## States

| State | Meaning |
|---|---|
| `ok` | installed and identical to the source |
| `absent` / `missing` | target file does not exist |
| `no-marker` / `no-meta` | file exists but the block or its metadata is broken |
| `outdated` | version or sha differs from the source, run `--apply` |
| `written` / `unchanged` | written this run / already identical |
| `removed-block` / `removed-file` / `absent` | uninstall result |

## CI

```yaml
- run: python skills/code-standards/scripts/install.py --repo . --check --lang en
```
