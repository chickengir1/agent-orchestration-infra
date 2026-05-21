---
name: claude-code-delegate
description: Start a visible Claude Code Terminal session, send prompts into that same session, let the user watch Claude work, inspect the result, and stop/delete runtime state afterward.
---

# Claude Code Delegate

## Procedure

1. Start a visible Claude Code session.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py start --name "<session-name>" --workdir "$(pwd)"
```

2. Send prompts into that same visible session.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py send "<prompt>"
```

3. The user watches the Terminal window where Claude Code is running.

4. Codex inspects changed files and runs verification.

5. Stop the visible session and delete runtime state/logs.

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py stop
```

## Status

```bash
~/.codex/skills/claude-code-delegate/scripts/visible_claude.py status
```
