#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pty
import select
import signal
import subprocess
import sys
import time
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = SKILL_DIR / "runtime"
STATE_FILE = RUNTIME_DIR / "current.json"
FIFO_FILE = RUNTIME_DIR / "input.fifo"
LOG_FILE = RUNTIME_DIR / "session.log"


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
        try:
            RUNTIME_DIR.rmdir()
        except OSError:
            pass


def start(args: argparse.Namespace) -> None:
    if STATE_FILE.exists():
        state = read_state()
        pid = int(state.get("controller_pid", 0) or 0)
        if pid and process_alive(pid):
            raise SystemExit(f"already running: {state.get('session_name')}")
        cleanup_runtime()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    command = (
        f"cd {shell_quote(args.workdir)} && "
        f"{shell_quote(str(Path(__file__).resolve()))} controller "
        f"--name {shell_quote(args.name)} "
        f"--workdir {shell_quote(args.workdir)}"
    )
    osa = (
        'tell application "Terminal" '
        f'to do script {json.dumps(command)}'
    )
    subprocess.run(["osascript", "-e", osa], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    deadline = time.time() + 20
    while time.time() < deadline:
        if STATE_FILE.exists():
            state = read_state()
            if state.get("status") == "ready":
                print("Claude Code visible session ready")
                print(f"session={state['session_name']}")
                print(f"terminal=visible")
                print(f"state={STATE_FILE}")
                return
        time.sleep(0.2)
    raise SystemExit("timeout waiting for visible Claude session")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def controller(args: argparse.Namespace) -> None:
    cleanup_runtime()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    os.mkfifo(FIFO_FILE)

    master_fd, slave_fd = pty.openpty()
    child = subprocess.Popen(
        ["claude", "--permission-mode", "auto", "--remote-control", args.name],
        cwd=args.workdir,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    fifo_fd = os.open(FIFO_FILE, os.O_RDONLY | os.O_NONBLOCK)
    fifo_keepalive_fd = os.open(FIFO_FILE, os.O_WRONLY | os.O_NONBLOCK)

    state = {
        "session_name": args.name,
        "status": "ready",
        "workdir": args.workdir,
        "controller_pid": os.getpid(),
        "claude_pid": child.pid,
        "fifo": str(FIFO_FILE),
        "log": str(LOG_FILE),
        "visible": "Terminal",
        "permission_mode": "auto",
    }
    write_state(state)

    try:
        with LOG_FILE.open("ab") as log:
            while True:
                if child.poll() is not None:
                    state["status"] = "exited"
                    state["exit_code"] = child.returncode
                    write_state(state)
                    break
                readable, _, _ = select.select([master_fd, fifo_fd], [], [], 0.2)
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
                    elif fd == fifo_fd:
                        try:
                            data = os.read(fifo_fd, 65536)
                        except BlockingIOError:
                            data = b""
                        if data:
                            os.write(master_fd, data)
    finally:
        for fd in (master_fd, fifo_fd, fifo_keepalive_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def send(args: argparse.Namespace) -> None:
    state = read_state()
    fifo = Path(state["fifo"])
    if not fifo.exists():
        raise SystemExit("active session input pipe missing")
    with fifo.open("w") as f:
        f.write(args.prompt.rstrip("\n") + "\n")
    print("prompt sent")
    print(f"session={state['session_name']}")


def status(_: argparse.Namespace) -> None:
    print(json.dumps(read_state(), indent=2))


def stop(_: argparse.Namespace) -> None:
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
    p.set_defaults(func=send)

    p = sub.add_parser("status")
    p.set_defaults(func=status)

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
