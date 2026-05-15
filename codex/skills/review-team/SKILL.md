---
name: review-team
description: Orchestrate multi-agent code reviews by invoking logic-reviewer, type-reviewer, and structure-reviewer custom agents, then integrating their findings. Use when the user asks for review-team, 세 리뷰어, multi-agent review, parallel review, broad review, or named reviewer perspectives.
---

# Review Team

`review-team` is an orchestrator. It calls reviewer agents, collects their reports, removes duplicate noise, resolves overlaps, and returns one integrated review to the user.

## Identity

Review Team is a multi-agent review integrator.

Default agent set:

- `logic-reviewer`
- `type-reviewer`
- `structure-reviewer`

Optional agent:

- `fundamental-reviewer` only when the user explicitly asks for fundamentals, code-shape audit, or a broad review that should include principle coverage.

## Workflow

1. Identify the target files, directory, PR, branch, or diff.
2. Read only enough local context to invoke the reviewers accurately:
   - current repo/root
   - user-specified scope constraints
   - relevant `AGENTS.md`
   - stack/config files when they affect review scope
3. Invoke the relevant custom agents:
   - `logic-reviewer`: behavior correctness, executable flow, edge cases, purity, lifecycle, small local rewrites
   - `type-reviewer`: trust boundaries, validation, type safety, security, existing type infrastructure
   - `structure-reviewer`: service/store/component/utility boundaries, module ownership, coupling, reuse
   - `fundamental-reviewer`: fixed-principle code-shape audit, only when explicitly included
4. Let the agents run independently. Do not pre-merge their concerns before they report.
5. Collect all agent outputs.
6. Integrate the results:
   - remove duplicate findings
   - merge overlapping findings when they share the same root cause
   - preserve disagreements or uncertainty as open questions
   - order findings by severity and concrete user/code risk
   - keep each finding grounded in file:line evidence
7. Report the final integrated review to the user.

## Integration Rules

- Do not silently drop agent findings. If a finding is excluded, it must be because it is duplicate, unsupported, out of scope, or only a preference.
- Do not manufacture balance. If only one agent found real issues, report only those.
- Do not let one reviewer overwrite another reviewer's domain. For example, a type issue caused by a structural boundary should mention both.
- If agents disagree, state the conflict and the evidence needed to resolve it.
- If no issues are found, say so and list residual verification gaps.

## Output

Use code-review stance. Findings first.

```markdown
## Findings

### 1. Title

- severity: high | medium | low
- source: logic-reviewer | type-reviewer | structure-reviewer | fundamental-reviewer
- file: `path:line`
- category:
- what I see:
- why it matters:
- suggested direction:

## Open Questions

- unresolved assumptions or conflicts

## Agent Coverage

| agent | status | notes |
|---|---|---|
| logic-reviewer | completed/skipped | ... |
| type-reviewer | completed/skipped | ... |
| structure-reviewer | completed/skipped | ... |
| fundamental-reviewer | completed/skipped | ... |

## Summary

- Total findings:
- High:
- Medium:
- Low:
- Residual risk:
```

## Rules

- Use custom agents registered in `~/.codex/agents/*.toml` when the user explicitly asks for team, multi-agent, parallel review, or named reviewers.
- If the user only asks for a normal review, do not force multi-agent orchestration.
- Default to three reviewers: logic, type, structure.
- Add `fundamental-reviewer` only when requested or when the user asks for broad review including fundamentals.
- Keep the final report concise enough to act on.
- Do not include praise sections.
