---
name: trace-flow
description: Trace UI state and render behavior from a specific frontend interaction, event, store action, fetch result, or component entry point. Use for `/trace-flow`, UI state forensics, render condition debugging, state leak checks, dead UI state checks, stale async/race checks, and service/store/component boundary tracing.
---

# Trace Flow

Trace how a frontend interaction or data arrival changes UI state and rendering. Keep it bounded to the requested user-visible behavior. This is not an API spec tool and not a full app call graph audit.

## Identity

Trace Flow is UI state/render forensics.

Use it to answer:

- When the user does this, which service/store/component path runs?
- Which state fields are written, read, reset, or leaked?
- Which branch decides whether UI appears, disappears, disables, or errors?
- Which render condition or derived VM value controls the visible result?
- Can stale async results, duplicate triggers, or missing reset leave the UI wrong?
- Is the component using service/store boundaries correctly?

## Workflow

1. Identify one UI entry point and target behavior:
   - click/input/submit event
   - component method
   - store action
   - fetch success/error path
   - route/init path
   - visible symptom, such as modal stuck open or button disabled
2. Read project guidance and stack files: `AGENTS.md`, `package.json`, framework config, and relevant local conventions.
3. Build a bounded interaction chain:
   - component event or lifecycle entry
   - service/store calls it triggers
   - async/fetch result path when relevant
   - VM/selector/derived state builders
   - template/render condition that produces the visible UI
   - stop expanding when code is unrelated to the target behavior
4. Build the UI state map:
   - local component fields, refs, signals, subjects, stores, selectors, derived VM values
   - every write point and read point relevant to the target behavior
   - reset conditions and cancellation/cleanup points
5. Build the render/branch map:
   - `if`, `switch`, guards, early returns, ternaries, async success/error/finally, template conditions
   - quote the condition expression
   - document visible true/false outcomes
6. Verify consumers and triggers:
   - template bindings, inputs/outputs, subscriptions, effects, selectors, event emitters
   - repeated trigger paths such as double submit, route reuse, refresh, remount, retry
7. Check UI regression risks:
   - stale async result overwrites newer state
   - missing reset leaves disabled/loading/error/dirty state stuck
   - dead state where no future event can recover
   - infinite loop or re-trigger path
   - component duplicates service/store domain logic
   - render condition disagrees with source state or VM shape

## Optional Subagents

Use Codex subagents only when the user explicitly asks for agents, teams, or parallel review. Suggested split:

- explorer 1: interaction chain
- explorer 2: state writes/reads/resets
- explorer 3: render consumers and regression risks

If subagents are not explicitly authorized, perform the same steps locally.

## Output

1. Scope and confidence: entry point, target visible behavior, searched boundaries, unsearched areas.
2. Interaction flow: `event -> service/store -> async/result -> state/VM -> render` or the closest actual shape.
3. State map: variable, owner, write points, read points, reset/cleanup condition.
4. Render/branch table: location, condition, true/case visible result, false/default visible result.
5. Trigger/consumer table: trigger or consumer, dependency, expected value range.
6. Regression verdict: stale async, dead state, missing reset, infinite loop, render mismatch, boundary leak.

## Rules

- Quote file and line evidence for state, branch, and render claims.
- Label inferred behavior as inference, not fact.
- Do not trace backend endpoint internals here; use `trace-api` for API consumption contracts.
- For generic machines, stores, hooks, or components, inspect consumer-specific config.
- Do not treat "not found in first search" as proof. Search by symbol, template binding, selector, output event, route, and import path when needed.
- If an important path is unverified, mark that part of the verdict as unverified instead of failing the whole trace.
- Do not expand into a full application audit unless the user asks for one.
