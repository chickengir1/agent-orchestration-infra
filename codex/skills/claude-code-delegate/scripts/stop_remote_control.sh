#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_file="${skill_dir}/state/current.env"

if [[ ! -f "${state_file}" ]]; then
  echo "claude-code-delegate: no current Remote Control state" >&2
  exit 0
fi

# shellcheck disable=SC1090
source "${state_file}"

log_file="${LOG_FILE:-}"

if [[ -n "${PID:-}" ]] && kill -0 "${PID}" 2>/dev/null; then
  kill "${PID}" 2>/dev/null || true
  sleep 1
  if kill -0 "${PID}" 2>/dev/null; then
    kill -9 "${PID}" 2>/dev/null || true
  fi
fi

rm -f "${state_file}"
if [[ -n "${log_file}" ]]; then
  rm -f "${log_file}"
fi

rmdir "${skill_dir}/state" 2>/dev/null || true

echo "Claude Remote Control stopped"
echo "session=${SESSION_NAME:-unknown}"
