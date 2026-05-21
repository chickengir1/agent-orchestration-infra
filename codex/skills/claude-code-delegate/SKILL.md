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

Each task is also bounded by an edit contract:

- `max_turns`: 12
- `thinking`: disabled
- `effort`: low
- max tool calls per task: 16
- max read-only tool calls before the first write: 8
- max discovery calls (`Glob`, `Grep`, `LS`) before the first write: 2
- max read-only calls after the first write: 1

These are not wall-clock timeouts. They are task-contract guards. If Claude cannot make progress within the edit contract, the task should fail visibly instead of holding a worker indefinitely.

For substantial changes, do not send one broad task. Split work into the smallest independently reviewable tasks. Prefer 3 parallel workers when tasks have disjoint write paths. If a task would need to edit source and tests across multiple modules, split it into source-slice and test-slice tasks.
The script enforces this: a new non-dry-run task is rejected if its write paths overlap any active `created`, `queued`, or `running` task, unless the new task declares that active task in `--depends-on`.

Each task must have:

- one narrow objective
- allowed read paths
- allowed write paths
- forbidden files or directories
- explicit dependency ids when it must wait for previous work
- expected output, including exact values for non-obvious assertions
- stop conditions

Before dispatch, Codex must check that Required Changes and Acceptance Contract agree. If they disagree, fix the task contract first. Do not ask Claude to infer which side is correct through broad search.

Do not ask Claude to run tests. Ask Claude to make the file changes only. Codex runs tests and validates diffs.

Claude should not be used as an open-ended explorer. Codex must do enough investigation to provide exact target files, direct dependency files, and acceptance files. Use directory read paths only for intentional discovery tasks; normal implementation tasks should use file-level read paths.

Default large-change loop:

1. Codex performs read-only investigation and identifies exact files.
2. Codex decomposes the target into source slices, test slices, and integration slices. Each task should own one small write set.
3. Create a manifest for the checkpoint.
4. Add every task to the manifest with exact read paths, write paths, dependencies, and Codex-owned verification commands.
5. Validate the manifest in strict mode.
6. Start up to 3 workers.
7. Dispatch the manifest. Do not manually dispatch broad or unvalidated tasks for large work.
8. Continue local Codex work or discussion without waiting.
9. Run `status --include-workers` at checkpoints.
10. For `done` tasks, inspect and verify artifacts directly with Codex.
11. For `failed` tasks, inspect events and split smaller; do not resend the same broad task.
12. Integrate or correct the result.
13. Stop workers or remove reviewed task records when appropriate.

Do not use Claude output as final verification. Claude may produce useful work, but Codex owns the final correctness decision.

## Procedure

1. Run preflight outside the Codex sandbox.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py preflight --workdir "$(pwd)"
```

Preflight verifies unsandboxed execution, runtime write access, Claude Code availability, and the Python SDK runtime. It also triggers the local `claude-delegate-watch` launchd watcher once, so `runtime/monitor/heartbeat.json` is refreshed before work starts.

Codex must also create a thread-scoped heartbeat automation before any non-dry-run `send` or `dispatch` in this skill. That automation is a Codex app/thread concern. It must read `runtime/monitor/heartbeat.json`, report `checked_at`, daemon status, runtime status, running/queued task ids, and `last_task`, then let Codex resume normal status verification. Keep this thread-scoped automation active while any task is `created`, `queued`, or `running`.
The script enforces this lifecycle gate: non-dry-run `send` and `dispatch` require `--thread-heartbeat-automation-id <automation-id>`. The script reads `~/.codex/automations/<automation-id>/automation.toml` and rejects dispatch unless it is an `ACTIVE` heartbeat automation, has a `target_thread_id`, and its prompt mentions this skill's heartbeat file.

Treat heartbeat automation as a wake trigger, not as the source of truth. The heartbeat file may be one sampling interval behind task reality. When a heartbeat wakes Codex, immediately re-read direct task state with `status --include-workers` and the relevant `runtime/tasks/<task-id>/status.json`, then inspect artifacts. If task state and heartbeat disagree, trust the task status files and direct artifacts, optionally refresh the watcher once, and only delete the thread-scoped automation after direct verification is complete.

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

4. Validate a bounded task before dispatch.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py validate-task \
  --workdir "$(pwd)" \
  --prompt-file /absolute/path/to/task.md \
  --read-path "$(pwd)/src/module-a.ts" \
  --write-path "$(pwd)/src/module-a.ts" \
  --strict
```

`validate-task` checks required task sections, exact read/write path declarations in the task file, `TASK_DONE`, and rejects workdir-wide ownership in strict mode.

5. For one-off bounded work, send a bounded task.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send \
  --prompt-file /absolute/path/to/task.md \
  --read-path "$(pwd)/src" \
  --read-path "$(pwd)/tests" \
  --write-path "$(pwd)/src/module-a" \
  --label "module-a-api" \
  --group "checkpoint-8" \
  --thread-heartbeat-automation-id "<automation-id>"
```

For dependent follow-up work:

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send \
  --prompt-file /absolute/path/to/follow-up.md \
  --read-path "$(pwd)/src" \
  --write-path "$(pwd)/src/module-b" \
  --depends-on "<previous-task-id>" \
  --label "module-b-integration" \
  --group "checkpoint-8" \
  --thread-heartbeat-automation-id "<automation-id>"
```

`send` normalizes escaped `\n` for inline prompts, reads `--prompt-file` directly for long tasks, writes the full task to `runtime/tasks/<task-id>/task.md`, writes a queue item under `runtime/queue`, records `runtime/tasks/<task-id>/status.json`, and returns immediately. Queue order is recorded with a nanosecond monotonic-ish enqueue key. Duplicate prompts for the same workdir are not enqueued twice unless `--force-new` is passed.
Concurrent `send` invocations are serialized by a runtime lock before they create task records or update `current.json`; this supports dispatching multiple independent tasks quickly without corrupting runtime state.
Lifecycle commands that mutate runtime state (`start`, `send`, `status`, `stop`, and `rm`) use the same runtime lock, so start/stop/status transitions cannot interleave with task creation.
Use `--read-path` and `--write-path` for bounded tasks. If omitted, both default to the workdir. Prefer file-level read paths: target file, direct dependency files, and the specific acceptance/test file Codex will later run. Do not pass broad source directories unless the task truly requires discovery. Write paths are automatically readable, so the target file does not need to be duplicated as a read path. The worker denies tool calls outside the recorded paths.
Use `--depends-on` to connect tasks. A dependent task stays queued until every dependency is `done`. If any dependency reaches a terminal non-`done` state or is missing, the dependent task becomes `failed`; it is not retried or auto-rerouted.
After `send`, Codex must keep the conversation available. Do not wait inline for Claude completion; use a later `status` checkpoint.

6. For large work, use a manifest instead of direct `send`.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py manifest init \
  --workdir "$(pwd)" \
  --group "checkpoint-8" \
  --out /absolute/path/to/checkpoint-8.manifest.json

~/.codex/skills/claude-code-delegate/scripts/visible_claude.py manifest add \
  --manifest /absolute/path/to/checkpoint-8.manifest.json \
  --id module-a-api \
  --prompt-file /absolute/path/to/module-a.md \
  --read-path "$(pwd)/src/module-a.ts" \
  --write-path "$(pwd)/src/module-a.ts" \
  --verify-cmd "npm test -- module-a"

~/.codex/skills/claude-code-delegate/scripts/visible_claude.py manifest validate \
  --manifest /absolute/path/to/checkpoint-8.manifest.json \
  --strict

~/.codex/skills/claude-code-delegate/scripts/visible_claude.py dispatch \
  --manifest /absolute/path/to/checkpoint-8.manifest.json \
  --strict \
  --thread-heartbeat-automation-id "<automation-id>"
```

Manifest dependencies use manifest task ids. `dispatch` translates them to runtime task ids and records `runtime_task_id` back into the manifest. Manifest validation rejects overlapping write paths unless the tasks have an explicit dependency edge.

7. Check status.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status --include-workers
```

`status` reads runtime task files, daemon state, and worker state. It does not infer completion from terminal output. The default output is compact; use `--verbose` to include full SDK result payloads.
If the daemon is dead while tasks are still `queued` or `running`, `status` marks those tasks `failed`.
`status` also reports `runtime_status` and `daemon_alive`, so a stopped worker pool is mechanically visible even if old task records remain.
`status` also reports `thread_heartbeat_automation`. Use this field as the lifecycle gate for the Codex app automation:

- `recommended_action: create_or_keep`: the thread-scoped heartbeat automation must exist.
- `recommended_action: delete_if_present_after_verification`: remove the thread-scoped heartbeat automation after Codex has inspected and verified all terminal task artifacts for the current checkpoint.

Task states:

- `created`: task file and status file were written.
- `queued`: task is waiting for an SDK worker.
- `running`: a worker has accepted the task.
- `done`: SDK returned a non-error `ResultMessage`.
- `failed`: SDK returned an error result or worker execution raised.
- `stopped`: reserved for interrupted task support.
- `removed`: task record was removed from active consideration.
- `dry-run`: task state was written without enqueueing Claude.

Running task records also include the enforced session and guard fields:

- `session_policy`: `isolated-per-task`
- `max_turns`
- `thinking`
- `effort`
- `max_tool_calls`
- `max_read_calls_before_write`
- `max_discovery_calls_before_write`
- `max_post_write_read_calls`

8. Inspect and verify.

Codex inspects changed files, task `status.json`, task `events.jsonl`, and direct worktree evidence. Codex runs tests when appropriate. Claude's result is not treated as verification by itself.
If Codex was woken by the thread heartbeat automation, do not decide from the heartbeat snapshot alone. Heartbeat may still show `running` while the task `status.json` is already `done`, or may lag in the other direction. Reconcile by reading `status --include-workers`, the specific task `status.json`, and the expected output files.

When all checkpoint tasks are terminal and direct Codex verification is complete, delete the thread-scoped heartbeat automation created for this delegation run. Do not delete the global launchd watcher.

9. Stop workers or remove task records when appropriate.

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

Do not dispatch delegated work without first creating the thread-scoped heartbeat automation for this Codex conversation. Pass its actual automation id to `send` or `dispatch` with `--thread-heartbeat-automation-id`. Delete that thread-scoped automation after all active delegated work is terminal and verified.

Do not treat `runtime/monitor/heartbeat.json` as a completion proof. It is only a wake signal and coarse summary. Completion proof is the task status file plus direct artifact verification by Codex.

Do not treat Claude output as the source of truth for correctness. Use direct worktree inspection and tests.

Do not ask Claude delegate workers to run tests or commands. Delegate workers are for file reads and file edits only; Codex handles command execution and verification.

Always run delegate workers with `opus`. Do not use `sonnet` for normal delegate work.
The script enforces this at `start` and daemon launch time. Treat a non-`opus` model request as a configuration error, not as a weaker-model fallback.

The SDK worker must be tool-isolated. Each task starts with MCP servers, plugins, skills, agents, and user/project/local setting sources disabled. It uses a `PreToolUse` hook to gate every tool call, including calls that Claude Code would otherwise auto-allow. Only read-only discovery tools (`Read`, `LS`, `Glob`, `Grep`) are allowed within recorded read paths, and only edit tools (`Edit`, `MultiEdit`, `Write`) are allowed within recorded write paths. The hook also enforces the per-task tool-call and pre-edit read limits.

Discovery is intentionally leashed. `Glob`, `Grep`, and `LS` are limited before the first write and denied after the first write. Read-back after the first edit is limited. If Claude needs more discovery after editing, that is a signal to stop and dispatch a smaller follow-up task with clearer file ownership.

Subscription/accounting details are not part of delegate orchestration decisions. Optimize for Opus quality, low reasoning overhead, bounded scope, and fast completion; do not choose weaker models or change task routing for accounting reasons.

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

## Execution Rules
- Read only the target file, direct dependencies, and the acceptance file.
- Do not use Glob, Grep, or LS unless discovery is explicitly required.
- After the first edit/write, do not perform broad inspection. Finish or stop.
- Do not run commands or tests.

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
