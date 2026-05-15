#!/usr/bin/env python3
"""Sync local Claude Code/Codex agent infrastructure into this repository."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path


HOME = Path.home()

CLAUDE_AGENT_FILES = [
    "fundamental-reviewer.md",
    "logic-reviewer.md",
    "structure-reviewer.md",
    "task-planner.md",
    "type-reviewer.md",
]

CLAUDE_SKILLS = [
    "edit-pr",
    "fundamental-review",
    "handoff",
    "reply-review",
    "test-matrix",
    "trace-api",
    "trace-flow",
]

CODEX_AGENT_FILES = [
    "fundamental-reviewer.toml",
    "logic-reviewer.toml",
    "structure-reviewer.toml",
    "type-reviewer.toml",
]

AGENTS_SKILLS = [
    "edit-pr",
    "fundamental-review",
    "handoff",
    "reply-review",
    "review-team",
    "test-matrix",
    "trace-api",
    "trace-flow",
]

CODEX_SKILLS = [
    "claude-code-delegate",
]

EXCLUDED_DIRS = {
    ".auth",
    ".git",
    ".venv",
    "__pycache__",
}

EXCLUDED_FILES = {
    ".DS_Store",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def should_ignore(_dir: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in EXCLUDED_DIRS or name in EXCLUDED_FILES:
            ignored.add(name)
        elif any(name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
            ignored.add(name)
    return ignored


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, dest: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def copy_tree(src: Path, dest: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=should_ignore)


def sync(repo: Path) -> None:
    reset_dir(repo / "claude-code" / "agents")
    reset_dir(repo / "claude-code" / "skills")
    reset_dir(repo / "codex" / "agents")
    reset_dir(repo / "codex" / "skills")

    for filename in CLAUDE_AGENT_FILES:
        copy_file(HOME / ".claude" / "agents" / filename, repo / "claude-code" / "agents" / filename)

    for skill in CLAUDE_SKILLS:
        copy_tree(HOME / ".claude" / "skills" / skill, repo / "claude-code" / "skills" / skill)

    for filename in CODEX_AGENT_FILES:
        copy_file(HOME / ".codex" / "agents" / filename, repo / "codex" / "agents" / filename)

    for skill in AGENTS_SKILLS:
        copy_tree(HOME / ".agents" / "skills" / skill, repo / "codex" / "skills" / skill)

    for skill in CODEX_SKILLS:
        copy_tree(HOME / ".codex" / "skills" / skill, repo / "codex" / "skills" / skill)


def has_changes(repo: Path) -> bool:
    result = run(["git", "status", "--porcelain"], repo)
    return bool(result.stdout.strip())


def commit_and_push(repo: Path, push: bool) -> None:
    run(["git", "add", "."], repo)
    if not has_changes(repo):
        print("sync-local-infra: no changes")
        return

    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S %z").strip()
    message = f"Sync local agent orchestration infra ({timestamp})"
    run(["git", "commit", "-m", message], repo)
    print(f"sync-local-infra: committed {message}")

    if push:
        run(["git", "push"], repo)
        print("sync-local-infra: pushed")


def acquire_lock(lock_path: Path) -> int:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        return os.open(lock_path, flags)
    except FileExistsError:
        print(f"sync-local-infra: lock exists at {lock_path}; exiting")
        return -1


def release_lock(lock_path: Path, fd: int) -> None:
    if fd >= 0:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--push", action="store_true", help="Push after committing changes.")
    parser.add_argument("--dry-run", action="store_true", help="Sync files but do not commit or push.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"sync-local-infra: not a git repo: {repo}", file=sys.stderr)
        return 2

    lock_path = repo / ".sync-local-infra.lock"
    lock_fd = acquire_lock(lock_path)
    if lock_fd < 0:
        return 0

    try:
        sync(repo)
        if args.dry_run:
            run(["git", "status", "--short"], repo, check=False)
            print("sync-local-infra: dry run complete")
            return 0
        commit_and_push(repo, args.push)
        return 0
    except Exception as exc:
        print(f"sync-local-infra: failed: {exc}", file=sys.stderr)
        return 1
    finally:
        release_lock(lock_path, lock_fd)


if __name__ == "__main__":
    sys.exit(main())
