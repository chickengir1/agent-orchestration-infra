---
name: claude-code-delegate
description: Start a Claude Code remote-control session without opening Terminal, report the Claude remote URL to the user, send prompts into that same session, inspect results, and keep the session alive until explicitly stopped.
---

# Claude Code Delegate

## Procedure

1. Run preflight outside the Codex sandbox.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py preflight
```

This skill must not be operated inside the Codex sandbox. It owns local ports, a long-running Claude process, runtime state, and a local MCP channel server. Preflight verifies that execution is unsandboxed, the runtime directory is writable, localhost bind works, the channel server parses, and `claude --version` works. Do not continue to `start`, `send`, `status`, or `stop` unless preflight passes. `start` also runs this preflight internally before it creates or replaces runtime state.

2. Start a Claude Code Remote Control session with the Codex delegate channel.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py start --name "<session-name>" --workdir "$(pwd)"
```

`start` creates the runtime MCP config, registers the channel server in Claude Code local MCP config for the target workdir, launches Claude Code with `--dangerously-load-development-channels server:codex_delegate_channel`, waits for Remote Control, waits for the channel MCP server, sends a handshake task, and only reports ready after Claude acknowledges and completes that handshake through the channel reply tools.

During research-preview channel development, Claude Code shows an official local-development confirmation prompt before loading a custom channel. The controller may answer that exact startup confirmation once, after matching the expected prompt text. This is not a task delivery path and must never be used to inject user work into the TUI.

3. Report the printed `remote_url` to the user. The user watches Claude through Claude Code Remote Control, not a local Terminal window.

4. Send work through the channel task-file transport.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send "<prompt>"
```

The send command never writes prompt text into the Remote Control TUI and never starts a fallback `claude --resume --print` process. It normalizes escaped `\n`, writes the full task to `runtime/tasks/<task-id>/task.md`, creates `status.json` plus status marker files, then posts the task to the already-running local channel server. The channel server emits a Claude Code channel notification into the active session.

Claude must call the channel reply tools:

- `delegate_status({ task_id, status: "ack" })` before doing work.
- `delegate_reply({ task_id, text })` with the final response.
- `delegate_status({ task_id, status: "done" })` after finishing, or `failed` if blocked.

`send` returns after `ack`, `done`, or `failed`. It does not retry and does not use another transport. If the channel is not ready, the session was started incorrectly and must be restarted with `start`.

5. Codex inspects changed files and runs verification.

6. Keep the session open across checkpoints. Stop only when the user explicitly asks to end the Claude Code delegate session.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py stop
```

## Status

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status
```

`status` prints the Remote Control URL, bridge session id, resolved Claude session id, channel state, and every task state. Task states are:

- `pending`: task file and status were created.
- `sent`: task was accepted by the local channel server and emitted as a channel notification.
- `ack`: Claude called `delegate_status` with `ack`.
- `done`: Claude called `delegate_status` with `done`; response is in `runtime/tasks/<task-id>/response.txt` when Claude also called `delegate_reply`.
- `failed`: channel delivery or Claude execution failed; do not auto-retry.
- `dry-run`: `send --dry-run` wrote state without invoking Claude.

If the same prompt is sent again for the same Claude session, `send` reports the existing task and does not send a duplicate. Use `--force-new` only when the user explicitly wants a separate new task.

Dry-run verification:

```bash
python3 -c 'p="/Users/leegangho/.codex/skills/claude-code-delegate/scripts/visible_claude.py"; compile(open(p).read(), p, "exec")'
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py preflight
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send --dry-run "DRY RUN ONLY: do not modify files."
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status
```

## Hard Rule

Do not open macOS Terminal, iTerm, tmux, or any local visible shell for Claude Code delegation. The only user-visible surface is the `remote_url` returned by Claude Code Remote Control.

Do not run this skill inside the Codex sandbox. Always establish the unsandboxed local-port execution environment first with `preflight`. If preflight fails, stop and fix the environment; do not proceed by trying the same command in sandboxed mode.

Do not stop/delete the active runtime state after each checkpoint. Preserve the session until the user explicitly says to stop or end it.

Do not inject work into Claude by writing to a PTY, FIFO, paste buffer, or TUI input line. Do not tune submit keys such as return, escape, or control sequences as a delivery mechanism. Do not fall back to `claude --resume --print` for ordinary delegation. If the channel handshake fails, the session is not ready. If a task does not reach `ack`, record `failed` and stop.
