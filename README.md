# Agent Orchestration Infra

Claude Code와 Codex에서 재사용할 에이전트/스킬 인프라 저장소입니다.

이 레포에는 이식 가능한 에이전트 정의와 스킬 정의만 올립니다. 세션 로그, 프로젝트 메모리, 캐시, 텔레메트리, 백업, 인증 파일, 로컬 설정, 프로젝트별 런타임 상태는 포함하지 않습니다.

## 구조

```text
.
├── claude-code/
│   ├── agents/   # Claude Code 서브에이전트 정의
│   └── skills/   # Claude Code 스킬과 스킬 내부 스크립트
└── codex/
    ├── agents/   # Codex 커스텀 에이전트 정의
    └── skills/   # Codex 스킬과 번들 리소스
```

## Claude Code

Claude Code 에이전트와 스킬은 로컬 Claude 설정 디렉터리로 복사해서 사용합니다.

```bash
cp -R claude-code/agents/* ~/.claude/agents/
cp -R claude-code/skills/* ~/.claude/skills/
```

`claude-code/skills/test-matrix`는 generator를 스킬 내부에 포함합니다.

```text
claude-code/skills/test-matrix/
├── skill.md
└── scripts/
    └── generate.py
```

따라서 별도의 `~/.claude/tools/test-matrix` 디렉터리에 의존하지 않습니다.

## Codex

Codex 커스텀 에이전트와 스킬은 로컬 Codex/Agents 설정 디렉터리로 복사해서 사용합니다.

```bash
cp codex/agents/*.toml ~/.codex/agents/
cp -R codex/skills/edit-pr ~/.agents/skills/
cp -R codex/skills/fundamental-review ~/.agents/skills/
cp -R codex/skills/handoff ~/.agents/skills/
cp -R codex/skills/reply-review ~/.agents/skills/
cp -R codex/skills/review-team ~/.agents/skills/
cp -R codex/skills/test-matrix ~/.agents/skills/
cp -R codex/skills/trace-api ~/.agents/skills/
cp -R codex/skills/trace-flow ~/.agents/skills/
```

`claude-code-delegate`는 일반 `.agents/skills` 스킬이 아니라 Codex 전역 스킬로 사용하는 것을 전제로 합니다.

```bash
cp -R codex/skills/claude-code-delegate ~/.codex/skills/
```

## 포함된 인프라

Claude Code:

- `fundamental-reviewer`
- `logic-reviewer`
- `structure-reviewer`
- `task-planner`
- `type-reviewer`
- `edit-pr`
- `fundamental-review`
- `handoff`
- `reply-review`
- `test-matrix`
- `trace-api`
- `trace-flow`

Codex:

- `fundamental-reviewer`
- `logic-reviewer`
- `structure-reviewer`
- `type-reviewer`
- `claude-code-delegate`
- `edit-pr`
- `fundamental-review`
- `handoff`
- `reply-review`
- `review-team`
- `test-matrix`
- `trace-api`
- `trace-flow`
