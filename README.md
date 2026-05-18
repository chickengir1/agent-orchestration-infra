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
```

`codex/skills`에는 `~/.agents/skills`에서 온 일반 스킬과 `~/.codex/skills`에서 온 Codex 전역 스킬이 함께 보관됩니다. 복원할 때는 스킬의 실행 위치에 맞게 복사합니다. `claude-code-delegate`는 일반 `.agents/skills` 스킬이 아니라 Codex 전역 스킬로 사용하는 것을 전제로 합니다.

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

## 로컬 인프라 자동 동기화

`scripts/sync-local-infra.py`는 로컬 Claude Code/Codex 인프라를 이 저장소 구조로 동기화합니다.

동기화 대상은 고정 allowlist가 아니라 절대 경로 기준 파일 시스템 발견으로 정합니다. 새 에이전트 파일이나 스킬 디렉터리를 아래 로컬 경로에 추가하면 다음 sync 때 자동으로 레포에 반영됩니다. 제외할 대상만 `scripts/sync-local-infra.py`의 `EXCLUDED_*`에 추가합니다.

- `~/.claude/agents`
- `~/.claude/skills`
- `~/.agents/skills`
- `~/.codex/agents`
- `~/.codex/skills`

발견 규칙:

- Claude Code agents: `~/.claude/agents/*.md`
- Claude Code skills: `~/.claude/skills/*` 중 `SKILL.md` 또는 `skill.md`가 있는 디렉터리
- Codex agents: `~/.codex/agents/*.toml`
- Codex skills: `~/.agents/skills/*` 및 `~/.codex/skills/*` 중 `SKILL.md` 또는 `skill.md`가 있는 디렉터리

제외 대상:

- 세션 로그
- 프로젝트 메모리
- 캐시
- 텔레메트리
- 백업
- 인증 파일
- `.auth`
- `.system`
- `.venv`
- `.git`
- `__pycache__`
- `.DS_Store`

수동 실행:

```bash
python3 scripts/sync-local-infra.py --push
```

macOS launchd 자동화 설치:

```bash
mkdir -p ~/Library/LaunchAgents
cp automation/com.chickengir1.agent-orchestration-infra-sync.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.chickengir1.agent-orchestration-infra-sync.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.chickengir1.agent-orchestration-infra-sync.plist
```

자동화는 10분마다 실행됩니다. diff가 없으면 커밋하지 않습니다. diff가 있으면 `Sync local agent orchestration infra (...)` 메시지로 커밋하고 push합니다.

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
