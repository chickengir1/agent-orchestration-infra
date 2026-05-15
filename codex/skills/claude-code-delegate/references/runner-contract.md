# Runner Contract

## Purpose

`delegate_claude.py` creates a file-backed Claude Code delegation job and executes Claude Code in non-interactive mode.

## Inputs

- `--objective`: Required. One concrete patch objective.
- `--allow`: Repeatable. Repo-relative file path Claude Code may edit.
- `--forbid`: Repeatable. Repo-relative file path or directory prefix Claude Code must not edit.
- `--validate`: Repeatable. Validation command the runner executes after Claude Code exits.
- `--job-id`: Optional stable job id. Defaults to timestamp-based id.
- `--dry-run`: Write job files without invoking Claude Code.
- `--allow-worker-bash`: Optional. Gives Claude Code the Bash tool. Off by default.
- `--validation-timeout`: Optional timeout in seconds for each runner validation command. Defaults to 600.
- `--model`: Optional Claude model or alias.
- `--max-budget-usd`: Optional Claude Code API budget cap.
- `--bare`: Optional minimal Claude Code mode. Use only when API-key/auth-helper credentials are available, because bare mode does not read OAuth/keychain authentication.

## Outputs

Each run writes `.codex/delegations/<job-id>/`:

- `task.md`: Worker task spec.
- `allowed-files.txt`: Allowed file list.
- `forbidden-files.txt`: Forbidden file list.
- `validation.txt`: Validation command list.
- `command.json`: Claude command metadata.
- `stdout.log`: Claude stdout.
- `stderr.log`: Claude stderr.
- `result.json`: Structured runner result.
- `before.diff`: Git diff before delegation.
- `after.diff`: Git diff after delegation.
- `scope-report.json`: File scope check result.
- `validation-results.json`: Structured runner validation results.
- `validation-results.txt`: Human-readable runner validation output.

## Exit Codes

- `0`: Claude ran, scope check passed, and all runner validation commands passed.
- `1`: Claude ran, but Claude returned non-zero, scope check failed, or runner validation failed.
- `2`: Invalid runner input or missing `claude` binary.

## Default Claude CLI Shape

Use headless execution:

```bash
claude -p --no-session-persistence --output-format json --max-turns 6 --permission-mode acceptEdits --tools Read,Edit,Write
```

The actual default tool set is `Read,Edit,Write`. `Bash` is added only when `--allow-worker-bash` is passed. This prevents Claude Code from burning turns on validation commands that the local permission layer may deny. Validation belongs to the runner, not the worker.

The runner should pass a short prompt telling Claude to read `task.md`, rather than embedding large repo context in the shell command.

## Code Shape Injection

The runner injects a compact `Code Shape Conventions` section into every `task.md`. The section is derived from the local `fundamental-reviewer` principles and constrains how Claude writes code inside the assigned patch. It must not authorize broad refactors or cleanup outside the objective.

## Review Requirement

Passing the runner does not mean the task is complete. Codex must still review `after.diff`, run final validation where appropriate, and decide whether to keep, modify, or reject the patch.
