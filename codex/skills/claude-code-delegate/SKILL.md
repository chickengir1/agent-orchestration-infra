---
name: prompt-engineering-harness
description: Build, critique, compress, and test prompts with a lightweight harness: define the task contract, isolate context, create eval cases, compare variants, and produce a token-efficient prompt artifact.
---

# Prompt Engineering Harness

Use this skill when the user wants to create, rewrite, reduce, evaluate, or systematize prompts, instructions, agent workflows, or skill text. The default goal is a smaller prompt that preserves behavior and has explicit tests.

Do not use this skill to run delegated Claude workers. The old Claude delegate workflow is preserved only as a legacy reference in `references/legacy-claude-code-delegate.md`; read it only when the user specifically asks about the old delegate runtime.

## Operating Principle

Treat prompts like code:

- define the behavioral contract before writing,
- keep only context that changes model behavior,
- separate stable policy from task-local data,
- test the prompt against concrete cases,
- prefer short rubrics and schemas over long prose,
- keep examples only when they cover real failure modes.

For reasoning models, avoid chain-of-thought instructions. Use direct goals, constraints, delimiters, and success criteria. Ask for concise rationale or verification evidence only when the output needs auditability.

## Harness Flow

1. Scope
   - Name the target prompt or workflow.
   - State what will not be optimized.
   - Identify the target model or agent surface if known.

2. Contract
   - Define inputs, outputs, allowed tools, forbidden actions, and success criteria.
   - Mark each requirement as `must`, `should`, or `nice`.
   - Remove requirements that are only commentary.

3. Context Budget
   - Split context into `always`, `conditional`, and `external/reference`.
   - Move large examples, API notes, or legacy procedures out of the main prompt unless they are needed every run.
   - Preserve exact wording only for safety rules, schemas, or externally imposed constraints.

4. Prompt Draft
   - Write the smallest prompt that satisfies the contract.
   - Use headings, bullets, and explicit delimiters.
   - Put output format near the end.
   - Keep tool-use rules concrete and observable.

5. Eval Cases
   - Create 3-7 cases: happy path, ambiguity, missing data, adversarial instruction, over-scope request, and one realistic regression.
   - For each case, define expected behavior and failure signals.
   - If the prompt is for code work, include verification commands or file inspections that the orchestrator will run.
   - Keep eval cases as chat output by default. Create files only when the user explicitly asks to save, scaffold, or run a file-backed harness.

6. Variant Review
   - Compare the current prompt and revised prompt against the eval cases.
   - Track behavior changes, token savings, and risks.
   - Keep the old prompt available until the revised prompt passes the contract.

7. Output
   - Provide the revised prompt.
   - Provide the eval matrix.
   - List removed or externalized context.
   - List remaining assumptions and follow-up checkpoints.
   - Do not write prompt, report, or eval artifacts to disk unless the user requests persistent files.

## Token Triage

Cut in this order:

1. repeated rules already supplied by higher-priority instructions,
2. explanatory prose that does not change behavior,
3. examples that duplicate the same pattern,
4. command walkthroughs that can live in scripts or references,
5. historical rationale,
6. broad "be careful" language without an observable check.

Keep:

- safety boundaries,
- file ownership and rollback rules,
- exact output schemas,
- acceptance criteria,
- short examples that cover distinct edge cases,
- commands that are fragile or easy to misuse.

## Prompt Artifact Template

```markdown
# <Prompt Name>

## Role
<One sentence.>

## Task
<What to do.>

## Inputs
- `<input_name>`: <meaning>

## Rules
- <Must-follow behavior.>

## Context Policy
- Always include: <small stable context>
- Include only when relevant: <conditional context>
- Keep external: <large references>

## Output
<Format, schema, or sections.>

## Stop Conditions
- <When to ask, refuse, or stop.>
```

## Eval Matrix Template

```markdown
| Case | Input | Expected behavior | Failure signal |
| --- | --- | --- | --- |
| Happy path |  |  |  |
| Missing data |  |  |  |
| Ambiguous request |  |  |  |
| Over-scope request |  |  |  |
| Regression |  |  |  |
```

## When Updating A Skill

- Keep `SKILL.md` under 200 lines when possible.
- Move long procedures to `references/` and mention exactly when to read them.
- Update `agents/openai.yaml` when the skill name, purpose, or default prompt changes.
- Verify frontmatter has `name` and `description`.
- Do not keep runtime logs, historical plans, or generated artifacts in the default prompt path.
