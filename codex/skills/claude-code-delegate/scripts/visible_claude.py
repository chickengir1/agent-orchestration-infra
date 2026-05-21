#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import re
import select
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = SKILL_DIR / "runtime"
STATE_FILE = RUNTIME_DIR / "current.json"
LOG_FILE = RUNTIME_DIR / "session.log"
CTRL_LOG_FILE = RUNTIME_DIR / "controller.log"
TASKS_DIR = RUNTIME_DIR / "tasks"
MCP_CONFIG_FILE = RUNTIME_DIR / "mcp.json"
CHANNEL_SERVER = SKILL_DIR / "scripts" / "channel_server.py"
CHANNEL_NAME = "codex_delegate_channel"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
REMOTE_URL_RE = re.compile(r"https://claude\.ai/(?:code|cod)/session_[A-Za-z0-9]+")
SESSION_ID_RE = re.compile(r"session_[A-Za-z0-9]+")
CLAUDE_SESSION_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
DEV_CHANNEL_CONFIRM_TEXT = "iamusingthisforlocaldevelopment"
DEV_CHANNEL_CONFIRM_HINT = "entertoconfirm"


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def normalize_remote_url(url: str) -> str:
    return url.replace("https://claude.ai/cod/", "https://claude.ai/code/")


def extract_remote_url(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    match = REMOTE_URL_RE.search(compact)
    if match:
        return normalize_remote_url(match.group(0))
    session_match = SESSION_ID_RE.search(compact)
    if session_match and "claude" in compact and "code" in compact:
        return f"https://claude.ai/code/{session_match.group(0)}"
    return None


def normalize_prompt_arg(prompt: str) -> str:
    return prompt.replace("\\n", "\n").rstrip("\n")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def read_state() -> dict:
    if not STATE_FILE.exists():
        raise SystemExit("no active Claude Code session")
    return json.loads(STATE_FILE.read_text())


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cleanup_runtime() -> None:
    if RUNTIME_DIR.exists():
        for path in RUNTIME_DIR.iterdir():
            if path.is_file() or path.is_fifo():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        try:
            RUNTIME_DIR.rmdir()
        except OSError:
            pass


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def sandbox_detected() -> bool:
    return bool(os.environ.get("CODEX_SANDBOX"))


def require_unsandboxed() -> None:
    if sandbox_detected():
        raise SystemExit(
            "claude-code-delegate must run outside the Codex sandbox. "
            "Re-run this command with escalated/unsandboxed execution before touching local ports or runtime processes."
        )


def run_preflight() -> dict:
    checks: dict[str, object] = {
        "timestamp": now_iso(),
        "unsandboxed": not sandbox_detected(),
        "python": sys.executable,
        "runtime_dir": str(RUNTIME_DIR),
        "channel_server": str(CHANNEL_SERVER),
    }
    require_unsandboxed()
    if not CHANNEL_SERVER.exists():
        raise SystemExit(f"channel server missing: {CHANNEL_SERVER}")

    compile(CHANNEL_SERVER.read_text(), str(CHANNEL_SERVER), "exec")
    checks["channel_server_syntax"] = "ok"

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    probe = RUNTIME_DIR / ".preflight-write"
    probe.write_text(now_iso() + "\n")
    probe.unlink()
    checks["runtime_write"] = "ok"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        checks["localhost_bind"] = sock.getsockname()[1]

    proc = subprocess.run(
        ["claude", "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"claude --version failed: {proc.stderr.strip()}")
    checks["claude_version"] = proc.stdout.strip()
    checks["status"] = "ok"
    return checks


def write_mcp_config(token: str) -> None:
    write_json(
        MCP_CONFIG_FILE,
        {
            "mcpServers": {
                CHANNEL_NAME: {
                    "command": sys.executable,
                    "args": [
                        str(CHANNEL_SERVER),
                        "--runtime-dir",
                        str(RUNTIME_DIR),
                        "--token",
                        token,
                    ],
                }
            }
        },
    )


def encoded_project_dir(workdir: str) -> Path:
    return CLAUDE_PROJECTS_DIR / workdir.replace("/", "-")


def tail_text(path: Path, limit: int = 2_000_000) -> str:
    with path.open("rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit), os.SEEK_SET)
        except OSError:
            pass
        return f.read().decode("utf-8", errors="ignore")


def bridge_id_from_remote_url(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    match = SESSION_ID_RE.search(remote_url)
    if not match:
        return None
    return "cse_" + match.group(0).removeprefix("session_")


def find_claude_session_id(workdir: str, bridge_session_id: str | None) -> str | None:
    project_dir = encoded_project_dir(workdir)
    if not project_dir.exists():
        return None
    files = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if bridge_session_id:
        needle = f'"bridgeSessionId":"{bridge_session_id}"'
        for path in files:
            text = tail_text(path)
            if needle in text:
                match = CLAUDE_SESSION_ID_RE.search(path.name)
                if match:
                    return match.group(0)
                for line in text.splitlines():
                    if needle in line:
                        try:
                            return json.loads(line).get("sessionId")
                        except json.JSONDecodeError:
                            return None
    return None


def refresh_session_identity(state: dict) -> dict:
    dirty = "fifo" in state
    state.pop("fifo", None)
    if state.get("status") == "ready" and not state.get("channel"):
        state["status"] = "legacy-no-channel"
        dirty = True
    if state.get("claude_session_id"):
        if dirty:
            write_state(state)
        return state
    bridge_session_id = state.get("bridge_session_id") or bridge_id_from_remote_url(state.get("remote_url"))
    if bridge_session_id:
        state["bridge_session_id"] = bridge_session_id
    claude_session_id = find_claude_session_id(state["workdir"], bridge_session_id)
    if claude_session_id:
        state["claude_session_id"] = claude_session_id
        write_state(state)
    return state


def task_id_for(prompt: str, claude_session_id: str, force_new: bool = False) -> str:
    digest = hashlib.sha256((claude_session_id + "\0" + prompt).encode("utf-8")).hexdigest()
    task_id = digest[:16]
    if force_new:
        task_id = f"{task_id}-{time.strftime('%Y%m%d%H%M%S')}"
    return task_id


def task_dir(task_id: str) -> Path:
    return TASKS_DIR / task_id


def task_status_path(task_id: str) -> Path:
    return task_dir(task_id) / "status.json"


def marker_path(task_id: str, status: str) -> Path:
    return task_dir(task_id) / f"{status}.json"


def update_task(task: dict, status: str, **extra: object) -> dict:
    task = {**task, **extra}
    task["status"] = status
    task["updated_at"] = now_iso()
    write_json(task_status_path(task["id"]), task)
    write_json(marker_path(task["id"], status), {"status": status, "timestamp": task["updated_at"]})
    return task


def list_tasks() -> list[dict]:
    if not TASKS_DIR.exists():
        return []
    tasks = []
    for path in sorted(TASKS_DIR.glob("*/status.json")):
        try:
            tasks.append(read_json(path))
        except (OSError, json.JSONDecodeError):
            continue
    return tasks


def existing_task_for(prompt_sha256: str, claude_session_id: str) -> dict | None:
    for task in list_tasks():
        if task.get("status") == "dry-run":
            continue
        if task.get("prompt_sha256") == prompt_sha256 and task.get("claude_session_id") == claude_session_id:
            return task
    return None


def write_task_file(task_id: str, prompt: str) -> Path:
    path = task_dir(task_id) / "task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt.rstrip("\n") + "\n")
    return path


def require_channel(state: dict) -> dict:
    channel = state.get("channel") or {}
    if state.get("status") != "ready":
        raise SystemExit(f"Claude Code channel session is not ready: {state.get('status')}")
    if channel.get("name") != CHANNEL_NAME or not channel.get("http_url") or not channel.get("token"):
        raise SystemExit("active session was not started with the Codex delegate channel; stop and start a new session")
    if not channel.get("handshake_done"):
        raise SystemExit("Codex delegate channel handshake is incomplete; stop and start a new session")
    return channel


def post_channel_task(channel: dict, task_id: str, task_file: Path, timeout: float = 5.0) -> None:
    url = channel["http_url"].rstrip("/") + "/task"
    body = json.dumps({"task_id": task_id, "task_file": str(task_file)}).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-codex-delegate-token": channel["token"],
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as res:
            if res.status != 202:
                raise SystemExit(f"channel rejected task: HTTP {res.status}")
    except error.URLError as exc:
        raise SystemExit(f"channel transport unavailable: {exc}") from exc


def wait_for_task_status(task_id: str, statuses: set[str], timeout: float) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            task = read_json(task_status_path(task_id))
        except (OSError, json.JSONDecodeError):
            task = {}
        if task.get("status") in statuses:
            return task
        time.sleep(0.25)
    return None


def create_task(state: dict, prompt: str, force_new: bool, transport: str) -> tuple[str, Path, dict]:
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    session_key = state.get("claude_session_id") or state["session_name"]
    if not force_new:
        existing = existing_task_for(prompt_sha256, session_key)
        if existing:
            print("task already exists; not sending duplicate")
            print(f"task_id={existing['id']}")
            print(f"status={existing['status']}")
            print(f"task_file={existing['task_file']}")
            raise SystemExit(0)
    task_id = task_id_for(prompt, session_key, force_new)
    task_file = write_task_file(task_id, prompt)
    task = {
        "id": task_id,
        "status": "pending",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "session_name": state["session_name"],
        "remote_url": state.get("remote_url"),
        "bridge_session_id": state.get("bridge_session_id"),
        "claude_session_id": state.get("claude_session_id"),
        "workdir": state["workdir"],
        "prompt_sha256": prompt_sha256,
        "task_file": str(task_file),
        "transport": transport,
    }
    write_json(task_status_path(task_id), task)
    write_json(marker_path(task_id, "pending"), {"status": "pending", "timestamp": task["created_at"]})
    return task_id, task_file, task


def run_channel_handshake(state: dict) -> dict:
    channel = state.get("channel") or {}
    task_id, task_file, task = create_task(
        state,
        "Channel handshake only. Do not modify files. Call delegate_status ack, delegate_reply with 'channel handshake ok', then delegate_status done.",
        True,
        "channel",
    )
    task = update_task(task, "pending", handshake=True)
    post_channel_task(channel, task_id, task_file)
    done = wait_for_task_status(task_id, {"done", "failed"}, 45)
    if not done or done.get("status") != "done":
        update_task(task, "failed", failure="channel handshake did not complete")
        raise SystemExit("channel handshake failed; Claude Code session is not ready")
    channel["handshake_done"] = True
    channel["handshake_task_id"] = task_id
    channel["handshake_done_at"] = now_iso()
    state["channel"] = channel
    state["status"] = "ready"
    write_state(state)
    return state


def start(args: argparse.Namespace) -> None:
    preflight = run_preflight()
    if STATE_FILE.exists():
        state = read_state()
        pid = int(state.get("controller_pid", 0) or 0)
        if pid and process_alive(pid):
            raise SystemExit(f"already running: {state.get('session_name')}")
        cleanup_runtime()

    cleanup_runtime()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    channel_token = secrets.token_urlsafe(24)
    write_mcp_config(channel_token)

    ctrl_log = CTRL_LOG_FILE.open("ab")
    subprocess.Popen(
        [
            str(Path(__file__).resolve()),
            "controller",
            "--name",
            args.name,
            "--workdir",
            args.workdir,
        ],
        cwd=args.workdir,
        stdout=ctrl_log,
        stderr=ctrl_log,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )

    deadline = time.time() + 20
    last_state = None
    while time.time() < deadline:
        if STATE_FILE.exists():
            state = read_state()
            last_state = state
            channel = state.get("channel") or {}
            if state.get("remote_url") and channel.get("mcp_ready") and channel.get("http_url"):
                state = refresh_session_identity(state)
                state = run_channel_handshake(state)
                print("Claude Code remote-control session ready")
                print(f"session={state['session_name']}")
                print(f"remote_url={state['remote_url']}")
                print(f"channel={state['channel']['http_url']}")
                print(f"preflight={preflight['status']}")
                print(f"state={STATE_FILE}")
                return
        time.sleep(0.2)
    raise SystemExit(f"timeout waiting for Claude remote-control channel session; last_state={last_state}")


def controller(args: argparse.Namespace) -> None:
    require_unsandboxed()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    master_fd, slave_fd = pty.openpty()
    child = subprocess.Popen(
        [
            "claude",
            "--permission-mode",
            "auto",
            "--mcp-config",
            str(MCP_CONFIG_FILE),
            "--dangerously-load-development-channels",
            f"server:{CHANNEL_NAME}",
            "--remote-control",
            args.name,
        ],
        cwd=args.workdir,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    state = {
        "session_name": args.name,
        "status": "starting",
        "workdir": args.workdir,
        "controller_pid": os.getpid(),
        "claude_pid": child.pid,
        "log": str(LOG_FILE),
        "tasks_dir": str(TASKS_DIR),
        "visible": "remote-control",
        "remote_url": None,
        "bridge_session_id": None,
        "claude_session_id": None,
        "permission_mode": "auto",
        "channel": {
            "name": CHANNEL_NAME,
            "status": "starting",
            "mcp_config": str(MCP_CONFIG_FILE),
            "token": read_json(MCP_CONFIG_FILE)["mcpServers"][CHANNEL_NAME]["args"][-1],
        },
    }
    write_state(state)

    recent_output = ""
    development_channel_confirmed = False

    try:
        with LOG_FILE.open("ab") as log:
            while True:
                if child.poll() is not None:
                    state["status"] = "exited"
                    state["exit_code"] = child.returncode
                    write_state(state)
                    break
                readable, _, _ = select.select([master_fd], [], [], 0.2)
                for fd in readable:
                    if fd == master_fd:
                        try:
                            data = os.read(master_fd, 8192)
                        except BlockingIOError:
                            data = b""
                        if data:
                            os.write(sys.stdout.fileno(), data)
                            sys.stdout.flush()
                            log.write(data)
                            log.flush()
                            text = strip_ansi(data.decode("utf-8", errors="ignore"))
                            recent_output = (recent_output + text)[-4000:]
                            compact_output = re.sub(r"[^a-z0-9]+", "", recent_output.lower())
                            if (
                                not development_channel_confirmed
                                and DEV_CHANNEL_CONFIRM_TEXT in compact_output
                                and DEV_CHANNEL_CONFIRM_HINT in compact_output
                            ):
                                os.write(master_fd, b"\r")
                                development_channel_confirmed = True
                                state["channel"]["development_prompt_confirmed"] = True
                                state["channel"]["development_prompt_confirmed_at"] = now_iso()
                                write_state(state)
                            remote_url = extract_remote_url(recent_output)
                            if remote_url:
                                state["remote_url"] = remote_url
                                state["bridge_session_id"] = bridge_id_from_remote_url(remote_url)
                                state["status"] = "remote-ready"
                                state = refresh_session_identity(state)
                                write_state(state)
    finally:
        for fd in (master_fd,):
            try:
                os.close(fd)
            except OSError:
                pass


def send(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = refresh_session_identity(read_state())
    channel = require_channel(state)
    prompt = normalize_prompt_arg(args.prompt)
    task_id, task_file, task = create_task(state, prompt, args.force_new, "channel")
    state["last_task"] = {"id": task_id, "status": "pending", "task_file": str(task_file)}
    write_state(state)
    if args.dry_run:
        task = update_task(task, "dry-run", dry_run=True)
    else:
        post_channel_task(channel, task_id, task_file)
        task = wait_for_task_status(task_id, {"ack", "done", "failed"}, args.ack_timeout)
        if not task:
            task = update_task(read_json(task_status_path(task_id)), "failed", failure="channel ack timeout")
    state["last_task"] = {"id": task_id, "status": task["status"], "task_file": str(task_file)}
    write_state(state)
    print(f"task_id={task_id}")
    print(f"status={task['status']}")
    print(f"task_file={task_file}")
    print(f"remote_url={state.get('remote_url')}")
    if task["status"] == "failed":
        raise SystemExit(1)


def status(_: argparse.Namespace) -> None:
    require_unsandboxed()
    state = refresh_session_identity(read_state())
    state["tasks"] = list_tasks()
    print(json.dumps(state, indent=2, sort_keys=True))


def stop(_: argparse.Namespace) -> None:
    require_unsandboxed()
    if not STATE_FILE.exists():
        cleanup_runtime()
        print("Claude Code visible session stopped")
        return
    state = read_state()
    for key in ("claude_pid", "controller_pid"):
        pid = int(state.get(key, 0) or 0)
        if pid and process_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    time.sleep(0.5)
    for key in ("claude_pid", "controller_pid"):
        pid = int(state.get(key, 0) or 0)
        if pid and process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    cleanup_runtime()
    print("Claude Code visible session stopped")
    print(f"session={state.get('session_name', 'unknown')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start")
    p.add_argument("--name", default=f"codex-claude-{time.strftime('%H%M%S')}")
    p.add_argument("--workdir", default=os.getcwd())
    p.set_defaults(func=start)

    p = sub.add_parser("send")
    p.add_argument("prompt")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force-new", action="store_true")
    p.add_argument("--ack-timeout", type=float, default=30.0)
    p.set_defaults(func=send)

    p = sub.add_parser("status")
    p.set_defaults(func=status)

    p = sub.add_parser("preflight")
    p.set_defaults(func=lambda _: print(json.dumps(run_preflight(), indent=2, sort_keys=True)))

    p = sub.add_parser("stop")
    p.set_defaults(func=stop)

    p = sub.add_parser("controller")
    p.add_argument("--name", required=True)
    p.add_argument("--workdir", required=True)
    p.set_defaults(func=controller)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
