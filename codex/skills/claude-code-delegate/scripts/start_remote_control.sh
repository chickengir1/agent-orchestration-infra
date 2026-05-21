#!/usr/bin/env bash
set -euo pipefail

session_name="${1:-codex-delegate}"
workdir="${2:-$(pwd)}"

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="${skill_dir}/state"
state_file="${state_dir}/current.env"
log_file="${state_dir}/${session_name}.log"

mkdir -p "${state_dir}"

cd "${workdir}"

if ! command -v claude >/dev/null 2>&1; then
  echo "claude-code-delegate: missing claude CLI" >&2
  exit 127
fi

auth_json="$(claude auth status --json 2>&1 || true)"
if [[ "${auth_json}" != *'"loggedIn": true'* && "${auth_json}" != *'"loggedIn":true'* ]]; then
  cat >&2 <<'EOF'
claude-code-delegate: Claude auth is unavailable in this execution context.

Run this skill script from the authenticated host context. A Codex sandbox may
report loggedIn=false even when the user's normal Claude Code session is logged in.
EOF
  echo "${auth_json}" >&2
  exit 2
fi

: > "${log_file}"

claude remote-control \
  --name "${session_name}" \
  --permission-mode auto \
  --spawn=session \
  >"${log_file}" 2>&1 &

pid="$!"

url=""
for _ in $(seq 1 80); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "claude-code-delegate: remote-control exited before becoming ready" >&2
    cat "${log_file}" >&2
    exit 3
  fi

  url="$(grep -Eo 'https://claude\.ai/code[^[:space:]]+' "${log_file}" | tail -n 1 || true)"
  if [[ -n "${url}" ]]; then
    break
  fi

  sleep 0.25
done

if [[ -z "${url}" ]]; then
  echo "claude-code-delegate: remote-control did not publish a URL" >&2
  cat "${log_file}" >&2
  kill "${pid}" 2>/dev/null || true
  exit 4
fi

cat > "${state_file}" <<EOF
SESSION_NAME=${session_name}
PID=${pid}
WORKDIR=${workdir}
URL=${url}
LOG_FILE=${log_file}
PERMISSION_MODE=auto
STATUS=ready
EOF

open "${url}"

echo "Claude Remote Control ready"
echo "session=${session_name}"
echo "pid=${pid}"
echo "url=${url}"
echo "state=${state_file}"
echo "log=${log_file}"
