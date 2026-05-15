# Claude Code Delegation Task

## Objective
Update migration-runtime-check for two runtime-test issues. First, SKILL.md must require user-flow candidate handling before any capture: after discover/check-plan draft, if the user requested flows or if safe UI interactions are needed, Claude must add explicit scenarios[].flows[] entries or explicitly record 'no flows selected'; A capture must not silently proceed with flows=0 when flow testing was requested. Second, capture.py must avoid capturing before client-side redirect/route settling: add a small route-stability wait after goto/networkidle fallback and before evaluate/screenshot. The wait should observe page.url changes, wait for a stable URL for a short window, and avoid treating transient about:blank as ready until timeout. Keep this deterministic and bounded. Update tests with a unit-level helper test if practical. Preserve context-scoped output layout, safe-ui-flow model, and existing tests.

## Authority
Codex owns intent, scope, architecture, review, and final integration.
Claude Code owns only the assigned patch.

## Allowed Files
- SKILL.md
- capture.py
- tests/test_compare_synthetic.py

## Forbidden Files
- .auth
- .venv
- .git

## Constraints
- Do not reinterpret the task.
- Do not broaden scope.
- Do not make architecture decisions.
- Do not ask the user questions.
- Do not edit files outside the allowed scope.
- Do not refactor unrelated code.
- Apply the smallest correct patch that satisfies the objective.

## Code Shape Conventions
Write code within these conventions. Do not perform a broad cleanup pass just to satisfy them.

- Guard clauses: reject invalid, empty, unauthorized, unsupported, or irrelevant cases early.
- Flat happy path: handle exceptional paths first, then let normal execution read straight down.
- Funnel order: narrow first, validate second, decide third, transform fourth, then return or commit.
- Phase separation: avoid mixing validation, transformation, mutation, effects, and response construction in one block.
- Named decisions: name multi-clause domain rules or permission checks before using them.
- Named semantic values: name meaningful derived values before using them in conditions, payloads, or returns.
- Shallow control flow: avoid nested ternaries, deep branches, and multi-level callback logic.
- Explicit side effects: make network, storage, logging, analytics, DOM, global-state, event, or cache effects visible.
- Consistent return shapes: preserve the local result convention for validators, parsers, hooks, actions, and services.
- One responsibility per unit: do not combine orchestration, calculation, rendering, persistence, and policy unless the file already requires it.
- Local decision context: keep decision evidence near the decision, or name the decision at the call site.
- Invalid states hard to represent: validate boundaries, narrow before use, and prefer explicit variants or domain-specific shapes.

## Runner Validation
- /Users/leegangho/.claude/skills/migration-runtime-check/.venv/bin/python3 tests/test_compare_synthetic.py

Claude Code must not run these commands unless Codex explicitly enabled worker Bash for this job.
The delegation runner executes them after Claude Code exits and records the result.

## Report Format
Report only:
- changed files
- what changed
- validation not run by worker; runner will execute validation
- blockers, if any
