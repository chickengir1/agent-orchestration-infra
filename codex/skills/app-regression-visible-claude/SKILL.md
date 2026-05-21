---
name: app-regression-visible-claude
description: Use when working on app-regression and the user wants Claude Code to write code while Codex remains the main planner, scope owner, reviewer, and verifier, especially when Claude should be visible through Remote Control, an existing Claude session, or a macOS Terminal fallback.
---

# App Regression Visible Claude

## Purpose

Use this skill to delegate bounded `app-regression` code changes to Claude Code while keeping Codex responsible for planning, scope control, review, and final headed browser verification.

This skill is for the local `sbe-web-v4` migration workflow where the user wants to see Claude Code working, not just receive silent `--print` output.

## Authority Model

- Codex owns checkpoint definition, allowed files, forbidden files, acceptance criteria, diff review, and user report.
- Claude Code owns only the assigned patch.
- Claude Code output is untrusted until Codex reviews the changed files and verifies behavior.
- Do not let Claude Code make architecture, product, or scope decisions.

## Checkpoint Template

Before delegating, write the checkpoint in this shape:

```text
Question:
  The one question this checkpoint answers.

Scope:
  What is allowed / what is explicitly out of scope.

Inputs:
  Files, ports, session id, commands, fixtures.

Success:
  Exact pass condition.

Allowed artifacts:
  Files/directories allowed to be created.

Stop:
  Conditions where Claude or Codex must stop and report.
```

If the checkpoint is not narrow enough to express this way, do not delegate yet.

## Visible Mode Selection

Prefer modes in this order:

1. **Remote Control** when available.
   - Start or use an existing Claude Code session with Remote Control enabled.
   - User can watch or steer through Claude Code web/mobile/terminal surfaces.
   - Use this for the cleanest official visible workflow.

2. **Existing Claude session resume** when a session id is known.
   - Send bounded prompts with:
     ```bash
     claude --resume <session-id> --print "<prompt>"
     ```
   - This is stable but not fully visual by itself.

3. **macOS Terminal fallback** when the user wants a visible local terminal and tmux is unavailable.
   - Open the session:
     ```bash
     osascript -e 'tell application "Terminal" to do script "cd /Users/leegangho/sbe-web-v4 && claude --resume <session-id>"'
     ```
   - Send a prompt to the selected tab/window with Terminal `do script`.
   - If a prompt appears in the input area but does not submit, send an empty Terminal `do script ""` to submit.
   - Do not rely on System Events keystrokes unless the user has granted accessibility permission.

4. **tmux + hooks** only if tmux is installed or the user explicitly wants it.
   - tmux is useful for multi-agent panes, notifications, and durable remote attach.
   - tmux is not required when Remote Control is available.

## Delegation Prompt Rules

Every Claude Code prompt must include:

```text
You are a bounded code worker. Do not reinterpret the request. Do not broaden scope.

Objective:
...

Question this checkpoint answers:
...

Allowed files:
...

Forbidden files / paths:
...

Strict constraints:
- Do not broaden scope.
- Do not edit outside allowed files.
- Do not touch credentials or storageState.
- Do not create unrelated reports/test-results/playwright-report.
- Do not run headed browser unless explicitly assigned.
- Do not add dependencies unless explicitly assigned.

Expected worker output:
- Changed files.
- Exact behavior change.
- Validation not run by worker.
- Blockers.
```

Use `--print` for bounded patch delegation unless the user specifically asks to steer interactively in the visible Terminal/Remote Control UI.

## App Regression Invariants

- `app-regression` work follows sequential checkpoints.
- Auth verification target is `4200`; gate login provider is `4199`.
- During auth-only checkpoints, do not run route probe, preflight, summary, or gate matrix.
- Browser validation that the user needs to observe must be headed.
- Sandbox localhost `EPERM` is not app failure. Re-run localhost-required commands outside the sandbox/escalated path before classifying the app state.
- Do not commit or expose `.local/credentials.json`, `.playwright/state.json`, cookie values, tokens, or raw credentials.
- Current route evidence policy: screenshots disabled, video evidence only where relevant.

## Review Workflow

After Claude finishes:

1. Read Claude's final worker output.
2. Compare the pre-delegation and post-delegation artifact snapshot.
3. Inspect changed files directly. If `app-regression` is gitignored, do not trust `git diff` alone.
4. Check scope:
   - only allowed files changed
   - forbidden files untouched
   - no generated/stale artifacts unless allowed
5. Run syntax checks locally as Codex.
6. Run headed browser verification only for the checkpoint's exact target.
7. Report:
   - what Claude changed
   - what Codex verified
   - any scope issue or residual risk

## Artifact Hygiene

Before sending a prompt to Claude, record the current result-artifact state for the checkpoint scope. At minimum check:

```bash
find app-regression -maxdepth 3 -type d | sort | sed '/node_modules/d'
find app-regression -maxdepth 3 -type f | sort | sed '/node_modules/d'
```

After Claude returns, run the same checks and identify whether any of these appeared or changed:

```text
app-regression/reports/
app-regression/test-results/
app-regression/playwright-report/
app-regression/screenshots/
app-regression/.playwright/auth-failure/
```

Do not assume a clean tree. If these artifacts existed before the delegation, say so explicitly. If the checkpoint forbids artifacts and new ones appear, treat it as a scope failure until explained.

Do not delete artifacts in a side conversation unless the user explicitly asks. In the main workflow, delete stale artifacts only when cleanup is the current approved checkpoint.

## Terminal Fallback Notes

The previously verified visible fallback on this machine:

```text
tmux was not installed.
macOS Terminal opened a visible Claude Code session successfully.
Terminal do script injected a smoke prompt.
Terminal do script "" submitted the prompt.
Claude replied READY.
System Events keypress failed due accessibility permission.
```

Use this only as a fallback. Prefer Remote Control when available.
