---
name: claude-code-delegate
description: Start a visible Claude Code Remote Control session, give the user/Codex a prompt to send, inspect the result, and stop the session when done.
---

# Claude Code Delegate

## Procedure

1. Start Claude Remote Control from the target repo:

```bash
~/.codex/skills/claude-code-delegate/scripts/start_remote_control.sh "<session-name>" "$(pwd)"
```

The script opens the browser and writes the active URL/PID to:

```text
~/.codex/skills/claude-code-delegate/state/current.env
```

2. Send Claude the task prompt in the opened Remote Control UI.

Prompt template:

```md
Task:

Allowed files:

Forbidden files:

Expected output:
- Changed files
- Summary
- Validation
```

3. After Claude finishes, inspect the changed files and run the needed verification.

4. Stop the Remote Control session:

```bash
~/.codex/skills/claude-code-delegate/scripts/stop_remote_control.sh
```

## Commands

```bash
cat ~/.codex/skills/claude-code-delegate/state/current.env
```

Use this to see which Remote Control session Codex currently owns.
