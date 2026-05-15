# Code Shape Conventions

These conventions are derived from the local `fundamental-reviewer` principles. Use them as patch-local writing constraints for Claude Code delegation.

Do not treat these conventions as permission for broad cleanup. Apply them only where the assigned patch writes or reshapes code.

## Conventions

1. Guard clauses: reject invalid, empty, unauthorized, unsupported, or irrelevant cases early.
2. Flat happy path: handle exceptional paths first, then let normal execution read straight down.
3. Funnel order: narrow first, validate second, decide third, transform fourth, then return or commit.
4. Phase separation: avoid mixing validation, transformation, mutation, effects, and response construction in one block.
5. Named decisions: name multi-clause domain rules, permission checks, and cross-field conditions.
6. Named semantic values: name meaningful derived values, normalized inputs, keys, and filtered collections.
7. Shallow control flow: avoid nested ternaries, deep branches, and multi-level callback logic.
8. Explicit side effects: make network, storage, logging, analytics, DOM, global-state, event, or cache effects visible.
9. Consistent return shapes: preserve the local result convention for validators, parsers, hooks, actions, and services.
10. One responsibility per unit: avoid combining orchestration, calculation, rendering, persistence, and policy unless the local module already requires it.
11. Local decision context: keep decision evidence near the decision, or name the decision at the call site.
12. Invalid states hard to represent: validate boundaries, narrow before use, and prefer explicit variants or domain-specific shapes.

## Worker Rule

If a convention conflicts with the surrounding codebase pattern, preserve the surrounding pattern and keep the patch minimal. Codex will handle broader cleanup separately.
