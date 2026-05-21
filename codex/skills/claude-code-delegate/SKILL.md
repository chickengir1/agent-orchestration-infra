---
name: claude-code-delegate
description: Dispatch bounded work to a persistent Claude Agent SDK worker pool, track task files, inspect results, and clean up without TUI input injection or per-task Claude background sessions.
---

# Claude Code Delegate

## Requirements

This skill is experimental and uses only the persistent SDK worker-pool path. There is no legacy `claude --bg` fallback.

Required local runtime:

- Claude Code CLI available as `claude`
- Python 3.13 or compatible
- Skill venv at `~/.codex/skills/claude-code-delegate/.venv`
- `claude-agent-sdk` installed inside that venv

Install or repair the SDK runtime with:

```bash
python3 -m venv ~/.codex/skills/claude-code-delegate/.venv
~/.codex/skills/claude-code-delegate/.venv/bin/python -m pip install claude-agent-sdk
```

Do not run this skill inside the Codex sandbox. It controls local worker processes, runtime task files, and Claude Code SDK sessions.

## Operating Model

Use Claude as a warm bounded background worker. Codex remains the orchestrator, reviewer, integrator, and verifier.

`start` launches a local daemon. The daemon keeps one or more `ClaudeSDKClient` workers connected, so `send` only writes a task file and enqueues it. `send` returns immediately; completion is discovered later by explicit `status` checkpoints.

For substantial changes, do not send one broad task. Split work into bounded tasks with:

- narrow objective
- allowed files or directories
- forbidden files or directories
- whether file edits are allowed
- expected output
- stop conditions

Default large-change loop:

1. Decompose the target into bounded Claude tasks.
2. Dispatch each task with `send`.
3. Continue local Codex work or discussion without waiting.
4. Run `status --include-workers` at checkpoints.
5. For `done` tasks, inspect and verify artifacts directly.
6. Integrate or correct the result.
7. Stop workers or remove reviewed task records when appropriate.

Do not use Claude output as final verification. Claude may produce useful work, but Codex owns the final correctness decision.

## Procedure

1. Run preflight outside the Codex sandbox.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py preflight --workdir "$(pwd)"
```

Preflight verifies unsandboxed execution, runtime write access, Claude Code availability, and the Python SDK runtime.

2. Start the persistent worker pool.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py start --workdir "$(pwd)" --workers 1 --model sonnet
```

Use `--clean-runtime` only when intentionally discarding the skill runtime's tracked task files.

3. Send a bounded task.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send "<prompt>"
```

`send` normalizes escaped `\n`, writes the full task to `runtime/tasks/<task-id>/task.md`, writes a queue item under `runtime/queue`, records `runtime/tasks/<task-id>/status.json`, and returns immediately. Queue order is recorded with a nanosecond monotonic-ish enqueue key. Duplicate prompts for the same workdir are not enqueued twice unless `--force-new` is passed.

4. Check status.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status --include-workers
```

`status` reads runtime task files, daemon state, and worker state. It does not infer completion from terminal output. The default output is compact; use `--verbose` to include full SDK result payloads.

Task states:

- `created`: task file and status file were written.
- `queued`: task is waiting for an SDK worker.
- `running`: a worker has accepted the task.
- `done`: SDK returned a non-error `ResultMessage`.
- `failed`: SDK returned an error result or worker execution raised.
- `stopped`: reserved for interrupted task support.
- `removed`: task record was removed from active consideration.
- `dry-run`: task state was written without enqueueing Claude.

5. Inspect and verify.

Codex inspects changed files, task `status.json`, task `events.jsonl`, and direct worktree evidence. Claude's result is not treated as verification by itself.

6. Stop workers or remove task records when appropriate.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py stop --workers
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py rm "<task-id>"
```

## Hard Rules

Do not run this skill inside the Codex sandbox. Always establish the unsandboxed execution environment first with `preflight`.

Do not inject work into Claude by writing to a PTY, FIFO, paste buffer, Remote Control, or TUI input line.

Do not use `claude --bg` as the ordinary dispatch path. This experimental skill uses only the persistent Claude Agent SDK worker pool.

Do not block the Codex conversation waiting for Claude completion after `send`. Completion is discovered by explicit `status` checkpoints.

Do not treat Claude output as the source of truth for correctness. Use direct worktree inspection and tests.
