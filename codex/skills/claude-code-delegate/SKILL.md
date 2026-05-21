---
name: claude-code-delegate
description: Start a visible Claude Code Remote Control session, use the session name in claude.ai/code, inspect the result, and stop the session when done.
---

# Claude Code Delegate

## Procedure

1. Start Claude Remote Control from the target repo:

```bash
~/.codex/skills/claude-code-delegate/scripts/start_remote_control.sh "<session-name>" "$(pwd)"
```

Use a recognizable session name, for example:

```bash
~/.codex/skills/claude-code-delegate/scripts/start_remote_control.sh "codex-sbe-web-v4" "$(pwd)"
```

The browser opens:

```text
https://claude.ai/code
```

and writes temporary runtime state to:

```text
~/.codex/skills/claude-code-delegate/state/current.env
```

2. In `https://claude.ai/code`, select the session name printed as `select_session=...`.

3. Send the task prompt in that selected Remote Control session.

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

4. After Claude finishes, inspect the changed files and run the needed verification.

5. Stop the Remote Control session:

```bash
~/.codex/skills/claude-code-delegate/scripts/stop_remote_control.sh
```

## Commands

```bash
cat ~/.codex/skills/claude-code-delegate/state/current.env
```

Use this while the session is running. The stop script deletes this runtime state.
