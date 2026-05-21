---
name: claude-code-delegate
description: Dispatch bounded work to a persistent Claude Agent SDK worker daemon, track task files, inspect results, and clean up without TUI input injection or Claude background jobs.
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

Use Claude as a bounded background worker pool. Codex remains the orchestrator, reviewer, integrator, and verifier.

`start` launches a local daemon with up to 3 worker slots. `send` only writes a task file and enqueues it, then returns immediately; completion is discovered later by explicit `status` checkpoints.

Each queued task runs in an isolated SDK conversation. The daemon stays warm, but task context is not reused across tasks. This avoids stale session context, cross-task contamination, and long-running reasoning from one previous task affecting the next one.

Claude workers are bounded edit workers. They may use read-only discovery tools inside recorded read paths and edit tools inside recorded write paths. They must not run tests, shell commands, package managers, servers, git commands, browser automation, MCP tools, or plugin tools. Codex performs all verification after Claude returns.

Each task is also bounded by a tool/turn contract:

- `max_turns`: 8
- `thinking`: disabled
- `effort`: low
- max tool calls per task: 16
- max read-only tool calls before the first write: 6

These are not wall-clock timeouts. They are task-contract guards. If Claude cannot make progress within the edit contract, the task should fail visibly instead of holding a worker indefinitely.

For substantial changes, do not send one broad task. Split work into the smallest independently reviewable tasks. Prefer 3 parallel workers when tasks have disjoint write paths.

Each task must have:

- one narrow objective
- allowed read paths
- allowed write paths
- forbidden files or directories
- explicit dependency ids when it must wait for previous work
- expected output
- stop conditions

Do not ask Claude to run tests. Ask Claude to make the file changes only. Codex runs tests and validates diffs.

Default large-change loop:

1. Decompose the target into small tasks, each with disjoint write paths when possible.
2. Start up to 3 workers.
3. Dispatch independent tasks in parallel with `send`.
4. Dispatch follow-up tasks with `--depends-on <task-id>` so they run only after dependencies are `done`.
5. Continue local Codex work or discussion without waiting.
6. Run `status --include-workers` at checkpoints.
7. For `done` tasks, inspect and verify artifacts directly with Codex.
8. Integrate or correct the result.
9. Stop workers or remove reviewed task records when appropriate.

Do not use Claude output as final verification. Claude may produce useful work, but Codex owns the final correctness decision.

## Procedure

1. Run preflight outside the Codex sandbox.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py preflight --workdir "$(pwd)"
```

Preflight verifies unsandboxed execution, runtime write access, Claude Code availability, and the Python SDK runtime.

2. Start the persistent worker pool.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py start --workdir "$(pwd)" --workers 3 --model opus
```

Worker count is capped at 3. Use fewer only when write paths overlap or the task is inherently sequential.
There is no wall-clock per-task timeout. If a task is wrong, stale, or unsafe, Codex must stop the worker pool explicitly and inspect direct file evidence.
Use `--clean-runtime` only when intentionally discarding the skill runtime's tracked task files.
`start --clean-runtime` is refused while an existing worker daemon is alive. Stop workers first.

3. Prepare a bounded task file from the template.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py template > /absolute/path/to/task.md
```

4. Send a bounded task.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send \
  --prompt-file /absolute/path/to/task.md \
  --read-path "$(pwd)/src" \
  --read-path "$(pwd)/tests" \
  --write-path "$(pwd)/src/module-a" \
  --label "module-a-api" \
  --group "checkpoint-8"
```

For dependent follow-up work:

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send \
  --prompt-file /absolute/path/to/follow-up.md \
  --read-path "$(pwd)/src" \
  --write-path "$(pwd)/src/module-b" \
  --depends-on "<previous-task-id>" \
  --label "module-b-integration" \
  --group "checkpoint-8"
```

`send` normalizes escaped `\n` for inline prompts, reads `--prompt-file` directly for long tasks, writes the full task to `runtime/tasks/<task-id>/task.md`, writes a queue item under `runtime/queue`, records `runtime/tasks/<task-id>/status.json`, and returns immediately. Queue order is recorded with a nanosecond monotonic-ish enqueue key. Duplicate prompts for the same workdir are not enqueued twice unless `--force-new` is passed.
Use `--read-path` and `--write-path` for bounded tasks. If omitted, both default to the workdir. Prefer file-level read paths: target file, direct dependency files, and the specific acceptance/test file Codex will later run. Do not pass broad source directories unless the task truly requires discovery. Write paths are automatically readable, so the target file does not need to be duplicated as a read path. The worker denies tool calls outside the recorded paths.
Use `--depends-on` to connect tasks. A dependent task stays queued until every dependency is `done`. If any dependency reaches a terminal non-`done` state or is missing, the dependent task becomes `failed`; it is not retried or auto-rerouted.
After `send`, Codex must keep the conversation available. Do not wait inline for Claude completion; use a later `status` checkpoint.

5. Check status.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status --include-workers
```

`status` reads runtime task files, daemon state, and worker state. It does not infer completion from terminal output. The default output is compact; use `--verbose` to include full SDK result payloads.
If the daemon is dead while tasks are still `queued` or `running`, `status` marks those tasks `failed`.
`status` also reports `runtime_status` and `daemon_alive`, so a stopped worker pool is mechanically visible even if old task records remain.

Task states:

- `created`: task file and status file were written.
- `queued`: task is waiting for an SDK worker.
- `running`: a worker has accepted the task.
- `done`: SDK returned a non-error `ResultMessage`.
- `failed`: SDK returned an error result or worker execution raised.
- `stopped`: reserved for interrupted task support.
- `removed`: task record was removed from active consideration.
- `dry-run`: task state was written without enqueueing Claude.

Running task records also include the enforced session and budget fields:

- `session_policy`: `isolated-per-task`
- `max_turns`
- `thinking`
- `effort`
- `max_tool_calls`
- `max_read_calls_before_write`

6. Inspect and verify.

Codex inspects changed files, task `status.json`, task `events.jsonl`, and direct worktree evidence. Codex runs tests when appropriate. Claude's result is not treated as verification by itself.

7. Stop workers or remove task records when appropriate.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py stop --workers
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py rm "<task-id>"
```

`stop --workers` marks queued/running tasks as `stopped`, removes their queue items, and stops the daemon.

## Hard Rules

Do not run this skill inside the Codex sandbox. Always establish the unsandboxed execution environment first with `preflight`.

Do not inject work into Claude by writing to a PTY, FIFO, paste buffer, Remote Control, or TUI input line.

Do not use `claude --bg` as the ordinary dispatch path. This experimental skill uses only the persistent Claude Agent SDK worker pool.

Do not block the Codex conversation waiting for Claude completion after `send`. Completion is discovered by explicit `status` checkpoints.

Do not treat Claude output as the source of truth for correctness. Use direct worktree inspection and tests.

Do not ask Claude delegate workers to run tests or commands. Delegate workers are for file reads and file edits only; Codex handles command execution and verification.

Always run delegate workers with `opus`. Do not use `sonnet` for normal delegate work.
The script enforces this at `start` and daemon launch time. Treat a non-`opus` model request as a configuration error, not as a lower-cost fallback.

The SDK worker must be tool-isolated. Each task starts with MCP servers, plugins, skills, agents, and user/project/local setting sources disabled. It uses a `PreToolUse` hook to gate every tool call, including calls that Claude Code would otherwise auto-allow. Only read-only discovery tools (`Read`, `LS`, `Glob`, `Grep`) are allowed within recorded read paths, and only edit tools (`Edit`, `MultiEdit`, `Write`) are allowed within recorded write paths. The hook also enforces the per-task tool budget and pre-edit read budget.

Do not reuse Claude conversation context across delegated tasks. Worker slots may persist, but SDK conversations are isolated per task.

## Task Template Contract

Every substantial Claude task file should follow this structure:

```markdown
# Claude Delegate Task

## Objective
- One narrow, independently reviewable change.

## Context
- What Claude needs to know before editing.
- Mention related task ids if this task depends on previous Claude work.

## Allowed Read Paths
- /absolute/path/or/workdir-relative/path

## Allowed Write Paths
- /absolute/path/or/workdir-relative/path

## Forbidden
- Do not edit tests unless this task explicitly owns tests.
- Do not run shell commands, tests, package managers, servers, git, browsers, MCP, or external tools.
- Do not broaden scope.

## Required Changes
- Small bullet 1.
- Small bullet 2.

## Acceptance Contract
- What Codex will verify after completion.
- Expected files/functions/exports.

## Stop Conditions
- Stop if required files are missing.
- Stop if the requested change requires editing outside allowed write paths.

## Final Response
- Summarize changed files.
- Include TASK_DONE.
```
