# Claude Code Delegation Task

## Objective
Rework migration-runtime-check from scenario actions to explicit user flows. No legacy compatibility is required. Replace user-facing schema/docs/report/output naming from scenarios[].actions to scenarios[].flows. Each flow has id, kind=safe-ui-flow, description, intent, optional expectedObservables, snapshotAfterEachStep, and click-only steps with selector and optional description. Runtime output should be pages/<scenarioId>/flows/<flowId>/step-N/ with step.json, capture.json, page.png when a snapshot is saved. Preserve the existing safe click guards and statuses, but rename action result concepts to flow/step result concepts. Capture console/pageerror/requestfailed deltas that occur during each flow step and include them in the step capture so compare can report runtime differences caused by user-flow steps. Keep navigation-detected and unsafe-selector behavior. Fix unsafe selector detection so generated Angular attribute selectors such as [_ngcontent-xxx] and [_nghost-xxx] are rejected. Update compare/report to show User Flows, not UI Changes After Actions, and include flow step noise candidates when knownUnstable filters step diffs. Update SKILL.md to state the required sequence: collect route structure once, create strict context/check-plan metadata, collect runtime A, collect runtime B, then report only B-vs-A user-visible view/runtime/flow differences. Update tests and fixtures accordingly; current tests should remain equivalent under flow terminology and add coverage for step runtime deltas and _ngcontent unsafe selector rejection.

## Authority
Codex owns intent, scope, architecture, review, and final integration.
Claude Code owns only the assigned patch.

## Allowed Files
- SKILL.md
- check-plan.schema.json
- capture.py
- compare.py
- plan_helper.py
- tests/test_compare_synthetic.py
- tests/fixtures/sample-check-plan.json
- tests/fixtures/compare-basic/A/page-1/capture.json

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

## Validation
- python3 tests/test_compare_synthetic.py

## Report Format
Report only:
- changed files
- what changed
- validation run
- blockers, if any
