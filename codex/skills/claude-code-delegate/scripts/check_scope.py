#!/usr/bin/env python3
"""Check whether changed files stay within a delegation scope."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(path: str) -> str:
    return path.strip().lstrip("./")


def matches_path(path: str, pattern: str) -> bool:
    clean_path = normalize(path)
    clean_pattern = normalize(pattern)
    return clean_path == clean_pattern or clean_path.startswith(clean_pattern.rstrip("/") + "/")


def git_diff(repo: Path) -> str:
    result = subprocess.run(
        ["git", "diff"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def git_status(repo: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def changed_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [normalize(line) for line in result.stdout.splitlines() if line.strip()]


def diff_file_map(diff_text: str) -> dict[str, str]:
    files: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            parts = line.strip().split()
            if len(parts) >= 4:
                path = parts[3]
                current = normalize(path[2:] if path.startswith("b/") else path)
                files[current] = [line]
            else:
                current = None
            continue
        if current is not None:
            files[current].append(line)
    return {path: "".join(lines) for path, lines in files.items()}


def status_file_map(status_text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for line in status_text.splitlines():
        if not line.strip():
            continue
        raw_path = line[3:] if len(line) > 3 else line
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        files[normalize(raw_path)] = line
    return files


def changed_since_baseline(repo: Path, before_diff_path: Path | None, before_status_path: Path | None) -> list[str]:
    if before_diff_path is None and before_status_path is None:
        return changed_files(repo)

    changed: set[str] = set()
    if before_diff_path is not None:
        before_map = diff_file_map(before_diff_path.read_text(encoding="utf-8") if before_diff_path.exists() else "")
        after_map = diff_file_map(git_diff(repo))
        for path in set(before_map) | set(after_map):
            if before_map.get(path, "") != after_map.get(path, ""):
                changed.add(path)

    if before_status_path is not None:
        before_status = status_file_map(
            before_status_path.read_text(encoding="utf-8") if before_status_path.exists() else ""
        )
        after_status = status_file_map(git_status(repo))
        for path in set(before_status) | set(after_status):
            if before_status.get(path, "") != after_status.get(path, ""):
                changed.add(path)

    return sorted(changed)


def build_report(
    repo: Path,
    allowed_path: Path,
    forbidden_path: Path,
    before_diff_path: Path | None = None,
    before_status_path: Path | None = None,
) -> dict[str, object]:
    allowed = [normalize(item) for item in read_lines(allowed_path)]
    forbidden = [normalize(item) for item in read_lines(forbidden_path)]
    changed = changed_since_baseline(repo, before_diff_path, before_status_path)

    outside_allowed = []
    forbidden_changed = []

    for path in changed:
        if allowed and not any(matches_path(path, item) for item in allowed):
            outside_allowed.append(path)
        if any(matches_path(path, item) for item in forbidden):
            forbidden_changed.append(path)

    return {
        "ok": not outside_allowed and not forbidden_changed,
        "changed_files": changed,
        "allowed": allowed,
        "forbidden": forbidden,
        "outside_allowed": outside_allowed,
        "forbidden_changed": forbidden_changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--allowed", required=True, help="Path to allowed-files.txt.")
    parser.add_argument("--forbidden", required=True, help="Path to forbidden-files.txt.")
    parser.add_argument("--before-diff", help="Optional git diff baseline captured before delegation.")
    parser.add_argument("--before-status", help="Optional git status --porcelain baseline captured before delegation.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report = build_report(
        repo,
        Path(args.allowed),
        Path(args.forbidden),
        Path(args.before_diff) if args.before_diff else None,
        Path(args.before_status) if args.before_status else None,
    )

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
