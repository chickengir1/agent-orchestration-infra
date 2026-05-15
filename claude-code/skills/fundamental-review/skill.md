# Fundamental Review

Scan the target against the 12 code fundamentals. The actual scanning and reporting runs inside the `fundamental-reviewer` sub-agent. This skill is a thin invoker — it does not judge, prioritize, or modify code.

## Trigger

`/fundamental-review` or "펀더멘탈 검사" requests.

## Arguments

A file path, directory path, or PR number.

Examples:
- `/fundamental-review apps/libs-app/src/app/pages/settings-board-v2/`
- `/fundamental-review board.store.ts`
- `/fundamental-review #1189`

## Instructions

Invoke the `fundamental-reviewer` sub-agent via the Agent tool.

- `subagent_type`: `fundamental-reviewer`
- `prompt`: `Scan ${target} against the 12 fundamentals. Report every violation with file:line, cause, and a one-line direction. Include all 11 principle sections even when clean. Do not emit severity or fix instructions — those belong to the main agent.`

Pass the sub-agent's output back to the user unchanged. The main agent decides which violations matter, what severity to assign, and whether to patch — the skill layer does not interpret.

## Rules

- The skill is a call interface. All logic lives in the sub-agent.
- Do not filter, re-rank, or summarize the sub-agent's output.
- Do not propose fixes as part of skill invocation. If the user wants fixes, they ask the main agent separately.
- If the target is ambiguous (no path given, no PR number), ask the user before invoking.
