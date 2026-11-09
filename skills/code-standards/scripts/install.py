#!/usr/bin/env python3
"""Install the code standards into a repository, idempotently.

    python install.py --detect                  report which targets apply
    python install.py --apply                   write or update
    python install.py --check                   exit 1 if missing or outdated
    python install.py --uninstall               remove, keeping user content

Options: --repo PATH  --targets a,b  --lang en|zh  --json

The default language is English: install it unless the caller explicitly asks
for Chinese with --lang zh.

Every write is wrapped in a marker block whose first line states the installed
version, so an agent reading AGENTS.md knows the standard is already present and
does not need to probe for it. An existing AGENTS.md or CLAUDE.md keeps its own
content, and re-running is a no-op.

Blocks written before the code-standards rename carried an `agent-standards`
marker; both are recognised, so --apply upgrades them in place instead of
appending a second block.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <skill>/scripts
RESOURCES = HERE.parent / "resources"
SOURCES = {"zh": "code-standards.md", "en": "code-standards.en.md"}
TARGETS_FILE = HERE / "targets.json"

NAME = "code-standards"
LEGACY_NAMES = ("agent-standards",)
ALL_NAMES = "|".join(re.escape(n) for n in (NAME,) + LEGACY_NAMES)

# Dedicated target files written before the rename; reported but never touched.
LEGACY_TARGET_FILES = (
    ".cursor/rules/agent-standards.mdc",
    ".kiro/steering/engineering-standards.md",
)

BEGIN_MARK = f"<!-- BEGIN {NAME}"
END_MARK = f"<!-- END {NAME} -->"
REGION_RE = re.compile(
    rf"<!-- BEGIN (?:{ALL_NAMES})[^>]*-->.*?<!-- END (?:{ALL_NAMES}) -->", re.S
)
META_RE = re.compile(r"v(\d+\.\d+(?:\.\d+)?)\s+sha=([0-9a-f]{8})")

STATUS = {
    "zh": (
        "> **已安装** 编码代理工程规范 v{ver} · sha {sha}\n"
        "> 本块由 install.py 维护，请勿手改；升级用 --apply，验证用 --check。\n"
        "> 读到本行即表示规范已就位，不要再去探测或安装。\n"
    ),
    "en": (
        "> **Installed** Coding Agent Engineering Standards v{ver} · sha {sha}\n"
        "> Managed by install.py, do not edit by hand; use --apply to upgrade, --check to verify.\n"
        "> Seeing this line means the standard is already in place: do not probe or install again.\n"
    ),
}


def load_source(lang: str):
    path = RESOURCES / SOURCES[lang]
    if not path.exists():
        sys.exit(f"source not found: {path}")
    body = path.read_text(encoding="utf-8").strip() + "\n"
    m = re.search(r"\bv(\d+\.\d+(?:\.\d+)?)\b", body)
    version = m.group(1) if m else "0"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return body, version, sha


def block_for(body: str, version: str, sha: str, lang: str) -> str:
    status = STATUS[lang].format(ver=version, sha=sha)
    return (
        f"{BEGIN_MARK} v{version} sha={sha} lang={lang} -->\n"
        f"{status}\n{body}{END_MARK}\n"
    )


def load_targets() -> dict:
    return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))


def detect(repo: Path, targets: dict) -> list:
    found = []
    for name, cfg in targets.items():
        rule = (cfg.get("detect") or "").strip()
        if rule == "always":
            found.append(name)
            continue
        for token in [t.strip() for t in rule.split(",") if t.strip()]:
            if (repo / token).exists():
                found.append(name)
                break
    return found


def read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def write(path: Path, text: str, backup: bool) -> None:
    if backup and path.exists():
        shutil.copy2(str(path), str(path) + ".code-standards.bak")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def apply_one(repo: Path, cfg: dict, body: str, version: str, sha: str, lang: str) -> str:
    path = repo / cfg["path"]
    block = block_for(body, version, sha, lang)
    current = read(path)

    if current is None:
        text = (cfg.get("front") or "") + block
    elif REGION_RE.search(current):
        text = REGION_RE.sub(lambda _: block.rstrip("\n"), current, count=1)
    else:
        head = current.rstrip()
        text = (head + "\n\n" + block) if head else block

    if current == text:
        return "unchanged"
    write(path, text, backup=current is not None)
    return "written"


def check_one(repo: Path, cfg: dict, version: str, sha: str) -> str:
    path = repo / cfg["path"]
    current = read(path)
    if current is None:
        return "missing"
    m = REGION_RE.search(current)
    if not m:
        return "no-marker"
    meta = META_RE.search(m.group(0))
    if not meta:
        return "no-meta"
    if meta.group(1) != version or meta.group(2) != sha:
        return "outdated"
    return "ok"


def uninstall_one(repo: Path, cfg: dict) -> str:
    path = repo / cfg["path"]
    current = read(path)
    if current is None:
        return "absent"
    if not REGION_RE.search(current):
        return "no-marker"
    rest = REGION_RE.sub("", current, count=1).strip()
    front = (cfg.get("front") or "").strip()
    if not rest or rest == front:
        path.unlink()
        return "removed-file"
    write(path, rest + "\n", backup=False)
    return "removed-block"


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--targets", default="")
    ap.add_argument("--lang", default="en", choices=sorted(SOURCES))
    ap.add_argument("--json", action="store_true")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--detect", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        sys.exit(f"not a directory: {repo}")
    targets = load_targets()

    legacy = [p for p in LEGACY_TARGET_FILES if (repo / p).exists()]
    if legacy:
        print(f"note     legacy file(s) still present, remove by hand: {', '.join(legacy)}",
              file=sys.stderr)

    detected = detect(repo, targets)
    if args.targets:
        chosen = [t.strip() for t in args.targets.split(",") if t.strip()]
        unknown = [t for t in chosen if t not in targets]
        if unknown:
            sys.exit(f"unknown target(s): {', '.join(unknown)}")
    else:
        chosen = detected

    body, version, sha = load_source(args.lang)
    results = {}

    for name in chosen:
        cfg = targets[name]
        if args.detect:
            state = check_one(repo, cfg, version, sha) if (repo / cfg["path"]).exists() else "absent"
        elif args.apply:
            state = apply_one(repo, cfg, body, version, sha, args.lang)
        elif args.check:
            state = check_one(repo, cfg, version, sha)
        else:
            state = uninstall_one(repo, cfg)
        results[name] = {"path": cfg["path"], "state": state}

    if args.json:
        print(json.dumps(
            {"repo": str(repo), "lang": args.lang, "version": version,
             "sha": sha, "detected": detected, "results": results},
            ensure_ascii=False, indent=2))
    else:
        print(f"repo     {repo}")
        print(f"source   {SOURCES[args.lang]}  v{version}  sha={sha}")
        print(f"detected {', '.join(detected) or '(none)'}")
        for name, info in results.items():
            print(f"  {info['state']:<13} {name:<9} {info['path']}")

    if args.check:
        bad = [n for n, i in results.items() if i["state"] != "ok"]
        if bad:
            print(f"FAILED: {', '.join(bad)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
