---
name: claude-code-delegate
description: Delegate work from Codex to the local Claude Code CLI. Use whenever Codex should send a prompt to Claude Code, let Claude do the main worker task in a visible or streamed session, avoid permission stalls when explicitly allowed, then inspect and verify the result as orchestrator/reviewer.
---

# Claude Code Delegate

## Core

Codex sends a bounded prompt to Claude Code. Claude Code does the worker task. Codex reviews the result before trusting it.

That is the whole model.

## Roles

- Codex owns intent, scope, prompt quality, review, verification, and the final user report.
- Claude Code owns the assigned worker task.
- Claude output is not trusted until Codex checks the changed files and validation result.

## Basic Flow

1. Codex reads enough local context to define the task.
2. Codex writes one clear worker prompt.
3. Codex sends the prompt to Claude Code.
4. Claude Code works in a visible, streamed, or resumable session.
5. Codex inspects what changed.
6. Codex runs the needed verification.
7. Codex reports what happened.

## Preflight

- Check Claude Code exists with `claude --version`.
- If using Remote Control, the Claude session must be authenticated with claude.ai OAuth.
- If `claude --print` returns `Not logged in`, use an authenticated existing session or have the user run `/login`; do not misclassify this as a permission problem.
- If Codex is sandboxed and `--resume <session-id>` cannot read `~/.claude/projects/...jsonl`, rerun the same Claude command through the approved outside-sandbox path.

## Transport

Use the simplest transport that satisfies the user's visibility requirement.

### Visible Session

Use this when the user wants to watch Claude Code work.

Preferred official path:

```bash
claude --remote-control "<name>" --permission-mode acceptEdits
```

If the user explicitly wants the worker not to stop on permissions in a trusted local workspace:

```bash
claude --remote-control "<name>" --permission-mode bypassPermissions
```

Then send the bounded prompt into that open Claude Code session. On macOS Terminal this can be done by opening Claude in a visible terminal and using Terminal's own `do script` command to submit text to that session. If `tmux` is installed, a common alternative is to run Claude inside tmux and use `tmux send-keys`.

### Streamed Worker

Use this when visible terminal control is not required but Codex should see live output.

```bash
claude --print \
  --output-format stream-json \
  --verbose \
  --include-partial-messages \
  --include-hook-events \
  --permission-mode acceptEdits \
  "<prompt>"
```

### Resumable Worker

Use this when a Claude session id is already known.

```bash
claude --resume <session-id> --print "<prompt>"
```

### Fresh Non-Interactive Worker

Use this for quick bounded tasks where a transcript is enough.

```bash
claude --print "<prompt>"
```

## Permissions

Do not solve permission stalls by adding vague instructions to the prompt. Use Claude Code permission modes and allowlists.

- `acceptEdits`: normal default for code work; reads and edits can proceed with fewer prompts.
- `allowedTools`: pre-approve known safe commands for a task, such as read commands, package manager tests, or project lint commands.
- `bypassPermissions` / `--dangerously-skip-permissions`: use only when the user explicitly wants uninterrupted work in a trusted or isolated workspace.

If permissions still block the worker, Codex must report the exact blocker and either relaunch with the approved permission mode or narrow the task.

## Prompt Shape

```text
You are a bounded worker. Codex is the orchestrator and reviewer.

Task:
...

Allowed files:
...

Do not touch:
...

Constraints:
- Do not broaden scope.
- Do not make product or architecture decisions.
- Do not edit outside the allowed files.
- Do not perform unrelated cleanup.
- If blocked by permissions or missing credentials, stop and report the exact blocker.

Expected output:
- Changed files
- Summary
- Validation run, or "not run"
- Blockers
```

If the task is too broad to express this way, Codex must split it before sending it.

## Review

After Claude finishes, Codex must inspect the actual files, not only Claude's summary.

- Check changed files.
- Check scope.
- Run the needed tests or inspection.
- Fix, reject, or re-delegate if the patch is wrong.
- Report only the verified result.

If `claude` is missing, unauthenticated, blocked, or still running unexpectedly, stop and report the blocker.

## Common Patterns

- Official visible control: `claude --remote-control`.
- Terminal source of truth: keep Claude Code running in a visible terminal, then inject the Codex-authored prompt.
- tmux/PTY control: common for long-running or remote sessions; use `tmux send-keys` when tmux exists.
- Hooks: useful for notifications, logging, formatting, and permission routing; they are optional infrastructure, not required for basic delegation.
