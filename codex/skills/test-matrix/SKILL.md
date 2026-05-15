---
name: test-matrix
description: Generate scenario-based pytest test matrices and verify coverage. Use for `/test-matrix`, Given/When/Then scenario design, variation axes, pytest parametrization scaffolds, logic-porting tests, and matrix coverage checks.
---

# Test Matrix

Generate pytest matrices for logic verification. API call and payload verification are separate unless the user provides API samples or a Postman MCP is available.

Bundled CLI:

```text
~/.agents/skills/test-matrix/scripts/generate.py
```

## Workflow

1. Identify the feature and related source files. If missing, ask for the feature entry point.
2. Trace the user flow before writing tests:
   - component or entry point
   - service/store/API call
   - transformations
   - branches and validation
   - error handling
3. Define scenarios in Given/When/Then format:
   - each scenario maps to a real user journey
   - axes represent roles, data state, permissions, size, nullability, timing, or error cases
   - mark expected failures with `expect_fail: true`
4. Present scenario definitions before generating files when the matrix affects a real repo.
5. Port the When-step logic into Python only as far as needed to verify deterministic business logic. Do not pretend UI rendering or network behavior is covered by this matrix.
6. Use realistic mock data. If Postman MCP or API samples are unavailable, ask for response examples or derive the minimum shape from source types and mark assumptions.
7. Generate the scaffold:

```bash
python3 ~/.agents/skills/test-matrix/scripts/generate.py init config.json
```

or:

```bash
cat config.json | python3 ~/.agents/skills/test-matrix/scripts/generate.py init -
```

8. Fill generated `mocks.py` and `logic.py`; do not leave TODOs in final work.
9. Run tests from the target repo, then check matrix coverage:

```bash
python3 ~/.agents/skills/test-matrix/scripts/generate.py check path/to/generated/tests
```

## Config Shape

```json
{
  "name": "feature-name",
  "output_dir": "tests/feature_name",
  "scenarios": [
    {
      "id": "scenario_id",
      "desc": "user does X",
      "given": "preconditions",
      "when": "action chain",
      "then": "expected outcome",
      "axes": [
        {
          "name": "axis_name",
          "items": [
            {"id": "normal", "desc": "normal case"},
            {"id": "error", "desc": "error case", "expect_fail": true}
          ]
        }
      ]
    }
  ]
}
```

## Rules

- Scenario definition is the most important step.
- Do not generate tests before tracing the exercised code path.
- Keep generated tests in the target repo, not under `~/.codex`.
- Treat this as logic coverage, not end-to-end coverage.
- The CLI uses only Python standard library.
