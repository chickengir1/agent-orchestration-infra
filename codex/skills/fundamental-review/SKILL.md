---
name: fundamental-review
description: Invoke the `fundamental-reviewer` custom agent to audit a file, directory, diff, or PR against the twelve code-shape fundamentals. Use for 펀더멘탈 리뷰, code-shape audit, guard clause / happy path / funnel order inspection, and principle coverage reports.
---

# Fundamental Review

This skill is an invoker. The actual audit belongs to the `fundamental-reviewer` custom agent.

## Identity

`fundamental-review` does not judge, prioritize, or fix code. It:

1. identifies the target
2. invokes `fundamental-reviewer`
3. returns the agent's principle coverage report
4. leaves severity, trade-off decisions, and fixes to the main Codex session

## Workflow

1. Identify the target: file path, directory path, diff, branch, or PR.
2. If the target is ambiguous, ask for the target before invoking the agent.
3. Read only enough local context to invoke accurately:
   - current repo/root
   - user-provided scope constraints
   - relevant `AGENTS.md` if it affects review scope
4. Invoke the `fundamental-reviewer` custom agent with this intent:

```text
Audit {target} against the twelve code-shape fundamentals.
Output every principle section in order, including clean sections.
For each violation, cite file:line, quote a small snippet, explain why the shape violates the principle, and give one-line direction toward the canonical shape.
Do not assign severity.
Do not prioritize.
Do not modify code.
Do not perform behavior debugging except as a cross-review note.
```

5. Return the agent result. Do not filter, re-rank, or silently drop findings.
6. If the user asks to fix findings, treat that as a separate implementation task after the report.

## Output Rules

- Preserve the `fundamental-reviewer` section order.
- Keep clean sections unless the user explicitly asks for a compact summary.
- Do not turn the report into a `logic-reviewer` review.
- Do not add severity labels in the skill layer.
- If the agent result contains uncertain cases, preserve the uncertainty.

## Relationship To Other Reviewers

- `fundamental-reviewer`: owns the 12-principle code-shape audit.
- `logic-reviewer`: owns behavior correctness, edge cases, repeated execution, lifecycle, and concrete rewrite strategy.
- `type-reviewer`: owns type safety, validation, trust boundaries, and type design leverage.
- `structure-reviewer`: owns service/store/component/utility boundaries and system shape.
