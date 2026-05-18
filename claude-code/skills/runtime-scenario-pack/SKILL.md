---
name: runtime-scenario-pack
description: Build reusable dev-baseline runtime E2E scenario packs for web app branch parity testing, then project those packs into repeatable A(dev)/B(candidate) runtime comparison runs. Use when the user wants durable runtime scenario assets, branch-by-branch migration/feature parity checks, or model-based page/action/flow construction rather than one-off capture.
---

# runtime-scenario-pack

## Identity

This skill is not a one-off migration checker.

It builds a reusable **runtime scenario pack** from the `dev` branch and uses that pack as the SSOT for repeated branch parity runs.

```text
dev branch = oracle baseline
runtime-scenario-pack.json = reusable SSOT
check-plan.json = run-specific executable projection
run artifacts = disposable evidence
report.md = candidate-specific diff
```

## Core Rule

Never create executable flows directly from user prose.

User prose is a weighting signal for value and priority. Executable flows are created only by promotion from evidence-backed page/action candidates.

```text
route graph
+ static action graph
+ dev runtime state-flow graph
+ state equivalence index
+ context/domain metadata
-> scenario-action candidates
-> promotion gate
-> promoted flows
```

## Functional Architecture

Code must be written as a functional core with an imperative shell.

Pure core:

- parse/normalize artifact data
- construct route/action/scenario graphs
- join static actions to runtime surfaces
- classify risk/value/effect
- apply promotion gates
- project scenario pack to check-plan
- compute diff/report models

Imperative shell:

- filesystem read/write
- Playwright capture
- subprocess `rg`
- CLI argument parsing

Forbidden shape:

```text
one function that prompts, scans, writes files, captures browser state, and compares results
```

Required shape:

```text
input artifact -> pure function -> output artifact
```

## Artifact Graph

All repo-local outputs live under:

```text
<repo-root>/.claude/runtime-scenario-pack/
```

Build artifacts:

```text
build/<pack-id>/
  route-graph.json
  static-action-graph.json
  runtime-state-graph.json
  state-equivalence-index.json
  page-scenarios.json
  dev-page-capture/
  runtime-action-surface.json
  scenario-action-candidates.json
  promotion-decisions.json
  pack-build-report.md
```

Frozen reusable asset:

```text
packs/<app>.runtime-scenario-pack.json
```

Run artifacts:

```text
runs/run-<n>/
  check-plan.json
  dev/
  <candidate-branch>/
  diff.json
  report.md
```

## Mathematical Model

```text
R = route graph
Gdev = dev runtime state-flow graph
Q = state equivalence / fragment signature index
C = contexts/auth/domain samples
A = static user actions extracted from codebase
V = runtime visible action surface from dev capture
S = page scenarios, subset of Gdev × C
M = scenario-action candidate mapping, subset of S × A
F = promoted flows, subset of M
D = promotion decisions over M
Pack = (R, Gdev, Q, C, A, V, S, M, D, policy, provenance)
```

Promotion:

```text
promote(s, a) iff
  source_evidence(a)
  selector_provenance(a)
  state_reachable_on_dev(s)
  route_or_component_join(s, a)
  runtime_selector_match(s, a)
  state_delta_observed_or_expected(s, a)
  risk(a) = safe-readonly
  value(a) ∈ {high, medium}
  effect(a) ∈ allowed_same_page_effects
  not mutating(a)
  not duplicate_coverage(a, F)
```

Allowed same-page effects:

- `opens-overlay`
- `opens-dialog`
- `toggles-tab`
- `expands-section`
- `reveals-hidden-content`
- `changes-action-surface`
- `changes-component-surface`
- `read-only-pagination`

Navigation actions are not `safe-ui-flow`; keep them as `navigation-evidence` unless a future explicit navigation-flow contract is added.

Promotion decisions are the only flow SSOT inside a frozen pack. `promotedFlows`
must not exist as a second stored source of truth; runnable flows are derived
from `promotionDecisions[decision=promote-to-flow].flow` during run projection.

## Build Mode

Build mode creates or updates a reusable scenario pack from `dev`.

```text
B0 Runtime Ready
B1 Build Unit Selected
B2 Dev Baseline Bound
B3 Auth/Context Bound
B4 Domain Metadata Bound
B5 Route Graph Extracted
B6 Static Action Graph Extracted
B7 Dev Runtime State Graph Captured
B8 State Equivalence Index Built
B9 Scenario State Candidates Built
B10 Runtime Action Surface Extracted
B11 Scenario-Action Candidate Matrix Built
B12 Promotion Gate Applied
B13 Human Review
B14 Scenario Pack Frozen
```

Human review happens once, at `B13`, before freezing the pack.

Human review checks:

- page scenarios
- dev runtime states
- promoted flows
- rejected high-value actions
- uncertain actions
- known unstable noise
- context metadata

## Run Mode

Run mode does not create new scenarios. It executes a frozen pack against a branch pair.

```text
R0 Scenario Pack Selected
R1 Candidate Branch Selected
R2 Check Plan Projected
R3 Dev Captured
R4 Candidate Captured
R5 Targeted Flow Captured
R6 Scenario Matrix Reported
```

## Contracts

Read `contract.py` before changing schemas or validators.

Minimum validators:

- `validate_route_graph`
- `validate_static_action_graph`
- `validate_runtime_state_graph`
- `validate_state_equivalence_index`
- `validate_runtime_surface`
- `validate_scenario_action_candidates`
- `validate_promotion_decisions`
- `validate_scenario_pack`
- `validate_check_plan`

Validation must reject:

- source-less executable actions
- selector-less executable actions
- generated/framework selectors
- unresolved route parameters in concrete paths
- page scenarios that do not reference a dev runtime state
- scenario-action candidates without route/component join evidence
- scenario-action candidates without dev runtime selector match
- scenario-action candidates without observed or expected state delta
- flow promotion without runtime visibility
- flow promotion with unsafe risk
- flow promotion with low/none/unknown value
- flow selector that differs from the promoted action selector
- `promotedFlows` as a second source of truth
- run check-plan used as reusable SSOT

## LLM Role

LLM may:

- interpret source evidence
- map user/domain intent to value and priority
- explain rejected/uncertain actions
- summarize reports and investigation candidates

LLM must not:

- invent selectors
- invent source locations
- promote mutating actions
- treat user prose as an executable plan
- skip artifact validation

## Reuse Policy

The expensive work is scenario-pack construction. After a pack is frozen, repeated branch checks should only project and execute the pack.

```text
scenario pack = stable asset
check-plan = generated per run
report = generated per run
```
