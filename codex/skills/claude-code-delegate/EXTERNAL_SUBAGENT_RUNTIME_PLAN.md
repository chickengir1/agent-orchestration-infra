# External Subagent Runtime Plan

## Goal

Turn `claude-code-delegate` from a Claude-specific task dispatcher into an external subagent runtime that feels like Codex native subagents:

- Codex main issues one bounded delegation request.
- Work runs outside the main Codex turn.
- Workers execute in parallel through a backend adapter.
- A supervisor handles status, verification, heartbeat cleanup, and summary writing.
- Codex main reads compact summaries instead of task logs or long status JSON.

The first backend remains Claude Code SDK. The design must allow future backends such as Codex subagents or local script workers without changing the Codex-facing workflow.

## Current State

Current implementation is task-oriented:

- Runtime state lives under `runtime/`.
- Task records live under `runtime/tasks/<task-id>/status.json`.
- Queue items live under `runtime/queue/<task-id>.json`.
- Worker state lives under `runtime/workers/worker-*.json`.
- `start`, `send`, `dispatch`, `status`, `stop`, and `rm` mutate or inspect this runtime.
- `dispatch --manifest` maps manifest task ids to runtime task ids.
- Thread heartbeat automation is required for non-dry-run dispatch and is verified through `~/.codex/automations/<automation-id>/automation.toml`.

Observed bottlenecks before Checkpoint 1:

- `status --include-workers` emits all historical task summaries.
- Codex main repeatedly reasons about heartbeat stale state, task terminal state, artifact verification, and cleanup.
- Smoke/integration tests require many shell commands and large JSON reads.
- There is no first-class `run` object, so Codex main has to reconstruct a checkpoint from task files and manifests.

## Target Architecture

```text
Codex Main
  -> External Subagent Runtime CLI
      -> Run Supervisor
          -> Backend Adapter: claude-code
              -> Claude SDK worker pool
          -> Verifier
          -> Heartbeat Resolver
          -> Summary Writer
```

### Control Plane

Codex main is the control plane. It should only:

- define or approve a run manifest,
- start a run,
- read compact run summaries,
- make product/code decisions that require human-level judgment.

Codex main should not repeatedly parse full task history, worker logs, or raw heartbeat snapshots.

### Data Plane

The runtime is the data plane. It should:

- validate manifests,
- create/enforce task records,
- dispatch work to the selected backend,
- monitor active tasks,
- run verifiers,
- update run state,
- delete thread-scoped heartbeat automation after verified terminal completion,
- emit compact summaries.

## Core Concepts

### Run

A run is the Codex-facing unit of delegation. It groups one or more tasks, their backend, verifier contracts, heartbeat automation id, and summary.

Path:

```text
runtime/runs/<run-id>/
  manifest.json
  state.json
  events.jsonl
  summary.json
  artifacts.json
```

### Task

A task is the backend-facing execution unit. Existing task records under `runtime/tasks/<task-id>/` remain valid.

Tasks belong to a run through:

```json
{
  "run_id": "<run-id>",
  "manifest_id": "<manifest-task-id>"
}
```

### Backend

A backend is an implementation of a common worker interface:

```text
start(workdir, options) -> backend_state
dispatch(task_contract) -> backend_task_id
status(task_id) -> task_state
cancel(task_id) -> task_state
collect_result(task_id) -> result
```

Initial backend:

```text
claude-code
```

Future backends:

```text
codex-subagent
local-script
```

### Activity

Activities are side-effecting operations performed by the runtime:

- `preflight`
- `validate_manifest`
- `create_heartbeat_automation`
- `dispatch_task`
- `poll_task`
- `verify_artifact`
- `run_verify_cmd`
- `delete_heartbeat_automation`
- `write_summary`

The supervisor should record activity events, not ask Codex main to reason through each activity.

## Run State Machine

```text
created
-> validating
-> ready
-> dispatching
-> running
-> verifying
-> verified
-> cleaned
```

Failure states:

```text
failed
stopped
needs-human
```

State rules:

- `created`: run directory exists; manifest copied in.
- `validating`: manifest and task contracts are being checked.
- `ready`: validation passed; no tasks dispatched yet.
- `dispatching`: task queue records are being created.
- `running`: at least one task is `created`, `queued`, or `running`.
- `verifying`: no active tasks remain; verifier is checking artifacts and commands.
- `verified`: all tasks terminal-success and verifier passed.
- `cleaned`: thread heartbeat automation has been deleted and summary is final.
- `failed`: backend or verifier failed.
- `stopped`: explicit stop/cancel.
- `needs-human`: runtime cannot safely decide next action.

## Event Model

Append all transitions to:

```text
runtime/runs/<run-id>/events.jsonl
```

Event shape:

```json
{
  "ts": "2026-05-22T00:00:00Z",
  "run_id": "checkpoint-8",
  "type": "task.done",
  "task_id": "abc",
  "manifest_id": "module-a",
  "detail": {}
}
```

Use event sourcing for reconstruction and debugging, but do not make Codex main read `events.jsonl` by default.

## Summary Contract

Codex main reads this by default:

```json
{
  "run_id": "checkpoint-8",
  "backend": "claude-code",
  "status": "verified",
  "workdir": "/absolute/workdir",
  "tasks": {
    "total": 3,
    "done": 3,
    "failed": 0,
    "active": 0
  },
  "changed_files": [
    "/absolute/path/a.ts"
  ],
  "checks": [
    {
      "name": "artifact-boundary",
      "status": "passed"
    }
  ],
  "heartbeat": {
    "automation_id": null,
    "deleted": true
  },
  "next_action": "ready_for_codex_review"
}
```

Target size: under 1 KB for normal successful runs.

## CLI Target

Keep existing commands during migration. Add run-oriented commands:

```bash
visible_claude.py run init \
  --run-id checkpoint-8 \
  --backend claude-code \
  --manifest /absolute/path/manifest.json

visible_claude.py run start \
  --run-id checkpoint-8 \
  --thread-heartbeat-automation-id "<automation-id>"

visible_claude.py run supervise \
  --run-id checkpoint-8

visible_claude.py run status checkpoint-8

visible_claude.py run summary checkpoint-8

visible_claude.py run cancel checkpoint-8
```

Add compact task status commands:

```bash
visible_claude.py status
visible_claude.py status --active-only
visible_claude.py status --task <task-id>
visible_claude.py status --history --limit 10
```

Default `status` should not emit all historical done tasks.

Add heartbeat resolver:

```bash
visible_claude.py heartbeat resolve \
  --automation-id "<automation-id>"
```

Resolver output:

```json
{
  "decision": "DONT_NOTIFY",
  "reason": "active_tasks_running",
  "run_id": "checkpoint-8"
}
```

or:

```json
{
  "decision": "NOTIFY",
  "run_id": "checkpoint-8",
  "status": "verified",
  "automation_deleted": true,
  "summary_file": "/absolute/path/summary.json"
}
```

## Verification Model

Verification must move out of Codex main where possible.

Verifier inputs:

- manifest task read/write paths,
- task status files,
- expected artifacts,
- `verify_cmd` entries,
- optional changed-file allowlist.

Verifier checks:

- every runtime task reached `done`,
- no task wrote outside declared write paths when detectable,
- expected artifact files exist,
- exact artifact assertions pass when declared,
- `verify_cmd` commands pass,
- no active queue items remain,
- worker daemon state is consistent.

Verifier output goes to:

```text
runtime/runs/<run-id>/artifacts.json
runtime/runs/<run-id>/summary.json
```

## Heartbeat Semantics

Heartbeat automation is for cold/idle wake only. It is not an active-turn interrupt.

Canonical behavior:

1. Heartbeat wakes Codex.
2. Codex calls `visible_claude.py heartbeat resolve --automation-id <id>`.
3. Runtime re-reads direct task/run state.
4. If active tasks exist:
   - return `DONT_NOTIFY`,
   - keep automation.
5. If no active tasks exist:
   - verify run,
   - refresh watcher if heartbeat is stale,
   - delete thread-scoped automation,
   - return compact `NOTIFY` summary.

The heartbeat file is never completion proof. It is only a trigger.

## Backend Adapter: Claude Code

The existing Claude backend should be wrapped, not rewritten first.

Mapping:

- `backend.start` -> existing `start`
- `backend.dispatch` -> existing `create_task` + queue item
- `backend.status` -> task status file
- `backend.collect_result` -> task `status.json` result
- `backend.cancel` -> queue removal / stopped state

Claude backend invariants stay unchanged:

- model `opus`,
- max 3 workers,
- isolated SDK conversation per task,
- tool gating,
- explicit read/write paths,
- no shell/test/git/browser/MCP/plugin/subagents in worker.

## Implementation Checkpoints

### Checkpoint 1: Compact Status

Files:

- `scripts/visible_claude.py`
- `SKILL.md`

Changes:

- Make default `status` compact.
- Add `--history --limit`, `--task`, `--active-only`.
- Add `--all` for all task summaries.
- Preserve `--verbose` for full debug output.
- Include `metrics.status_bytes` in status output.
- Return short CLI errors for missing or invalid manifest files.

Verification:

- default status under 1 KB on current runtime,
- `status --include-workers` under 1 KB on idle runtime,
- `--task <id>` prints one task,
- `--history --limit 3` prints three historical tasks,
- `--active-only` prints only active tasks,
- `--all` and `--verbose` remain available for debugging,
- missing manifest validation fails without traceback.

### Checkpoint 2: Run Storage

Files:

- `scripts/visible_claude.py`
- `SKILL.md`

Changes:

- Add `runtime/runs/<run-id>/` layout.
- Add `run init`.
- Add `run status <run-id>`.
- Add `run summary <run-id>`.
- Copy manifest into run directory.
- Write initial `state.json`, `events.jsonl`, `summary.json`.

Verification:

- `run init` creates deterministic files.
- invalid duplicate run id is rejected unless explicit force flag exists.
- summary is compact.
- `run status` and `run summary` read only run files and do not scan historical task records.

### Checkpoint 3: Run Start

Changes:

- Add `run start`.
- Validate heartbeat automation id.
- Validate manifest.
- Dispatch manifest tasks.
- Record runtime task ids in run state, run manifest, and run summary.
- Reuse the same dispatch helper as direct `dispatch --manifest`.
- Refresh run summary task counts from only that run's referenced task status files.

Verification:

- `/private/tmp` one-task run dispatches successfully.
- missing heartbeat automation id is rejected.
- invalid automation TOML is rejected.
- overlapping write paths fail before dispatch.
- `run summary <run-id>` reports dispatched and active task counts after start.
- after a task reaches `done`, `run summary <run-id>` reports updated done/active counts without scanning historical task records.

### Checkpoint 4: Run Supervise

Changes:

- Add `run supervise`.
- Read only task states referenced by the run manifest.
- Move run through `running -> verifying|failed`.
- Write compact summary.

Verification:

- done task produces verifying summary.
- failed task produces failed summary.
- active task returns running without verbose task dump.

### Checkpoint 5: Verifier

Changes:

- Support exact artifact assertions in manifest.
- Run `verify_cmd`.
- Check write path boundaries from recorded task metadata.

Verification:

- exact artifact pass/fail tests.
- command pass/fail tests.
- write path mismatch test when detectable.

### Checkpoint 6: Heartbeat Resolve

Changes:

- Add `heartbeat resolve --automation-id`.
- It finds the associated run.
- It returns `DONT_NOTIFY` for active work.
- It verifies and deletes automation for completed work.

Verification:

- active run keeps automation and returns `DONT_NOTIFY`.
- done run verifies, deletes automation, returns `NOTIFY`.
- stale heartbeat is refreshed but not trusted.

### Checkpoint 7: Backend Interface Extraction

Changes:

- Introduce a small backend adapter layer.
- Move Claude-specific task dispatch/status into `ClaudeCodeBackend`.
- Keep CLI behavior stable.

Verification:

- existing Claude smoke tests still pass.
- fake backend can complete a run without Claude SDK.

### Checkpoint 8: Native-Like Subagent UX

Changes:

- Add a single high-level command:

```bash
visible_claude.py delegate \
  --backend claude-code \
  --manifest /absolute/path/manifest.json \
  --run-id checkpoint-8 \
  --thread-heartbeat-automation-id "<automation-id>"
```

This should call `run init`, `run start`, and write an immediate compact response.

Verification:

- Codex main can start work with one command and later read one summary.
- No full task history is read in the normal path.

## Migration Strategy

Do not remove current task/manifest commands at first.

1. Add compact status without changing task execution.
2. Add run files as a layer over existing tasks.
3. Add supervisor over existing task states.
4. Add heartbeat resolver.
5. Add backend adapter.
6. Add high-level `delegate`.
7. Only then consider deprecating direct `send`/`dispatch` in normal docs.

## Non-Goals

- Do not build a general distributed Temporal replacement.
- Do not add remote services or databases.
- Do not let Claude workers run tests or shell commands.
- Do not make Codex main read detailed logs by default.
- Do not require Codex native subagents for execution.

## Completion Criteria

This plan is implemented when:

- Codex main can start a multi-task Claude run with one command.
- Normal status/summary output is under 1 KB.
- Heartbeat wake is resolved by one command without main-agent reasoning.
- Verified runs delete their thread-scoped automation automatically.
- Detailed task logs remain available but are opt-in.
- Claude backend behavior remains bounded by the existing safety contract.
- A fake backend proves the interface is backend-compatible.
