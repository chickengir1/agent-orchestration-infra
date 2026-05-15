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


def build_report(repo: Path, allowed_path: Path, forbidden_path: Path) -> dict[str, object]:
    allowed = [normalize(item) for item in read_lines(allowed_path)]
    forbidden = [normalize(item) for item in read_lines(forbidden_path)]
    changed = changed_files(repo)

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
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report = build_report(repo, Path(args.allowed), Path(args.forbidden))

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
