---
name: claude-code-delegate
description: Delegate code work from Codex to Claude Code through Claude Code Remote Control. Use when Codex should prepare a bounded worker prompt, Claude Code must be visible in claude.ai/code or the Claude mobile app, permission mode is auto, and Codex must inspect and verify the result afterward.
---

# Claude Code Delegate

## Contract

Codex is the orchestrator and reviewer. Claude Code is the visible worker.

Default path:

```text
Codex writes a bounded worker prompt
-> Claude Code runs through Remote Control
-> user can watch in claude.ai/code or the Claude app
-> Codex inspects changed files and verifies the result
```

## Hard Rules

- Use Claude Code Remote Control for delegated work.
- Use permission mode `auto`.
- Do not use budget or cost flags.
- Do not use Terminal injection, AppleScript keystrokes, tmux, hooks, headless runners, or `--print`.
- Do not treat sandbox-only auth failure as user logout; run Remote Control from the authenticated host context.

## Remote Control Preflight

Check locally before delegation:

```bash
claude --version
claude auth status --json
```

Required facts:

- Host auth must report `loggedIn: true`.
- Remote Control requires claude.ai subscription/OAuth auth, not API-key auth.
- The project must have accepted Claude Code workspace trust at least once.
- Codex sandbox may report `loggedIn: false`; that is not the user's login state if host auth is true.

## Start Visible Delegation

Start a Remote Control session in the target repo from the authenticated host context:

```bash
claude --remote-control "<session-name>" --permission-mode auto "<bounded worker prompt>"
```

If no initial prompt should be sent yet, start the visible session only:

```bash
claude --remote-control "<session-name>" --permission-mode auto
```

The user watches and can steer from:

```text
https://claude.ai/code
```

or the Claude mobile app.

## Prompt Shape

```text
You are the Claude Code worker. Codex is the orchestrator and reviewer.

Task:
...

Allowed files:
...

Forbidden files:
...

Constraints:
- Do not broaden scope.
- Do not edit outside allowed files.
- Do not perform unrelated cleanup.
- Permission mode is auto.
- If blocked, show the exact blocker and wait.

Expected output:
- Changed files
- Summary
- Validation run, or "not run"
- Blockers
```

If the task cannot be bounded in this shape, Codex must split it before delegation.

## Codex Review

After Claude Code finishes, Codex must not trust the worker summary alone.

Codex must:

- inspect the actual changed files
- check forbidden paths were not touched
- run the narrow verification required for the task
- report only verified facts
