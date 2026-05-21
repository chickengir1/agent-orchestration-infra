---
name: claude-code-delegate
description: Dispatch bounded work to Claude Code background agents, track state from Claude's local job files, inspect results, and clean up without using TUI input injection.
---

# Claude Code Delegate

## Procedure

1. Run preflight outside the Codex sandbox.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py preflight --workdir "$(pwd)"
```

This skill must not be operated inside the Codex sandbox. It manages local Claude background-agent state under `~/.claude/jobs` and runtime state under `~/.codex/skills/claude-code-delegate/runtime`. Preflight verifies unsandboxed execution, runtime write access, Claude Code availability, and `claude agents --json`.

2. Start the delegate runtime.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py start --workdir "$(pwd)"
```

`start` does not open Terminal, iTerm, tmux, Remote Control, or a TUI. It records a ready runtime for background-agent delegation. Use `--clean-runtime` only when intentionally discarding the skill runtime's tracked task files.

3. Send a bounded task.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send "<prompt>"
```

`send` normalizes escaped `\n`, writes the full task to `runtime/tasks/<task-id>/task.md`, then dispatches a short wrapper through:

```bash
claude --bg "<wrapper pointing at task.md>"
```

The returned short background id is stored in `runtime/tasks/<task-id>/status.json`. Duplicate prompts for the same workdir are not dispatched twice unless `--force-new` is passed.

Use `--wait <seconds>` when Codex should block until Claude's local job state reaches `done`, `failed`, or `stopped`.

4. Check status.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status --include-agents
```

`status` refreshes tracked tasks from `~/.claude/jobs/<bg-id>/state.json`. That job `state.json` is the authoritative machine-readable source for completion. `claude logs <id>` is useful for human inspection, but it includes TUI/ANSI output and is not the primary state source.

Task states:

- `created`: task file and status file were written.
- `dispatched`: `claude --bg` returned a background id.
- `running`: the job exists but has not reached a terminal state.
- `done`: `~/.claude/jobs/<id>/state.json` has `state: "done"`.
- `failed`: dispatch or job state failed.
- `timeout`: `send --wait` timed out before a terminal job state.
- `stopped`: the background job was stopped.
- `removed`: the background job was removed.
- `dry-run`: task state was written without dispatching Claude.

5. Inspect and verify.

Codex inspects changed files, the task `status.json`, `~/.claude/jobs/<id>/state.json`, and, when useful, `timeline.jsonl` or `claude logs <id>`. Claude's result is not treated as verification by itself.

6. Stop or remove tracked jobs when explicitly appropriate.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py stop
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py rm "<task-id-or-bg-id>"
```

`stop` stops non-terminal tracked background jobs with `claude stop <id>`. `rm` removes Claude background sessions with `claude rm <id>`.

## Hard Rules

Do not run this skill inside the Codex sandbox. Always establish the unsandboxed execution environment first with `preflight`.

Do not inject work into Claude by writing to a PTY, FIFO, paste buffer, Remote Control, or TUI input line. Do not tune submit keys such as return, escape, or control sequences as a delivery mechanism.

Do not use `claude --resume --print` as a fallback for ordinary delegation. The primary and only task dispatch path is Claude Code background agents via `claude --bg`.

Do not treat `claude logs` as the source of truth for completion. Use `~/.claude/jobs/<id>/state.json`, then verify artifacts directly.
