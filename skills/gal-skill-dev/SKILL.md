---
name: gal-skill-dev
description: Guide for authoring GAL skills. Load when the user asks to create, write, or design a skill, or the task involves producing a SKILL.md, skill scripts, or packaging reusable knowledge as a skill.
---

# GAL Skill Authoring Guide

A skill packages reusable knowledge (and optionally executable scripts) that an
agent loads on demand. Authoring a skill = writing plain files; you do that with
the normal file tools (file_write/file_edit). This guide defines WHAT to write.

Authoring (writing the files) is separate from installing. Skill files are plain
files — write them anywhere in the working directory, same as project source code.
Do NOT write directly into `~/.gal/skills/` (that is the install target, not a
development directory). Authoring alone does NOT make a skill active for an agent.
Installing — copying the skill into `~/.gal/skills/` and adding it to an agent's
`skills:` list — is an admin task done in `/admin`. In `/admin` you can develop and
install in one flow; in normal chat you can develop but must switch to `/admin` to
install.

## 1. Directory Layout
Author the skill under its own directory. `skills/<skill-name>/` is the conventional
location (this is where `load_skills` looks for development copies), but any path
under the working directory works — treat it like any other source code.

`~/.gal/skills/` is the install target, not a development directory.

Runtime resolution: if a skill exists in both `~/.gal/skills/` (installed) and
`./skills/` (development), the installed copy wins. To test a development draft,
either uninstall the installed copy first (in `/admin`) or use a different skill name.

  <skill-name>/
  ├── SKILL.md         # REQUIRED: frontmatter + documentation body
  ├── scripts/         # OPTIONAL: each executable becomes a tool (see §5)
  │   └── run.sh
  └── resources/       # OPTIONAL: templates, configs, examples referenced by SKILL.md

- <skill-name>: lowercase, alphanumeric, hyphens or underscores; starts with a
  letter or digit (regex ^[a-z0-9][a-z0-9_-]*$). The directory name is the skill name.

## 2. SKILL.md Frontmatter
Begin SKILL.md with a YAML frontmatter block delimited by '---' lines:

  ---
  name: <skill-name>
  description: <trigger-oriented description, see §3>
  ---

- name MUST match the directory name.
- Only name and description are required. Keep values on one line; quote any
  value containing ':' or special characters.

## 3. description = the load TRIGGER (most important field)
The description is NOT documentation — it is the signal the agent uses to decide
whether to load the skill. Write it so the right skill loads at the right time.
- Max 200 characters. Two parts:
  1. Brief purpose (<=30 chars) — what the skill does.
  2. Trigger conditions — when to load it.
- Format: "<purpose>. Load when user mentions or agent finds task highly matches
  <keyword1>, <keyword2>, <keyword3>..."
- Cover BOTH user-mentioned keywords AND scenarios an agent hits at runtime
  (not only explicit user requests). List concrete keywords, file extensions,
  and scenarios.
- Do NOT put implementation details, usage tips, or alternatives here.
- Bad:  "Excel read/write/format. Use for quick inspection."
- Good: "Excel spreadsheet read/write. Load when user mentions or agent finds
  task highly matches xlsx, xls, spreadsheet, cell formatting, sheet
  manipulation, or tabular data export."

## 4. Documentation Body (progressive disclosure)
The text after the frontmatter is the body returned by load_skills.
- Skills are lazy-loaded: the system prompt shows ONLY name + description.
  load_skills then returns the full body and registers any script tools.
- Keep the body focused: what the skill does, when to use it, step-by-step
  usage, exact tool names and parameters, and pointers into resources/ for
  bulky reference material (load detail only when needed).
- Be explicit about tool names and arguments so the agent never has to guess.

## 5. Scripts vs Prompt-Only
- Prompt-only skill (no scripts/ dir): load_skills returns documentation only,
  no tools registered. Use this when the skill is pure knowledge/procedure.
- Skill with scripts/: each executable file becomes a tool named
  "skill_<skillname>_<scriptbasename>" (e.g. scripts/run.sh in skill "myskill"
  → tool "skill_myskill_run"). The script must be executable (chmod +x), and on
  Windows use .exe/.bat/.cmd/.ps1 (shell scripts are skipped on Windows, native
  binaries are skipped on Unix). Each tool receives optional "input" (stdin) and
  "args" (command-line) parameters — document the exact contract in the body.

## 6. Security Model (read before adding scripts)
Skill script tools run as local commands, OUTSIDE the safe-mode sandbox, with
the user's normal system access. Treat scripts as trusted code:
- Have the script content reviewed before it is installed.
- NEVER put credentials in SKILL.md, scripts, resources, or tool output.
- Prefer read-only behavior unless the skill's purpose requires writes.
- Use interactive confirmation before destructive operations.

## 7. After Authoring (install = admin)
1. Verify the files are correct: frontmatter parses, the description follows §3,
   and any scripts are executable and run as intended.
2. Stop at the authored files unless the user explicitly asks to install/activate
   the skill. To install, switch to `/admin`: copy the skill directory into
   `~/.gal/skills/<name>/` and add the name to the target agent's `skills:` list.
   Uninstall/delete are also admin tasks. Authoring alone never registers or runs
   anything.
