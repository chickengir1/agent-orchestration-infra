---
name: claude-code-delegate
description: Delegate bounded code-editing tasks from Codex to the local Claude Code CLI while Codex remains the planner, scope owner, reviewer, and final integrator. Use when the user asks Codex to send a code modification request to Claude Code, trigger Claude Code from the CLI, run Claude Code as a constrained worker, review Claude Code's diff, or compare code-reading predictions with the actual execution sequence after delegation.
---

# Claude Code Delegate

## Overview

Use this skill to let Codex call Claude Code as a bounded code-editing worker. Claude Code must not act as a co-agent, architect, product decision-maker, or user-facing collaborator; it receives a narrow job spec, edits within scope, and reports machine-checkable results for Codex to review.

## Authority Model

Codex owns intent, scope, architecture, review, and final integration.
Claude Code owns only the assigned patch.

Reject delegation when the task requires unresolved product judgment, broad architecture, unrelated refactors, production access, or user clarification.

## Delegation Workflow

1. Read the relevant repo context first. Do not outsource the initial understanding step.
2. Decide whether the task is small enough for a bounded worker patch.
3. Define the objective, allowed files, forbidden files, constraints, validation commands, and expected report format.
4. Create a job directory under `.codex/delegations/<job-id>/`.
5. Run `scripts/delegate_claude.py` with the objective and file scope, or write the job spec manually when the runner is not suitable.
6. Let Claude Code edit only inside the assigned scope. By default it does not get Bash.
7. Inspect the saved scope report and runner validation report.
8. Review the resulting git diff yourself.
9. Repair or reject any incorrect, overbroad, or scope-violating patch.
10. Run any additional final validation as Codex before reporting completion.

## Runner Quick Start

From the repository root:

```bash
python3 ~/.codex/skills/claude-code-delegate/scripts/delegate_claude.py \
  --objective "Update the target component to handle the empty state." \
  --allow src/components/Target.tsx \
  --forbid package.json \
  --validate "pnpm lint" \
  --validate "pnpm test"
```

The runner writes `.codex/delegations/<job-id>/task.md`, invokes `claude -p`, captures logs, records before/after diff and status snapshots, checks file scope for changes made by this delegation only, and executes `--validate` commands itself after Claude exits.

Default Claude tools are `Read,Edit,Write`. `Bash` is intentionally disabled so Claude does not burn turns on validation commands that the local permission layer may deny. Use `--allow-worker-bash` only for a job that truly needs shell inspection or mechanical commands during the patch.

Default permission mode is `acceptEdits` for normal repos. For local agent/skill infrastructure repos under `.claude`, `.codex`, or `.agents`, the runner defaults to `bypassPermissions` so Claude can edit files such as `SKILL.md` that Claude Code otherwise treats as sensitive. Scope checking still runs after the edit.

The runner uses `--no-session-persistence` by default. Add `--bare` only when Claude Code has API-key or auth-helper credentials available; bare mode does not read OAuth/keychain authentication.

## Claude Worker Constraints

Include these constraints in every task, either through the runner or manually:

- Do not reinterpret the user request.
- Do not broaden scope.
- Do not make architectural decisions.
- Do not ask the user questions.
- Do not edit outside allowed files.
- Do not refactor unrelated code.
- Apply the smallest correct patch that satisfies the objective.
- Write code inside the Code Shape Conventions generated from the local `fundamental-reviewer` principles.
- Do not run validation commands unless the task explicitly enables worker Bash.
- Report only changed files, summary, validation not run by worker, and blockers.

The conventions are writing constraints, not an invitation to perform a broad cleanup. Claude Code should apply them only inside the assigned patch.

## Engineering Retrospective

After a meaningful delegation, produce a short engineering retrospective with two separate parts:

1. Code-reading prediction review: what Codex expected from static code inspection, which execution path or change point it predicted, and where that prediction was right or wrong.
2. Actual behavior sequence review: what really happened after Claude Code ran, what files changed, which validation or runtime sequence confirmed behavior, and what principle explains the final result.

Use `references/engineering-retrospective.md` for the expected structure.

## Resources

- `scripts/delegate_claude.py`: Create a delegation job, run Claude Code CLI, capture logs, save diff, and check scope.
- `scripts/check_scope.py`: Fail when changed files escape the allowed/forbidden file contract.
- `references/job-spec.md`: Job spec schema for `.codex/delegations/<job-id>/task.md`.
- `references/runner-contract.md`: Runner behavior, CLI assumptions, exit codes, and failure handling.
- `references/code-shape-conventions.md`: Condensed code-writing conventions derived from `fundamental-reviewer`.
- `references/engineering-retrospective.md`: Retrospective format for prediction-versus-actual analysis.
- `assets/worker-system-prompt.md`: Minimal Claude worker prompt that strips collaborator behavior.

## Safety Notes

Prefer non-interactive Claude Code execution. If the `claude` binary is missing, authenticated incorrectly, or blocked by network permissions, stop and report the blocker instead of faking delegation. Do not leave background Claude jobs running at the end of the turn.
