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

if [[ -n "${PID:-}" ]] && kill -0 "${PID}" 2>/dev/null; then
  kill "${PID}" 2>/dev/null || true
  sleep 1
  if kill -0 "${PID}" 2>/dev/null; then
    kill -9 "${PID}" 2>/dev/null || true
  fi
fi

tmp_file="${state_file}.tmp"
grep -v '^STATUS=' "${state_file}" > "${tmp_file}" || true
printf 'STATUS=stopped\n' >> "${tmp_file}"
mv "${tmp_file}" "${state_file}"

echo "Claude Remote Control stopped"
echo "session=${SESSION_NAME:-unknown}"
