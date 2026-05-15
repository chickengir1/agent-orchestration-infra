#!/usr/bin/env python3
"""Create and run a bounded Claude Code delegation job."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKER_PROMPT = SKILL_ROOT / "assets" / "worker-system-prompt.md"
CHECK_SCOPE = SKILL_ROOT / "scripts" / "check_scope.py"


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Path(result.stdout.strip()).resolve()


def run_git_diff(repo: Path) -> str:
    result = subprocess.run(
        ["git", "diff"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def run_git_status(repo: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def default_permission_mode(repo: Path) -> str:
    parts = set(repo.parts)
    if ".claude" in parts or ".codex" in parts or ".agents" in parts:
        return "bypassPermissions"
    return "acceptEdits"


def run_validation_commands(repo: Path, commands: list[str], timeout: int) -> list[dict]:
    results: list[dict] = []
    for command in commands:
        try:
            proc = subprocess.run(
                command,
                cwd=repo,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            results.append(
                {
                    "command": command,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "timed_out": False,
                }
            )
        except subprocess.TimeoutExpired as exc:
            results.append(
                {
                    "command": command,
                    "returncode": 124,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                    "timed_out": True,
                }
            )
    return results


def render_validation_text(results: list[dict]) -> str:
    if not results:
        return "No validation commands configured.\n"

    chunks: list[str] = []
    for item in results:
        chunks.append(f"$ {item['command']}")
        chunks.append(f"returncode: {item['returncode']}")
        if item.get("timed_out"):
            chunks.append("timed_out: true")
        if item.get("stdout"):
            chunks.append("stdout:")
            chunks.append(str(item["stdout"]).rstrip())
        if item.get("stderr"):
            chunks.append("stderr:")
            chunks.append(str(item["stderr"]).rstrip())
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def render_task(objective: str, allowed: list[str], forbidden: list[str], validation: list[str]) -> str:
    allowed_block = "\n".join(f"- {item}" for item in allowed) or "- none"
    forbidden_block = "\n".join(f"- {item}" for item in forbidden) or "- none"
    validation_block = "\n".join(f"- {item}" for item in validation) or "- none"

    return f"""# Claude Code Delegation Task

## Objective
{objective.strip()}

## Authority
Codex owns intent, scope, architecture, review, and final integration.
Claude Code owns only the assigned patch.

## Allowed Files
{allowed_block}

## Forbidden Files
{forbidden_block}

## Constraints
- Do not reinterpret the task.
- Do not broaden scope.
- Do not make architecture decisions.
- Do not ask the user questions.
- Do not edit files outside the allowed scope.
- Do not refactor unrelated code.
- Apply the smallest correct patch that satisfies the objective.

## Code Shape Conventions
Write code within these conventions. Do not perform a broad cleanup pass just to satisfy them.

- Guard clauses: reject invalid, empty, unauthorized, unsupported, or irrelevant cases early.
- Flat happy path: handle exceptional paths first, then let normal execution read straight down.
- Funnel order: narrow first, validate second, decide third, transform fourth, then return or commit.
- Phase separation: avoid mixing validation, transformation, mutation, effects, and response construction in one block.
- Named decisions: name multi-clause domain rules or permission checks before using them.
- Named semantic values: name meaningful derived values before using them in conditions, payloads, or returns.
- Shallow control flow: avoid nested ternaries, deep branches, and multi-level callback logic.
- Explicit side effects: make network, storage, logging, analytics, DOM, global-state, event, or cache effects visible.
- Consistent return shapes: preserve the local result convention for validators, parsers, hooks, actions, and services.
- One responsibility per unit: do not combine orchestration, calculation, rendering, persistence, and policy unless the file already requires it.
- Local decision context: keep decision evidence near the decision, or name the decision at the call site.
- Invalid states hard to represent: validate boundaries, narrow before use, and prefer explicit variants or domain-specific shapes.

## Runner Validation
{validation_block}

Claude Code must not run these commands unless Codex explicitly enabled worker Bash for this job.
The delegation runner executes them after Claude Code exits and records the result.

## Report Format
Report only:
- changed files
- what changed
- validation not run by worker; runner will execute validation
- blockers, if any
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective", required=True, help="Concrete patch objective.")
    parser.add_argument("--allow", action="append", default=[], help="Allowed file path. Repeatable.")
    parser.add_argument("--forbid", action="append", default=[], help="Forbidden file or path prefix. Repeatable.")
    parser.add_argument("--validate", action="append", default=[], help="Validation command. Repeatable.")
    parser.add_argument("--job-id", help="Optional stable job id.")
    parser.add_argument("--dry-run", action="store_true", help="Write job files without invoking Claude.")
    parser.add_argument("--max-turns", default="6", help="Claude max turns. Defaults to 6.")
    parser.add_argument(
        "--permission-mode",
        choices=["acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan"],
        help="Claude permission mode. Defaults to bypassPermissions inside local agent/skill repos, otherwise acceptEdits.",
    )
    parser.add_argument(
        "--allow-worker-bash",
        action="store_true",
        help="Allow Claude Code to use Bash. Off by default; runner validation still runs after Claude exits.",
    )
    parser.add_argument(
        "--validation-timeout",
        type=int,
        default=600,
        help="Timeout in seconds for each runner validation command. Defaults to 600.",
    )
    parser.add_argument("--model", help="Optional Claude model or alias.")
    parser.add_argument("--max-budget-usd", help="Optional Claude Code API budget cap.")
    parser.add_argument(
        "--bare",
        action="store_true",
        help="Run Claude in minimal mode. Requires API-key/auth helper credentials; OAuth/keychain auth is not read.",
    )
    args = parser.parse_args()

    if not args.allow:
        print("delegate_claude.py: at least one --allow path is required", file=sys.stderr)
        return 2

    repo = repo_root()
    claude_bin = shutil.which("claude")
    if not claude_bin and not args.dry_run:
        print("delegate_claude.py: missing local 'claude' CLI binary", file=sys.stderr)
        return 2

    job_id = args.job_id or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    job_dir = repo / ".codex" / "delegations" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    task_path = job_dir / "task.md"
    allowed_path = job_dir / "allowed-files.txt"
    forbidden_path = job_dir / "forbidden-files.txt"
    validation_path = job_dir / "validation.txt"
    worker_prompt_path = job_dir / "worker-system-prompt.md"

    write_lines(allowed_path, args.allow)
    write_lines(forbidden_path, args.forbid)
    write_lines(validation_path, args.validate)
    worker_prompt_path.write_text(WORKER_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")
    task_path.write_text(render_task(args.objective, args.allow, args.forbid, args.validate), encoding="utf-8")
    (job_dir / "before.diff").write_text(run_git_diff(repo), encoding="utf-8")
    (job_dir / "before.status").write_text(run_git_status(repo), encoding="utf-8")

    permission_mode = args.permission_mode or default_permission_mode(repo)

    command = [
        claude_bin or "claude",
        "-p",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--max-turns",
        str(args.max_turns),
        "--permission-mode",
        permission_mode,
        "--tools",
        "Read,Edit,Write,Bash" if args.allow_worker_bash else "Read,Edit,Write",
        "--append-system-prompt-file",
        str(worker_prompt_path),
    ]
    if args.bare:
        command.append("--bare")
    if args.model:
        command.extend(["--model", args.model])
    if args.max_budget_usd:
        command.extend(["--max-budget-usd", args.max_budget_usd])

    command.append(f"Read {task_path.relative_to(repo)} and complete exactly that task.")
    (job_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")

    if args.dry_run:
        result = {"ok": True, "dry_run": True, "job_id": job_id, "job_dir": str(job_dir)}
        (job_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0

    proc = subprocess.run(command, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (job_dir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
    (job_dir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    (job_dir / "after.diff").write_text(run_git_diff(repo), encoding="utf-8")
    (job_dir / "after.status").write_text(run_git_status(repo), encoding="utf-8")

    scope_report = job_dir / "scope-report.json"
    scope_proc = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCOPE),
            "--repo",
            str(repo),
            "--allowed",
            str(allowed_path),
            "--forbidden",
            str(forbidden_path),
            "--before-diff",
            str(job_dir / "before.diff"),
            "--before-status",
            str(job_dir / "before.status"),
            "--output",
            str(scope_report),
        ],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    validation_results = run_validation_commands(repo, args.validate, args.validation_timeout)
    validation_ok = all(item["returncode"] == 0 for item in validation_results)
    (job_dir / "validation-results.json").write_text(
        json.dumps(validation_results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (job_dir / "validation-results.txt").write_text(
        render_validation_text(validation_results),
        encoding="utf-8",
    )

    result = {
        "ok": proc.returncode == 0 and scope_proc.returncode == 0 and validation_ok,
        "job_id": job_id,
        "job_dir": str(job_dir),
        "claude_returncode": proc.returncode,
        "scope_returncode": scope_proc.returncode,
        "validation_ok": validation_ok,
        "permission_mode": permission_mode,
        "stdout_log": str(job_dir / "stdout.log"),
        "stderr_log": str(job_dir / "stderr.log"),
        "scope_report": str(scope_report),
        "validation_results": str(job_dir / "validation-results.json"),
    }
    (job_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
