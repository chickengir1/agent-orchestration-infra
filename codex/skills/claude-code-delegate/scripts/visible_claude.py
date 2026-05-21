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
TERMINAL_TASK_STATES = {"done", "failed", "stopped", "timeout", "dispatch_failed", "removed"}


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


def wait_for_task(task: dict[str, Any], timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    current = task
    while time.time() < deadline:
        current = refresh_task_from_job(current)
        if current.get("status") in {"done", "failed", "stopped"}:
            return current
        time.sleep(0.5)
    return update_task(current, "timeout", timeout_seconds=timeout)


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
        if args.wait and task.get("status") == "dispatched":
            task = wait_for_task(task, args.wait)
    state["last_task"] = {"id": task_id, "status": task["status"], "task_file": str(task_file), "bg_id": task.get("bg_id")}
    write_state(state)
    print(f"task_id={task_id}")
    print(f"status={task['status']}")
    if task.get("bg_id"):
        print(f"bg_id={task['bg_id']}")
    print(f"task_file={task_file}")
    if task.get("status") in {"dispatch_failed", "failed", "timeout"}:
        raise SystemExit(1)


def status(args: argparse.Namespace) -> None:
    require_unsandboxed()
    state = read_state()
    tasks = refresh_all_tasks()
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


def resolve_task(identifier: str) -> dict[str, Any]:
    for task in list_tasks():
        if task.get("id") == identifier or task.get("bg_id") == identifier:
            return task
    raise SystemExit(f"no tracked task matches {identifier}")


def read_text_if_exists(path: Path | None, limit: int = 200_000) -> str | None:
    if not path or not path.exists():
        return None
    text = path.read_text(errors="replace")
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


def read_json_if_exists(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def text_from_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text":
            parts.append(str(item.get("text") or ""))
        elif item_type == "tool_use":
            parts.append(f"tool_use: {item.get('name') or 'unknown'}")
        elif item_type == "tool_result":
            parts.append("tool_result: " + str(item.get("content") or ""))
        elif item_type:
            parts.append(str(item_type))
    return "\n".join(part for part in parts if part)


def truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def summarize_jsonl_event(event: dict[str, Any]) -> dict[str, Any]:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    content = text_from_message_content(message.get("content"))
    attachment = event.get("attachment") if isinstance(event.get("attachment"), dict) else {}
    summary = {
        "timestamp": event.get("timestamp"),
        "type": event.get("type"),
        "role": message.get("role"),
        "uuid": event.get("uuid"),
        "summary": truncate(content or str(attachment.get("type") or ""), 2000),
    }
    if event.get("toolUseResult"):
        tool_result = event["toolUseResult"]
        if isinstance(tool_result, dict):
            summary["tool_result_type"] = tool_result.get("type")
            file_info = tool_result.get("file")
            if isinstance(file_info, dict):
                summary["tool_file"] = file_info.get("filePath")
    return {key: value for key, value in summary.items() if value not in (None, "")}


def load_jsonl_summaries(path: Path | None, max_events: int = 200) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                events.append({"type": "invalid-json", "summary": truncate(line)})
                continue
            if isinstance(parsed, dict):
                events.append(summarize_jsonl_event(parsed))
            if len(events) >= max_events:
                break
    return events


def html_table(rows: list[tuple[str, Any]]) -> str:
    cells = []
    for key, value in rows:
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, indent=2, sort_keys=True)
        else:
            rendered = "" if value is None else str(value)
        cells.append(f"<tr><th>{html.escape(key)}</th><td><pre>{html.escape(rendered)}</pre></td></tr>")
    return "<table>" + "\n".join(cells) + "</table>"


def html_events(events: list[dict[str, Any]], empty: str) -> str:
    if not events:
        return f"<p class=\"muted\">{html.escape(empty)}</p>"
    items = []
    for event in events:
        heading_parts = [str(event.get("timestamp") or ""), str(event.get("type") or "event")]
        if event.get("role"):
            heading_parts.append(str(event["role"]))
        heading = " · ".join(part for part in heading_parts if part)
        summary = str(event.get("summary") or "")
        meta = {key: value for key, value in event.items() if key not in {"timestamp", "type", "role", "summary"}}
        meta_html = ""
        if meta:
            meta_html = f"<pre class=\"meta\">{html.escape(json.dumps(meta, indent=2, sort_keys=True))}</pre>"
        items.append(
            "<article class=\"event\">"
            f"<h3>{html.escape(heading)}</h3>"
            f"<pre>{html.escape(summary)}</pre>"
            f"{meta_html}"
            "</article>"
        )
    return "\n".join(items)


def render_view_html(data: dict[str, Any]) -> str:
    task = data["task"]
    job_state = data.get("job_state") or {}
    status_class = html.escape(str(task.get("status") or "unknown"))
    output_result = task.get("output_result")
    if not output_result and isinstance(job_state.get("output"), dict):
        output_result = job_state["output"].get("result")
    task_rows = [
        ("task id", task.get("id")),
        ("status", task.get("status")),
        ("bg id", task.get("bg_id")),
        ("workdir", task.get("workdir")),
        ("created", task.get("created_at")),
        ("updated", task.get("updated_at")),
        ("task file", task.get("task_file")),
        ("job state source", data.get("job_state_source")),
        ("timeline file", data.get("timeline_file")),
        ("transcript file", data.get("transcript_file")),
        ("output result", output_result),
    ]
    job_rows = [
        ("state", job_state.get("state")),
        ("detail", job_state.get("detail")),
        ("session id", job_state.get("sessionId")),
        ("created", job_state.get("createdAt")),
        ("updated", job_state.get("updatedAt")),
        ("first terminal", job_state.get("firstTerminalAt")),
        ("cwd", job_state.get("cwd")),
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Claude Delegate Task {html.escape(str(task.get("id")))}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f5ef;
      --panel: #ffffff;
      --ink: #18201f;
      --muted: #66706d;
      --line: #d8ded9;
      --accent: #146c5f;
      --accent-2: #8b4c2f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; gap: 16px; align-items: baseline; justify-content: space-between; margin-bottom: 22px; }}
    h1 {{ font-size: 24px; margin: 0; font-weight: 700; }}
    h2 {{ font-size: 16px; margin: 28px 0 10px; }}
    h3 {{ font-size: 13px; margin: 0 0 6px; color: var(--accent); }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--accent);
      border-radius: 999px;
      padding: 4px 10px;
      font-weight: 700;
    }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }}
    section, .event {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ width: 160px; text-align: left; vertical-align: top; color: var(--muted); font-weight: 600; padding: 8px 10px 8px 0; }}
    td {{ padding: 8px 0; border-top: 1px solid var(--line); }}
    tr:first-child td {{ border-top: 0; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    .muted {{ color: var(--muted); margin: 0; }}
    .event {{ margin-bottom: 10px; }}
    .meta {{ margin-top: 8px; color: var(--accent-2); }}
    @media (max-width: 800px) {{
      main {{ padding: 16px; }}
      header {{ display: block; }}
      .grid {{ grid-template-columns: 1fr; }}
      th {{ width: 110px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Claude Delegate Task</h1>
      <span class="badge {status_class}">{html.escape(str(task.get("status") or "unknown"))}</span>
    </header>
    <div class="grid">
      <section>
        <h2>Task</h2>
        {html_table(task_rows)}
      </section>
      <section>
        <h2>Job State</h2>
        {html_table(job_rows)}
      </section>
    </div>
    <section>
      <h2>Task File</h2>
      <pre>{html.escape(data.get("task_text") or "")}</pre>
    </section>
    <section>
      <h2>Timeline</h2>
      {html_events(data.get("timeline_events") or [], "timeline file is not available")}
    </section>
    <section>
      <h2>Transcript</h2>
      {html_events(data.get("transcript_events") or [], "transcript file is not available")}
    </section>
  </main>
</body>
</html>
"""


def export_view(args: argparse.Namespace) -> None:
    require_unsandboxed()
    task = resolve_task(args.identifier)
    if task.get("status") not in TERMINAL_TASK_STATES:
        task = refresh_task_from_job(task)
    if task.get("status") not in TERMINAL_TASK_STATES:
        raise SystemExit(f"task {task.get('id')} is {task.get('status')}; export-view only runs for terminal tasks")

    task_id = str(task["id"])
    bg_id = task.get("bg_id")
    live_job_state = read_json_if_exists(job_state_path(str(bg_id))) if bg_id else None
    cached_job_state = task.get("job_state") if isinstance(task.get("job_state"), dict) else None
    job_state = live_job_state or cached_job_state or {}
    job_state_source = str(job_state_path(str(bg_id))) if live_job_state and bg_id else "task status cache"

    task_path = Path(str(task.get("task_file"))) if task.get("task_file") else None
    timeline_file = Path(str(task.get("timeline_file"))) if task.get("timeline_file") else None
    transcript_path_value = job_state.get("linkScanPath") if isinstance(job_state, dict) else None
    transcript_file = Path(str(transcript_path_value)) if transcript_path_value else None

    data = {
        "generated_at": now_iso(),
        "task": task,
        "task_text": read_text_if_exists(task_path) or "",
        "job_state": job_state,
        "job_state_source": job_state_source,
        "timeline_file": str(timeline_file) if timeline_file else None,
        "timeline_events": load_jsonl_summaries(timeline_file),
        "transcript_file": str(transcript_file) if transcript_file else None,
        "transcript_events": load_jsonl_summaries(transcript_file),
    }

    view_dir = VIEWS_DIR / task_id
    view_dir.mkdir(parents=True, exist_ok=True)
    data_path = view_dir / "data.json"
    html_path = view_dir / "index.html"
    write_json(data_path, data)
    html_path.write_text(render_view_html(data))
    print(f"view={html_path}")
    print(f"data={data_path}")


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
    p.add_argument("--wait", type=float, default=0.0, help="seconds to wait for done/failed after dispatch")
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

    p = sub.add_parser("export-view")
    p.add_argument("identifier", help="task id or Claude background short id")
    p.set_defaults(func=export_view)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
