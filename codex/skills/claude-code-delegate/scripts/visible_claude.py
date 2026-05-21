#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = SKILL_DIR / "runtime"
STATE_FILE = RUNTIME_DIR / "current.json"
TASKS_DIR = RUNTIME_DIR / "tasks"
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_JOBS_DIR = CLAUDE_DIR / "jobs"
BG_ID_RE = re.compile(r"backgrounded\s+.\s+([A-Za-z0-9_-]+)")
TERMINAL_TASK_STATES = {"done", "failed", "stopped", "dispatch_failed", "removed"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sandbox_detected() -> bool:
    return bool(os.environ.get("CODEX_SANDBOX"))


def require_unsandboxed() -> None:
    if sandbox_detected():
        raise SystemExit(
            "claude-code-delegate must run outside the Codex sandbox. "
            "Re-run this command with escalated/unsandboxed execution before managing Claude background agents."
        )


def normalize_prompt_arg(prompt: str) -> str:
    return prompt.replace("\\n", "\n").rstrip("\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_state(state: dict[str, Any]) -> None:
    write_json(STATE_FILE, state)


def read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        raise SystemExit("no active Claude Code delegate runtime; run start first")
    return read_json(STATE_FILE)


def run_command(args: list[str], cwd: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def claude_version(cwd: str) -> str:
    proc = run_command(["claude", "--version"], cwd=cwd, timeout=10)
    if proc.returncode != 0:
        raise SystemExit(f"claude --version failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def agents_json(cwd: str) -> list[dict[str, Any]]:
    proc = run_command(["claude", "agents", "--json"], cwd=cwd, timeout=15)
    if proc.returncode != 0:
        raise SystemExit(f"claude agents --json failed: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"claude agents --json returned invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit("claude agents --json returned non-list JSON")
    return data


def run_preflight(cwd: str) -> dict[str, Any]:
    require_unsandboxed()
    checks: dict[str, Any] = {
        "timestamp": now_iso(),
        "unsandboxed": True,
        "runtime_dir": str(RUNTIME_DIR),
        "jobs_dir": str(CLAUDE_JOBS_DIR),
        "workdir": cwd,
    }
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    probe = RUNTIME_DIR / ".preflight-write"
    probe.write_text(now_iso() + "\n")
    probe.unlink()
    checks["runtime_write"] = "ok"

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    jobs_probe_dir = CLAUDE_JOBS_DIR
    jobs_probe_dir.mkdir(parents=True, exist_ok=True)
    checks["jobs_dir_write"] = "ok"

    checks["claude_version"] = claude_version(cwd)
    checks["agents"] = agents_json(cwd)
    checks["status"] = "ok"
    return checks


def task_dir(task_id: str) -> Path:
    return TASKS_DIR / task_id


def task_status_path(task_id: str) -> Path:
    return task_dir(task_id) / "status.json"


def marker_path(task_id: str, status: str) -> Path:
    return task_dir(task_id) / f"{status}.json"


def task_file_path(task_id: str) -> Path:
    return task_dir(task_id) / "task.md"


def list_tasks() -> list[dict[str, Any]]:
    if not TASKS_DIR.exists():
        return []
    tasks: list[dict[str, Any]] = []
    for path in sorted(TASKS_DIR.glob("*/status.json")):
        try:
            tasks.append(read_json(path))
        except (OSError, json.JSONDecodeError):
            continue
    return tasks


def update_task(task: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
    task = {**task, **extra}
    task["status"] = status
    task["updated_at"] = now_iso()
    write_json(task_status_path(task["id"]), task)
    write_json(marker_path(task["id"], status), {"status": status, "timestamp": task["updated_at"]})
    return task


def task_id_for(prompt: str, workdir: str, force_new: bool = False) -> str:
    digest = hashlib.sha256((workdir + "\0" + prompt).encode("utf-8")).hexdigest()
    task_id = digest[:16]
    if force_new:
        task_id = f"{task_id}-{time.strftime('%Y%m%d%H%M%S')}"
    return task_id


def existing_task_for(prompt_sha256: str, workdir: str) -> dict[str, Any] | None:
    for task in list_tasks():
        if task.get("status") == "dry-run":
            continue
        if task.get("prompt_sha256") == prompt_sha256 and task.get("workdir") == workdir:
            return task
    return None


def create_task(state: dict[str, Any], prompt: str, force_new: bool) -> tuple[str, Path, dict[str, Any]]:
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if not force_new:
        existing = existing_task_for(prompt_sha256, state["workdir"])
        if existing:
            print("task already exists; not dispatching duplicate")
            print(f"task_id={existing['id']}")
            print(f"status={existing['status']}")
            print(f"task_file={existing['task_file']}")
            raise SystemExit(0)
    task_id = task_id_for(prompt, state["workdir"], force_new)
    task_file = task_file_path(task_id)
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(prompt.rstrip("\n") + "\n")
    task = {
        "id": task_id,
        "status": "created",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "workdir": state["workdir"],
        "prompt_sha256": prompt_sha256,
        "task_file": str(task_file),
        "transport": "claude-background-agent",
    }
    write_json(task_status_path(task_id), task)
    write_json(marker_path(task_id, "created"), {"status": "created", "timestamp": task["created_at"]})
    return task_id, task_file, task


def dispatch_prompt(task_id: str, task_file: Path) -> str:
    return (
        f"Codex delegated task {task_id}.\n"
        f"Read the task file at {task_file} and execute it exactly.\n"
        "Do not ask me to paste the task again. Do not broaden scope.\n"
        f"When complete, include TASK_DONE {task_id} in the final response."
    )


def parse_bg_id(output: str) -> str | None:
    match = BG_ID_RE.search(output)
    return match.group(1) if match else None


def job_dir(bg_id: str) -> Path:
    return CLAUDE_JOBS_DIR / bg_id


def job_state_path(bg_id: str) -> Path:
    return job_dir(bg_id) / "state.json"


def timeline_path(bg_id: str) -> Path:
    return job_dir(bg_id) / "timeline.jsonl"


def read_job_state(bg_id: str) -> dict[str, Any] | None:
    path = job_state_path(bg_id)
    if not path.exists():
        return None
    try:
        return read_json(path)
    except json.JSONDecodeError:
        return None


def map_job_state(job: dict[str, Any] | None) -> str:
    if not job:
        return "dispatched"
    state = str(job.get("state") or "")
    if state == "done":
        return "done"
    if state in {"failed", "error"}:
        return "failed"
    if state in {"stopped", "killed"}:
        return "stopped"
    return "running"


def refresh_task_from_job(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("status") in TERMINAL_TASK_STATES:
        return task
    bg_id = task.get("bg_id")
    if not bg_id:
        return task
    job = read_job_state(str(bg_id))
    mapped = map_job_state(job)
    extra: dict[str, Any] = {
        "job_state_file": str(job_state_path(str(bg_id))),
        "timeline_file": str(timeline_path(str(bg_id))),
    }
    if job is not None:
        extra["job_state"] = job
    if job and isinstance(job.get("output"), dict):
        extra["output_result"] = job["output"].get("result")
    if mapped != task.get("status"):
        return update_task(task, mapped, **extra)
    task = {**task, **extra, "updated_at": now_iso()}
    write_json(task_status_path(task["id"]), task)
    return task


def refresh_all_tasks() -> list[dict[str, Any]]:
    refreshed = []
    for task in list_tasks():
        if task.get("status") in TERMINAL_TASK_STATES:
            refreshed.append(task)
        else:
            refreshed.append(refresh_task_from_job(task))
    return refreshed


def sync_last_task(state: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    last_task = state.get("last_task")
    if not isinstance(last_task, dict):
        return state
    last_id = last_task.get("id")
    if not last_id:
        return state
    current = next((task for task in tasks if task.get("id") == last_id), None)
    if not current:
        return state
    next_last_task = {
        "id": current["id"],
        "status": current.get("status"),
        "task_file": current.get("task_file"),
        "bg_id": current.get("bg_id"),
    }
    if next_last_task == last_task:
        return state
    state = {**state, "last_task": next_last_task}
    write_state(state)
    return state


def dispatch_task(state: dict[str, Any], task: dict[str, Any], task_file: Path) -> dict[str, Any]:
    prompt = dispatch_prompt(task["id"], task_file)
    proc = run_command(["claude", "--bg", prompt], cwd=state["workdir"], timeout=30)
    combined_output = (proc.stdout or "") + (proc.stderr or "")
    bg_id = parse_bg_id(combined_output)
    if proc.returncode != 0 or not bg_id:
        return update_task(
            task,
            "dispatch_failed",
            dispatch_stdout=proc.stdout,
            dispatch_stderr=proc.stderr,
            dispatch_exit_code=proc.returncode,
        )
    return update_task(
        task,
        "dispatched",
        bg_id=bg_id,
        dispatch_stdout=proc.stdout,
        dispatch_stderr=proc.stderr,
        dispatch_prompt=prompt,
        job_state_file=str(job_state_path(bg_id)),
        timeline_file=str(timeline_path(bg_id)),
    )


def start(args: argparse.Namespace) -> None:
    preflight = run_preflight(args.workdir)
    if args.clean_runtime and RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "mode": "background-agent",
        "status": "ready",
        "workdir": args.workdir,
        "started_at": now_iso(),
        "runtime_dir": str(RUNTIME_DIR),
        "tasks_dir": str(TASKS_DIR),
        "claude_version": preflight["claude_version"],
    }
    write_state(state)
    print("Claude Code background delegate runtime ready")
    print(f"workdir={state['workdir']}")
    print(f"state={STATE_FILE}")


def send(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    if state.get("mode") != "background-agent" or state.get("status") != "ready":
        raise SystemExit("Claude Code background delegate runtime is not ready; run start first")
    prompt = normalize_prompt_arg(args.prompt)
    task_id, task_file, task = create_task(state, prompt, args.force_new)
    if args.dry_run:
        task = update_task(task, "dry-run", dry_run=True)
    else:
        task = dispatch_task(state, task, task_file)
    state["last_task"] = {"id": task_id, "status": task["status"], "task_file": str(task_file), "bg_id": task.get("bg_id")}
    write_state(state)
    print(f"task_id={task_id}")
    print(f"status={task['status']}")
    if task.get("bg_id"):
        print(f"bg_id={task['bg_id']}")
    print(f"task_file={task_file}")
    if task.get("status") in {"dispatch_failed", "failed"}:
        raise SystemExit(1)


def status(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    tasks = refresh_all_tasks()
    state = sync_last_task(state, tasks)
    output = {
        **state,
        "agents": agents_json(state["workdir"]) if args.include_agents else None,
        "tasks": tasks,
    }
    if not args.include_agents:
        output.pop("agents")
    print(json.dumps(output, indent=2, sort_keys=True))


def stop(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    stopped: list[str] = []
    for task in refresh_all_tasks():
        bg_id = task.get("bg_id")
        if not bg_id:
            continue
        if args.all or task.get("status") not in TERMINAL_TASK_STATES:
            proc = run_command(["claude", "stop", str(bg_id)], cwd=state["workdir"], timeout=15)
            if proc.returncode == 0:
                update_task(task, "stopped", stop_stdout=proc.stdout, stop_stderr=proc.stderr)
                stopped.append(str(bg_id))
            elif task.get("status") in TERMINAL_TASK_STATES:
                continue
            else:
                update_task(task, "failed", stop_stdout=proc.stdout, stop_stderr=proc.stderr, stop_exit_code=proc.returncode)
    if args.clear_runtime:
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
    print("Claude Code background delegate stop complete")
    print(f"stopped={','.join(stopped) if stopped else 'none'}")


def remove(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    ids = args.ids
    removed: list[str] = []
    for item in ids:
        task = next((candidate for candidate in list_tasks() if candidate.get("id") == item or candidate.get("bg_id") == item), None)
        bg_id = str(task.get("bg_id") if task else item)
        proc = run_command(["claude", "rm", bg_id], cwd=state["workdir"], timeout=15)
        if proc.returncode != 0:
            if task and "No job matching" in (proc.stderr + proc.stdout):
                task = update_task(task, "removed", rm_stdout=proc.stdout, rm_stderr=proc.stderr, rm_already_absent=True)
                state["last_task"] = {"id": task["id"], "status": task["status"], "task_file": task.get("task_file"), "bg_id": task.get("bg_id")}
                write_state(state)
                removed.append(bg_id)
                continue
            raise SystemExit(f"claude rm {bg_id} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        removed.append(bg_id)
        if task:
            task = update_task(task, "removed", rm_stdout=proc.stdout, rm_stderr=proc.stderr)
            state["last_task"] = {"id": task["id"], "status": task["status"], "task_file": task.get("task_file"), "bg_id": task.get("bg_id")}
            write_state(state)
    print(f"removed={','.join(removed)}")


def preflight(args: argparse.Namespace) -> None:
    print(json.dumps(run_preflight(args.workdir), indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight")
    p.add_argument("--workdir", default=os.getcwd())
    p.set_defaults(func=preflight)

    p = sub.add_parser("start")
    p.add_argument("--workdir", default=os.getcwd())
    p.add_argument("--clean-runtime", action="store_true")
    p.set_defaults(func=start)

    p = sub.add_parser("send")
    p.add_argument("prompt")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force-new", action="store_true")
    p.set_defaults(func=send)

    p = sub.add_parser("status")
    p.add_argument("--include-agents", action="store_true")
    p.set_defaults(func=status)

    p = sub.add_parser("stop")
    p.add_argument("--all", action="store_true", help="also stop terminal tasks tracked in this runtime")
    p.add_argument("--clear-runtime", action="store_true")
    p.set_defaults(func=stop)

    p = sub.add_parser("rm")
    p.add_argument("ids", nargs="+", help="task ids or Claude background short ids")
    p.set_defaults(func=remove)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
