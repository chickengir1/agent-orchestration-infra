#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = SKILL_DIR / "runtime"
VENV_PYTHON = SKILL_DIR / ".venv" / "bin" / "python"
STATE_FILE = RUNTIME_DIR / "current.json"
DAEMON_FILE = RUNTIME_DIR / "daemon.json"
STOP_FILE = RUNTIME_DIR / "stop-daemon"
TASKS_DIR = RUNTIME_DIR / "tasks"
QUEUE_DIR = RUNTIME_DIR / "queue"
WORKERS_DIR = RUNTIME_DIR / "workers"
LOGS_DIR = RUNTIME_DIR / "logs"
TERMINAL_TASK_STATES = {"done", "failed", "stopped", "removed", "dry-run"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def now_order() -> int:
    return time.time_ns()


def require_unsandboxed() -> None:
    if os.environ.get("CODEX_SANDBOX"):
        raise SystemExit("claude-code-delegate must run outside the Codex sandbox")


def normalize_prompt_arg(prompt: str) -> str:
    return prompt.replace("\\n", "\n").rstrip("\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


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


def ensure_dirs() -> None:
    for path in (RUNTIME_DIR, TASKS_DIR, QUEUE_DIR, WORKERS_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        raise SystemExit("no active Claude delegate runtime; run start first")
    return read_json(STATE_FILE)


def write_state(state: dict[str, Any]) -> None:
    write_json(STATE_FILE, state)


def task_dir(task_id: str) -> Path:
    return TASKS_DIR / task_id


def task_status_path(task_id: str) -> Path:
    return task_dir(task_id) / "status.json"


def task_file_path(task_id: str) -> Path:
    return task_dir(task_id) / "task.md"


def task_events_path(task_id: str) -> Path:
    return task_dir(task_id) / "events.jsonl"


def queue_item_path(task_id: str) -> Path:
    return QUEUE_DIR / f"{task_id}.json"


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
    updated = {**task, **extra, "status": status, "updated_at": now_iso()}
    write_json(task_status_path(updated["id"]), updated)
    append_jsonl(task_events_path(updated["id"]), {"type": "task_status", "timestamp": updated["updated_at"], "status": status})
    return updated


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


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def daemon_info() -> dict[str, Any] | None:
    if not DAEMON_FILE.exists():
        return None
    try:
        info = read_json(DAEMON_FILE)
    except json.JSONDecodeError:
        return None
    info["alive"] = process_alive(info.get("pid"))
    return info


def require_sdk() -> None:
    if not VENV_PYTHON.exists():
        raise SystemExit(f"missing skill venv Python: {VENV_PYTHON}")
    proc = run_command(
        [str(VENV_PYTHON), "-c", "import claude_agent_sdk; print(claude_agent_sdk.__file__)"],
        cwd=str(SKILL_DIR),
        timeout=10,
    )
    if proc.returncode != 0:
        raise SystemExit("missing claude-agent-sdk in skill venv; run: .venv/bin/python -m pip install claude-agent-sdk")


def claude_version(cwd: str) -> str:
    proc = run_command(["claude", "--version"], cwd=cwd, timeout=10)
    if proc.returncode != 0:
        raise SystemExit(f"claude --version failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def run_preflight(cwd: str) -> dict[str, Any]:
    require_unsandboxed()
    ensure_dirs()
    probe = RUNTIME_DIR / ".preflight-write"
    probe.write_text(now_iso() + "\n")
    probe.unlink()
    require_sdk()
    return {
        "timestamp": now_iso(),
        "status": "ok",
        "mode": "sdk-worker-pool",
        "unsandboxed": True,
        "workdir": cwd,
        "runtime_dir": str(RUNTIME_DIR),
        "venv_python": str(VENV_PYTHON),
        "claude_version": claude_version(cwd),
    }


def message_to_dict(message: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(message):
        return dataclasses.asdict(message)
    if hasattr(message, "__dict__"):
        return dict(message.__dict__)
    return {"repr": repr(message)}


def dispatch_prompt(task: dict[str, Any]) -> str:
    return (
        f"Codex delegated task {task['id']}.\n"
        f"Read the task file at {task['task_file']} and execute it exactly.\n"
        "Do not ask me to paste the task again. Do not broaden scope.\n"
        "Respect the allowed and forbidden paths written in the task file.\n"
        f"When complete, include TASK_DONE {task['id']} in the final response."
    )


async def worker_loop(worker_id: int, workdir: str, model: str, queue: asyncio.Queue[str], stop_event: asyncio.Event) -> None:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

    worker_file = WORKERS_DIR / f"worker-{worker_id}.json"
    options = ClaudeAgentOptions(
        cwd=workdir,
        model=model,
        permission_mode="acceptEdits",
        allowed_tools=["Read", "Edit", "MultiEdit", "Write"],
        add_dirs=["/private/tmp"],
    )
    write_json(worker_file, {"id": worker_id, "status": "connecting", "updated_at": now_iso()})
    async with ClaudeSDKClient(options=options) as client:
        write_json(worker_file, {"id": worker_id, "status": "idle", "updated_at": now_iso()})
        while not stop_event.is_set():
            try:
                task_id = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            try:
                task = read_json(task_status_path(task_id))
                task = update_task(task, "running", worker_id=worker_id, started_at=now_iso())
                write_json(worker_file, {"id": worker_id, "status": "running", "task_id": task_id, "updated_at": now_iso()})
                await client.query(dispatch_prompt(task))
                result: dict[str, Any] | None = None
                async for message in client.receive_response():
                    event = {"type": type(message).__name__, "timestamp": now_iso(), "message": message_to_dict(message)}
                    append_jsonl(task_events_path(task_id), event)
                    if isinstance(message, ResultMessage):
                        result = message_to_dict(message)
                        break
                task = read_json(task_status_path(task_id))
                if result and not result.get("is_error"):
                    update_task(task, "done", result=result, session_id=result.get("session_id"))
                else:
                    update_task(task, "failed", result=result or {"error": "no ResultMessage received"})
            except Exception as exc:
                try:
                    task = read_json(task_status_path(task_id))
                    update_task(task, "failed", error=repr(exc))
                except Exception:
                    append_jsonl(LOGS_DIR / "daemon-errors.jsonl", {"timestamp": now_iso(), "task_id": task_id, "error": repr(exc)})
            finally:
                queue.task_done()
                write_json(worker_file, {"id": worker_id, "status": "idle", "updated_at": now_iso()})


async def enqueue_loop(queue: asyncio.Queue[str], stop_event: asyncio.Event) -> None:
    scheduled: set[str] = set()
    while not stop_event.is_set():
        candidates: list[tuple[str, str]] = []
        for path in QUEUE_DIR.glob("*.json"):
            task_id = path.stem
            if task_id in scheduled:
                continue
            try:
                task = read_json(task_status_path(task_id))
            except (OSError, json.JSONDecodeError):
                continue
            if task.get("status") == "queued":
                candidates.append((str(task.get("queued_order") or task.get("queued_at") or task.get("created_at") or ""), task_id))
        for _, task_id in sorted(candidates):
            if task_id not in scheduled:
                scheduled.add(task_id)
                await queue.put(task_id)
        await asyncio.sleep(0.25)


async def daemon_main_async(args: argparse.Namespace) -> None:
    ensure_dirs()
    STOP_FILE.unlink(missing_ok=True)
    write_json(
        DAEMON_FILE,
        {
            "pid": os.getpid(),
            "mode": "sdk-worker-pool",
            "status": "running",
            "workdir": args.workdir,
            "workers": args.workers,
            "model": args.model,
            "started_at": now_iso(),
            "updated_at": now_iso(),
        },
    )
    queue: asyncio.Queue[str] = asyncio.Queue()
    stop_event = asyncio.Event()
    workers = [asyncio.create_task(worker_loop(i + 1, args.workdir, args.model, queue, stop_event)) for i in range(args.workers)]
    enqueuer = asyncio.create_task(enqueue_loop(queue, stop_event))
    try:
        while not STOP_FILE.exists():
            await asyncio.sleep(0.5)
    finally:
        stop_event.set()
        enqueuer.cancel()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(enqueuer, *workers, return_exceptions=True)
        write_json(
            DAEMON_FILE,
            {
                "pid": os.getpid(),
                "mode": "sdk-worker-pool",
                "status": "stopped",
                "workdir": args.workdir,
                "workers": args.workers,
                "model": args.model,
                "updated_at": now_iso(),
            },
        )


def start(args: argparse.Namespace) -> None:
    preflight = run_preflight(args.workdir)
    info = daemon_info()
    if info and info.get("alive"):
        raise SystemExit(f"delegate daemon already running pid={info['pid']}; stop workers before restarting or cleaning runtime")
    if args.clean_runtime:
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
        ensure_dirs()
    STOP_FILE.unlink(missing_ok=True)
    stdout_path = LOGS_DIR / "daemon.stdout.log"
    stderr_path = LOGS_DIR / "daemon.stderr.log"
    with stdout_path.open("a") as stdout, stderr_path.open("a") as stderr:
        proc = subprocess.Popen(
            [
                str(VENV_PYTHON),
                str(Path(__file__).resolve()),
                "daemon",
                "--workdir",
                args.workdir,
                "--workers",
                str(args.workers),
                "--model",
                args.model,
            ],
            cwd=args.workdir,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    state = {
        "mode": "sdk-worker-pool",
        "status": "ready",
        "workdir": args.workdir,
        "workers": args.workers,
        "model": args.model,
        "runtime_dir": str(RUNTIME_DIR),
        "tasks_dir": str(TASKS_DIR),
        "queue_dir": str(QUEUE_DIR),
        "started_at": now_iso(),
        "daemon_pid": proc.pid,
        "claude_version": preflight["claude_version"],
    }
    write_state(state)
    print("Claude SDK worker pool ready")
    print(f"daemon_pid={proc.pid}")
    print(f"workers={args.workers}")
    print(f"state={STATE_FILE}")


def create_task(state: dict[str, Any], prompt: str, force_new: bool) -> tuple[str, dict[str, Any]]:
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if not force_new:
        existing = existing_task_for(prompt_sha256, state["workdir"])
        if existing:
            print("task already exists; not enqueueing duplicate")
            print(f"task_id={existing['id']}")
            print(f"status={existing['status']}")
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
        "transport": "claude-agent-sdk-worker",
    }
    write_json(task_status_path(task_id), task)
    append_jsonl(task_events_path(task_id), {"type": "task_status", "timestamp": task["created_at"], "status": "created"})
    return task_id, task


def send(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    if state.get("mode") != "sdk-worker-pool" or state.get("status") != "ready":
        raise SystemExit("Claude SDK worker runtime is not ready; run start first")
    info = daemon_info()
    if not info or not info.get("alive"):
        raise SystemExit("Claude SDK worker daemon is not running; run start")
    prompt = normalize_prompt_arg(args.prompt)
    task_id, task = create_task(state, prompt, args.force_new)
    if args.dry_run:
        task = update_task(task, "dry-run", dry_run=True)
    else:
        queued_order = now_order()
        task = update_task(task, "queued", queued_at=now_iso(), queued_order=queued_order)
        write_json(queue_item_path(task_id), {"task_id": task_id, "queued_at": task["updated_at"], "queued_order": queued_order})
    state["last_task"] = {"id": task_id, "status": task["status"], "task_file": task.get("task_file")}
    write_state(state)
    print(f"task_id={task_id}")
    print(f"status={task['status']}")
    print(f"task_file={task['task_file']}")


def sync_last_task(state: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    last_task = state.get("last_task")
    if not isinstance(last_task, dict):
        return state
    current = next((task for task in tasks if task.get("id") == last_task.get("id")), None)
    if not current:
        return state
    next_last = {"id": current["id"], "status": current.get("status"), "task_file": current.get("task_file")}
    if next_last != last_task:
        state = {**state, "last_task": next_last}
        write_state(state)
    return state


def summarize_task(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    return {
        key: value
        for key, value in {
            "id": task.get("id"),
            "status": task.get("status"),
            "worker_id": task.get("worker_id"),
            "session_id": task.get("session_id"),
            "created_at": task.get("created_at"),
            "queued_at": task.get("queued_at"),
            "started_at": task.get("started_at"),
            "updated_at": task.get("updated_at"),
            "task_file": task.get("task_file"),
            "result": result.get("result"),
            "is_error": result.get("is_error"),
            "duration_ms": result.get("duration_ms"),
            "total_cost_usd": result.get("total_cost_usd"),
        }.items()
        if value is not None
    }


def status(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    daemon = daemon_info()
    tasks = list_tasks()
    if daemon and not daemon.get("alive"):
        tasks = [
            update_task(task, "failed", error="sdk worker daemon is not running")
            if task.get("status") in {"queued", "running"}
            else task
            for task in tasks
        ]
    state = sync_last_task(state, tasks)
    output = {**state, "daemon": daemon, "tasks": tasks if args.verbose else [summarize_task(task) for task in tasks]}
    if args.include_workers:
        workers = []
        for path in sorted(WORKERS_DIR.glob("worker-*.json")):
            try:
                workers.append(read_json(path))
            except json.JSONDecodeError:
                continue
        output["workers"] = workers
    print(json.dumps(output, indent=2, sort_keys=True))


def stop(args: argparse.Namespace) -> None:
    require_unsandboxed()
    if args.workers:
        for task in list_tasks():
            if task.get("status") in {"queued", "running"}:
                queue_item_path(task["id"]).unlink(missing_ok=True)
                update_task(task, "stopped", stopped_at=now_iso(), stop_reason="worker pool stopped")
        STOP_FILE.write_text(now_iso() + "\n")
        info = daemon_info()
        if info and info.get("alive"):
            deadline = time.time() + 5
            while time.time() < deadline and process_alive(info.get("pid")):
                time.sleep(0.2)
            if process_alive(info.get("pid")):
                os.kill(int(info["pid"]), signal.SIGTERM)
        print("workers=stopped")
        return
    raise SystemExit("stop currently supports --workers only in sdk-worker-pool mode")


def remove(args: argparse.Namespace) -> None:
    require_unsandboxed()
    removed: list[str] = []
    for item in args.ids:
        task = next((candidate for candidate in list_tasks() if candidate.get("id") == item), None)
        if not task:
            continue
        queue_item_path(task["id"]).unlink(missing_ok=True)
        update_task(task, "removed", removed_at=now_iso())
        removed.append(task["id"])
    print(f"removed={','.join(removed) if removed else 'none'}")


def preflight(args: argparse.Namespace) -> None:
    print(json.dumps(run_preflight(args.workdir), indent=2, sort_keys=True))


def daemon(args: argparse.Namespace) -> None:
    asyncio.run(daemon_main_async(args))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight")
    p.add_argument("--workdir", default=os.getcwd())
    p.set_defaults(func=preflight)

    p = sub.add_parser("start")
    p.add_argument("--workdir", default=os.getcwd())
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--model", default="sonnet")
    p.add_argument("--clean-runtime", action="store_true")
    p.set_defaults(func=start)

    p = sub.add_parser("send")
    p.add_argument("prompt")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force-new", action="store_true")
    p.set_defaults(func=send)

    p = sub.add_parser("status")
    p.add_argument("--include-workers", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=status)

    p = sub.add_parser("stop")
    p.add_argument("--workers", action="store_true")
    p.set_defaults(func=stop)

    p = sub.add_parser("rm")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=remove)

    p = sub.add_parser("daemon")
    p.add_argument("--workdir", required=True)
    p.add_argument("--workers", type=int, required=True)
    p.add_argument("--model", required=True)
    p.set_defaults(func=daemon)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
