#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


write_lock = threading.Lock()
runtime_dir: Path
tasks_dir: Path
state_file: Path
auth_token: str
mcp_ready = False


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def update_channel_state(**patch: Any) -> None:
    state = read_json(state_file)
    channel = dict(state.get("channel") or {})
    channel.update(patch)
    channel["updated_at"] = now_iso()
    state["channel"] = channel
    write_json(state_file, state)


def task_status_path(task_id: str) -> Path:
    return tasks_dir / task_id / "status.json"


def marker_path(task_id: str, status: str) -> Path:
    return tasks_dir / task_id / f"{status}.json"


def update_task(task_id: str, status: str, **extra: Any) -> dict[str, Any]:
    path = task_status_path(task_id)
    task = read_json(path)
    task.update(extra)
    task["id"] = task_id
    task["status"] = status
    task["updated_at"] = now_iso()
    write_json(path, task)
    write_json(marker_path(task_id, status), {"status": status, "timestamp": task["updated_at"]})
    return task


def send_rpc(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    with write_lock:
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()


def respond(message_id: Any, result: Any) -> None:
    send_rpc({"jsonrpc": "2.0", "id": message_id, "result": result})


def notify_channel(content: str, meta: dict[str, Any]) -> None:
    send_rpc(
        {
            "jsonrpc": "2.0",
            "method": "notifications/claude/channel",
            "params": {"content": content, "meta": meta},
        }
    )


def read_rpc() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        raw = line.decode("ascii", errors="replace").strip()
        if ":" in raw:
            key, value = raw.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    data = sys.stdin.buffer.read(length)
    return json.loads(data.decode("utf-8"))


def status_tool_schema() -> dict[str, Any]:
    return {
        "name": "delegate_status",
        "description": "Report machine-readable status for a Codex delegated task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string", "enum": ["ack", "done", "failed"]},
                "message": {"type": "string"},
            },
            "required": ["task_id", "status"],
            "additionalProperties": False,
        },
    }


def reply_tool_schema() -> dict[str, Any]:
    return {
        "name": "delegate_reply",
        "description": "Write the final or interim user-visible reply for a Codex delegated task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["task_id", "text"],
            "additionalProperties": False,
        },
    }


def handle_rpc(message: dict[str, Any]) -> None:
    global mcp_ready
    method = message.get("method")
    message_id = message.get("id")
    if method == "initialize":
        mcp_ready = True
        update_channel_state(mcp_initialized=True, mcp_initialized_at=now_iso())
        respond(
            message_id,
            {
                "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
                "serverInfo": {"name": "codex_delegate_channel", "version": "0.1.0"},
                "capabilities": {
                    "tools": {},
                    "experimental": {"claude/channel": {}},
                },
                "instructions": (
                    "Codex delegation tasks arrive as channel messages. For every task, first call "
                    "delegate_status with status ack and the task_id. Read the task file exactly, "
                    "perform the bounded task, call delegate_reply with the final response, then call "
                    "delegate_status with status done. If blocked, call delegate_status with status failed."
                ),
            },
        )
        return
    if method == "notifications/initialized":
        update_channel_state(mcp_ready=True, mcp_ready_at=now_iso())
        return
    if method == "tools/list":
        respond(message_id, {"tools": [status_tool_schema(), reply_tool_schema()]})
        return
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        task_id = str(args.get("task_id") or "")
        if name == "delegate_status" and task_id:
            status = str(args.get("status"))
            message_text = str(args.get("message") or "")
            update_task(task_id, status, status_message=message_text)
            respond(message_id, {"content": [{"type": "text", "text": f"status recorded: {status}"}]})
            return
        if name == "delegate_reply" and task_id:
            text = str(args.get("text") or "")
            response_path = tasks_dir / task_id / "response.txt"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(text.rstrip("\n") + "\n")
            update_task(task_id, read_json(task_status_path(task_id)).get("status", "ack"), response=str(response_path))
            respond(message_id, {"content": [{"type": "text", "text": "reply recorded"}]})
            return
        respond(message_id, {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True})
        return
    if message_id is not None:
        respond(message_id, {})


class Handler(BaseHTTPRequestHandler):
    server_version = "CodexDelegateChannel/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write((fmt % args) + "\n")
        sys.stderr.flush()

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self) -> bool:
        return self.headers.get("x-codex-delegate-token") == auth_token

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/health":
            self.send_json(404, {"error": "not found"})
            return
        self.send_json(200, {"ok": True, "mcp_ready": mcp_ready, "time": now_iso()})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/task":
            self.send_json(404, {"error": "not found"})
            return
        if not self.authenticated():
            self.send_json(403, {"error": "forbidden"})
            return
        body = self.read_body()
        task_id = str(body["task_id"])
        task_file = str(body["task_file"])
        update_task(task_id, "sent", channel_sent_at=now_iso())
        notify_channel(
            (
                f"Codex delegated task {task_id}.\n"
                f"Task file: {task_file}\n"
                "Required protocol: call delegate_status({task_id, status:'ack'}) before doing work; "
                "read the task file exactly; call delegate_reply({task_id, text}) with the final response; "
                "then call delegate_status({task_id, status:'done'}). If blocked, call status 'failed'."
            ),
            {"task_id": task_id, "task_file": task_file, "source": "codex-delegate"},
        )
        self.send_json(202, {"accepted": True, "task_id": task_id})


def start_http(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    actual_port = int(server.server_address[1])
    update_channel_state(http_url=f"http://127.0.0.1:{actual_port}", http_port=actual_port, http_ready=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    global runtime_dir, tasks_dir, state_file, auth_token
    runtime_dir = Path(args.runtime_dir)
    tasks_dir = runtime_dir / "tasks"
    state_file = runtime_dir / "current.json"
    auth_token = args.token
    runtime_dir.mkdir(parents=True, exist_ok=True)

    start_http(args.port)
    update_channel_state(server_pid=os.getpid(), server_started_at=now_iso())
    while True:
        message = read_rpc()
        if message is None:
            break
        handle_rpc(message)
    update_channel_state(server_exited_at=now_iso())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
