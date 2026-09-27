#!/usr/bin/env bash
# Git tamper detection (#72), no docker required. Sources bin/tjor and drives
# the baseline / check / marker helpers and `tjor git-check` against temp
# repos under a throwaway $HOME with a custom session.root. The `check "…"`
# names are literal: they feed the boundary matrix as the `gitcheck` suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

WORK="${HOME}/.tjor/tmp/gitcheck-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
trap 'rm -rf "${WORK}"' EXIT
export GIT_CEILING_DIRECTORIES="${WORK}"
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"; printf '#!/usr/bin/env bash\nexit 1\n' > "${MOCKBIN}/docker"; chmod +x "${MOCKBIN}/docker"
export PATH="${MOCKBIN}:${PATH}"
export HOME="${WORK}/home"; mkdir -p "${HOME}/proj" "${HOME}/extra"
for r in proj extra; do git -C "${HOME}/${r}" init -q; git -C "${HOME}/${r}" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m base; done
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
STATE="${WORK}/state"; mkdir -p "${STATE}"
printf '[session]\nroot = "%s"\n' "${STATE}" > "${XDG_CONFIG_HOME}/tjor/config.toml"
unset TJOR_USER_CONFIG

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

LAST_OUT="${WORK}/last.out"
# The session dir tjor would use for proj's session "gc".
SDIR="$(cd "${HOME}/proj" && resolve_session opencode "" gc >/dev/null 2>&1 && printf '%s' "${TJOR_SESSION_DIR}")"
SID="$(basename "${SDIR}")"
gc_check() { ( cd "${HOME}/proj" && cmd_git_check "$@" ) >"${LAST_OUT}.stdout" 2>"${LAST_OUT}"; }
gc_refused() { ! gc_check "$@"; }
pending() { [[ -f "${SDIR}/gitcheck/pending" ]]; }
no_pending() { ! pending; }
report_lists() { gitcheck_pending_report 2>&1 | grep -q "session ${SID} has UNCHECKED repos"; }
report_silent() { ! gitcheck_pending_report 2>&1 | grep -q "UNCHECKED"; }

# === 1. Baseline + marker ===================================================
gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/extra" 2>"${LAST_OUT}"
check "gitcheck: baseline records every writable root" bash -c "python3 -c \"import json,sys; b=json.load(open('${SDIR}/gitcheck/baseline.json')); sys.exit(0 if {r['worktree'] for r in b['repos']}=={'${HOME}/proj','${HOME}/extra'} else 1)\""
check "gitcheck: pending marker written at baseline" pending
check "gitcheck: launch announced the baseline" grep -q "git-check baseline recorded (2 repos)" "${LAST_OUT}"
check "gitcheck: ls surfaces the unchecked session" report_lists

# === 2. A planted dangerous key is a finding; the marker survives ===========
git -C "${HOME}/proj" config core.hooksPath .custom-hooks
check "gitcheck: planted core.hooksPath makes git-check exit non-zero" gc_refused --session gc
check "gitcheck: the finding names the repo, key and value" bash -c "grep -q 'FINDING ${HOME}/proj: dangerous-key core.hookspath' '${LAST_OUT}' && grep -q '.custom-hooks' '${LAST_OUT}'"
check "gitcheck: findings say the marker stays and how to ack" grep -q -- "--ack" "${LAST_OUT}"
check "gitcheck: marker survives findings" pending
json_has_kind() { local out; out="$( ( cd "${HOME}/proj" && cmd_git_check --session gc --json ) 2>/dev/null || true )"; grep -q '"kind": "dangerous-key"' <<<"${out}"; }   # pipefail: capture first (exit 1 = findings)
check "gitcheck: --json emits the finding class" json_has_kind

# === 3. Acknowledge clears; a clean check clears ============================
check "gitcheck: --ack exits zero" gc_check --session gc --ack
check "gitcheck: --ack clears the marker" no_pending
check "gitcheck: ls is silent once acknowledged" report_silent
check "gitcheck: after --ack the acknowledged state is the new baseline (next check clean)" gc_check --session gc
git -C "${HOME}/proj" config core.hooksPath .another
check "gitcheck: a change after --ack is reported again" gc_refused --session gc
check "gitcheck: findings after an ack set the marker again" pending
gc_check --session gc --ack >/dev/null 2>&1 || true
git -C "${HOME}/proj" config --unset core.hooksPath
gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/extra" 2>/dev/null
git -C "${HOME}/proj" config remote.origin.url https://example.invalid/r
git -C "${HOME}/proj" config branch.main.remote origin
git -C "${HOME}/proj" config branch.main.merge refs/heads/main
check "gitcheck: push -u shaped writes are clean (exit zero)" gc_check --session gc
check "gitcheck: a clean check clears the marker" no_pending

# === 4. The repo argument finds the covering session ========================
gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/extra" 2>/dev/null
git -C "${HOME}/extra" config core.fsmonitor /tmp/evil
check "gitcheck: <repo> argument finds the covering session and reports" gc_refused "${HOME}/extra"
check "gitcheck: the extra repo's finding is attributed to it" grep -q "FINDING ${HOME}/extra: dangerous-key core.fsmonitor" "${LAST_OUT}"
mkdir -p "${HOME}/unrelated"
uncovered_refused() { ! ( cd "${HOME}/proj" && cmd_git_check "${HOME}/unrelated" ) >/dev/null 2>"${LAST_OUT}"; grep -q 'no session baseline covers' "${LAST_OUT}"; }
check "gitcheck: a repo no session covers is refused clearly" uncovered_refused
gc_check --session gc --ack >/dev/null 2>&1 || true

# === 5. Help text ===========================================================
help_names() { usage | grep -qF 'git-check [<repo>'; }
check "gitcheck: help text names git-check" help_names

echo
echo "gitcheck: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
