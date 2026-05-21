#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HOME = Path.home()
SKILL_DIR = HOME / ".codex" / "skills" / "claude-code-delegate"
VISIBLE_CLAUDE = SKILL_DIR / "scripts" / "visible_claude.py"
MONITOR_DIR = SKILL_DIR / "runtime" / "monitor"
HEARTBEAT_FILE = MONITOR_DIR / "heartbeat.json"
EVENTS_FILE = MONITOR_DIR / "events.jsonl"
STATUS_TIMEOUT_SECONDS = 20


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def append_event(event: dict[str, Any]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def run_status() -> tuple[dict[str, Any] | None, str | None]:
    if not VISIBLE_CLAUDE.exists():
        return None, f"missing visible_claude.py: {VISIBLE_CLAUDE}"
    proc = subprocess.run(
        [sys.executable, str(VISIBLE_CLAUDE), "status", "--include-workers"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=STATUS_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"status exited {proc.returncode}"
        return None, message
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"status returned invalid JSON: {exc}"


def summarize_status(status: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    checked_at = now_iso()
    if status is None:
        return {
            "checked_at": checked_at,
            "daemon_alive": False,
            "runtime_status": "unknown",
            "status_error": error,
            "running_tasks": 0,
            "queued_tasks": 0,
            "done_tasks": 0,
            "failed_tasks": 0,
            "stopped_tasks": 0,
            "running_task_ids": [],
            "queued_task_ids": [],
        }

    tasks = status.get("tasks") if isinstance(status.get("tasks"), list) else []
    counts = {"running": 0, "queued": 0, "done": 0, "failed": 0, "stopped": 0}
    ids = {"running": [], "queued": []}
    for task in tasks:
        task_status = task.get("status")
        if task_status in counts:
            counts[task_status] += 1
        if task_status in ids and task.get("id"):
            ids[task_status].append(task["id"])

    daemon = status.get("daemon") if isinstance(status.get("daemon"), dict) else {}
    return {
        "checked_at": checked_at,
        "daemon_alive": bool(status.get("daemon_alive")),
        "daemon_pid": status.get("daemon_pid"),
        "daemon_status": daemon.get("status"),
        "runtime_status": status.get("runtime_status") or status.get("status"),
        "workdir": status.get("workdir"),
        "model": status.get("model"),
        "workers": status.get("workers"),
        "running_tasks": counts["running"],
        "queued_tasks": counts["queued"],
        "done_tasks": counts["done"],
        "failed_tasks": counts["failed"],
        "stopped_tasks": counts["stopped"],
        "running_task_ids": ids["running"],
        "queued_task_ids": ids["queued"],
        "last_task": status.get("last_task"),
    }


def should_log_event(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return True
    keys = [
        "daemon_alive",
        "daemon_pid",
        "runtime_status",
        "workdir",
        "running_tasks",
        "queued_tasks",
        "done_tasks",
        "failed_tasks",
        "stopped_tasks",
        "running_task_ids",
        "queued_task_ids",
        "status_error",
    ]
    return any(previous.get(key) != current.get(key) for key in keys)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    previous = read_json(HEARTBEAT_FILE)
    status, error = run_status()
    heartbeat = summarize_status(status, error)
    write_json_atomic(HEARTBEAT_FILE, heartbeat)

    if should_log_event(previous, heartbeat):
        append_event({"type": "heartbeat", **heartbeat})

    if not args.quiet:
        print(json.dumps(heartbeat, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
