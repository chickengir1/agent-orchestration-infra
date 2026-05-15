---
name: handoff
description: Create a design-oriented handoff document for the next Codex session or agent. Use when the user asks for `/handoff`, handoff, next-agent notes, continuation context, renewal handoff, implementation handoff, or a document that preserves design boundaries, decisions, invariants, and what must not be reverted.
---

# Handoff

Create a handoff for the next worker, not a chat summary. The document must let a fresh agent recover the design boundary, why decisions were made, what must not be casually reverted, and where future work should continue.

## Core Intent

The handoff is for restoring engineering judgment after context loss. Prioritize:

- what decision would break behavior if reverted
- what contracts must remain stable
- what is intentionally out of scope
- which layer owns which responsibility
- what policies/invariants the implementation relies on
- which files encode the important boundaries
- what was not verified

Do not write a generic progress summary unless the work was trivial.

## Workflow

1. Determine the feature/workstream name from the branch, changed files, user wording, or current task.
2. Collect baseline metadata:
   - current date
   - branch
   - HEAD short hash and subject
   - working tree status
   - whether tests/builds were run
3. Inspect relevant files enough to recover architecture and policy decisions. Do not read or modify files outside the user-approved scope when the user gave constraints.
4. If an existing handoff exists, read it and update it. Preserve useful decisions; remove stale claims.
5. Write the document in the current working directory unless the user specified a path. Prefer `HANDOFF.md`, or a feature-specific name when the user already uses one.
6. After writing, report the path and any verification not performed.

## Required Shape

Use this structure. Omit sections only when truly irrelevant.

```markdown
# {Feature / Workstream} Handoff

작성일: YYYY-MM-DD
기준 브랜치: `{branch}`
기준 HEAD: `{short-hash subject}`
상태: {one-sentence current state}

이 문서는 변경 파일 목록이 아니라 다음 작업자가 설계 경계와 판단 근거를 복원하기 위한 handoff다. diff가 크면 “무엇을 만들었나”보다 “어떤 결정을 되돌리면 깨지는가”를 먼저 본다.

## 작업 규칙

- User-specified constraints and scope rules
- Files or categories not to touch
- Commands not run unless requested
- Contracts not to break

## 한 줄 결론

{The feature architectural identity in one sentence.}

## 작업 범위

이번 작업에 포함된 것:

- ...

이번 작업이 아닌 것:

- ...

## 핵심 아키텍처

- `path/to/file`
  - responsibility
  - boundary it owns

핵심 판단:

- decision and reason

## 보존해야 할 계약 / 불변식

- Existing public contracts
- read/write boundaries
- ownership rules
- UI/domain/service/store invariants

## 정책 / 동작 세부사항

### {Policy Area}

- exact behavior
- edge cases
- what not to infer

## API / 데이터 trace

- route or data source
- live/dead parameters when relevant
- serialization details
- fallback/error policy

## 주요 파일

- `path`

## 주요 spec / 검증

- `path`
- Tests/builds run or explicitly not run

## 남은 TODO

- Only actual known TODOs
- If none, say none. Do not invent work.

## 워크트리 메모

- current branch
- current HEAD
- tracked changes
- untracked files
- whether this handoff should be committed
```

## Content Rules

- Write in Korean when the working context is Korean.
- Be specific. A future agent should be able to avoid breaking invariants without rereading the entire diff first.
- Prefer file paths and exact contract names over vague descriptions.
- Separate included from not included to prevent scope creep.
- Separate section visible from user can change it when that distinction matters.
- Record fallback policy and failure semantics when a fetch or side effect is best-effort.
- Mark assumptions explicitly.
- Do not include secrets, tokens, private credentials, or irrelevant chat transcript.
- Do not include every changed file as a flat dump; group files by architectural responsibility.
- Do not claim tests/builds were run unless they were actually run in the current work.
