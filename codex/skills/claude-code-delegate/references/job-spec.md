# Job Spec

`task.md` is the only source of truth Claude Code should follow for a delegated edit.

## Required Sections

### Objective
State one concrete code-editing goal. Do not include broad product background.

### Authority
State that Codex owns intent, scope, architecture, review, and final integration. State that Claude Code owns only the assigned patch.

### Allowed Files
List every file Claude Code may edit. Use repo-relative paths.

### Forbidden Files
List files or path prefixes Claude Code must not edit. Use repo-relative paths.

### Constraints
Include behavioral limits such as no unrelated refactors, no public API changes, no dependency changes, and no user questions.

### Code Shape Conventions
Include the condensed writing conventions from `references/code-shape-conventions.md`. These are patch-local constraints, not broad cleanup permission.

### Runner Validation
List commands the delegation runner will execute after Claude Code exits. Claude Code must not run them unless worker Bash was explicitly enabled for the job.

### Report Format
Require a concise final report:

```text
changed_files:
- path

summary:
- change

validation:
- not run by worker; runner will execute validation

blockers:
- blocker or none
```

## Minimal Example

```md
# Claude Code Delegation Task

## Objective
Update `src/components/Target.tsx` to render the empty state when `items` is empty.

## Authority
Codex owns intent, scope, architecture, review, and final integration.
Claude Code owns only the assigned patch.

## Allowed Files
- src/components/Target.tsx

## Forbidden Files
- package.json
- pnpm-lock.yaml

## Constraints
- Do not modify behavior outside the empty state.
- Do not refactor unrelated rendering logic.
- Do not ask the user questions.

## Code Shape Conventions
- Use guard clauses for invalid or empty states.
- Keep the happy path flat.
- Preserve the local return convention.

## Runner Validation
- pnpm lint

## Report Format
Report changed files, summary, validation, and blockers only.
```
