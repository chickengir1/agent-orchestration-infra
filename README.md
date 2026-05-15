# Agent Orchestration Infra

Reusable local agent infrastructure for Claude Code and Codex.

This repository stores only portable agent and skill definitions. It intentionally excludes session logs, memory, cache, telemetry, backups, auth files, local settings, and project-specific runtime state.

## Layout

```text
.
├── claude-code/
│   ├── agents/   # Claude Code subagent definitions
│   └── skills/   # Claude Code skills and bundled scripts
└── codex/
    ├── agents/   # Codex custom agent definitions
    └── skills/   # Codex skills and bundled resources
```

## Claude Code

Copy Claude Code agents and skills into the local Claude config directory:

```bash
cp -R claude-code/agents/* ~/.claude/agents/
cp -R claude-code/skills/* ~/.claude/skills/
```

`claude-code/skills/test-matrix` keeps its generator inside the skill:

```text
claude-code/skills/test-matrix/
├── skill.md
└── scripts/
    └── generate.py
```

This avoids depending on a separate `~/.claude/tools/test-matrix` directory.

## Codex

Copy Codex custom agents and skills into the local Codex/Agents config directories:

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

The `claude-code-delegate` skill belongs under `~/.codex/skills` if it should be discovered as a Codex skill:

```bash
cp -R codex/skills/claude-code-delegate ~/.codex/skills/
```

## Included Infrastructure

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
