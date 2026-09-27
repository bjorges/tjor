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
printf '[session]\nroot = "%s"\n[landlock]\ngit_check_depth = 4\n' "${STATE}" > "${XDG_CONFIG_HOME}/tjor/config.toml"
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
GC="${ROOT}/python/tjor_gitcheck.py"
cur_token() { python3 "${GC}" check "${SDIR}/gitcheck/baseline.json" --token 2>/dev/null || true; }   # empty when clean
gc_ack() { gc_check --session gc --ack "$(cur_token)"; }   # the reviewed-state ack (token from the check just shown)

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
json_has_token() { local out; out="$( ( cd "${HOME}/proj" && cmd_git_check --session gc --json ) 2>/dev/null || true )"; grep -q "\"token\": \"$(cur_token)\"" <<<"${out}"; }
check "gitcheck: --json carries the ack token" json_has_token
rm -f "${SDIR}/gitcheck/pending"
( cd "${HOME}/proj" && cmd_git_check --session gc --json ) >/dev/null 2>&1 || true
check "gitcheck: --json findings set the marker (same rule as the human path)" pending

# === 3. Acknowledge is token-bound; a clean check clears ====================
TOK="$(cur_token)"
check "gitcheck: a bare --ack with findings is refused (exit non-zero)" gc_refused --session gc --ack
check "gitcheck: the refused ack shows the findings and the token to accept them" bash -c "grep -q 'FINDING ${HOME}/proj: dangerous-key core.hookspath' '${LAST_OUT}' && grep -q -- \"--ack ${TOK}\" '${LAST_OUT}' && grep -q 'unreviewed' '${LAST_OUT}'"
check "gitcheck: marker survives a refused ack" pending
check "gitcheck: a wrong token is refused" gc_refused --session gc --ack 000000000000
check "gitcheck: --ack <token> exits zero" gc_check --session gc --ack "${TOK}"
check "gitcheck: --ack clears the marker" no_pending
check "gitcheck: ls is silent once acknowledged" report_silent
check "gitcheck: after --ack the acknowledged state is the new baseline (next check clean)" gc_check --session gc
git -C "${HOME}/proj" config core.hooksPath .another
check "gitcheck: a change after --ack is reported again" gc_refused --session gc
check "gitcheck: findings after an ack set the marker again" pending
STALE="$(cur_token)"
git -C "${HOME}/proj" config core.hooksPath .moved-on
check "gitcheck: a stale token (the state moved on) is refused" gc_refused --session gc --ack "${STALE}"
check "gitcheck: the stale refusal names the current token" grep -q -- "--ack $(cur_token)" "${LAST_OUT}"
gc_ack >/dev/null 2>&1 || true
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
gc_ack >/dev/null 2>&1 || true

# === 5. Fail closed: what the check cannot see is a finding =================
gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/extra" 2>/dev/null
git -C "${HOME}/proj" config remote.evil.url 'ext::sh -c touch% /tmp/pwned'
check "gitcheck: an ext:: remote url is a finding" gc_refused --session gc
check "gitcheck: the ext:: finding names the remote url key" grep -q 'dangerous-key remote.evil.url' "${LAST_OUT}"
git -C "${HOME}/proj" config --remove-section remote.evil
cp "${HOME}/proj/.git/config" "${WORK}/config.bak"
printf '[core\n' >> "${HOME}/proj/.git/config"
check "gitcheck: a config git cannot parse is a finding, not clean" gc_refused --session gc
check "gitcheck: the unparseable config is reported as UNKNOWN, with git's error" bash -c "grep -q 'config-unreadable' '${LAST_OUT}' && grep -q 'UNKNOWN' '${LAST_OUT}' && grep -q 'bad config' '${LAST_OUT}'"
cp "${WORK}/config.bak" "${HOME}/proj/.git/config"
check "gitcheck: the repaired config checks clean again" gc_check --session gc
mkdir -p "${HOME}/proj/a/b/c/d/e"
check "gitcheck: a directory tree deeper than git_check_depth is a NEW truncation, reported" gc_refused --session gc
check "gitcheck: the truncation finding names the depth cap and UNCHECKED" bash -c "grep -q 'discovery-incomplete' '${LAST_OUT}' && grep -q 'depth-cap 4' '${LAST_OUT}' && grep -q 'UNCHECKED' '${LAST_OUT}'"
baseline_warns() { local out; out="$(gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/extra" 2>&1)"; grep -q "discovery incomplete under ${HOME}/proj/a/b/c/d: depth-cap 4" <<<"${out}"; }   # pipefail: capture first
check "gitcheck: a baseline taken over a truncated tree announces the truncation at launch" baseline_warns
check "gitcheck: the truncation known at baseline is not re-reported" gc_check --session gc
rm -rf "${HOME}/proj/a"
mkdir -p "${HOME}/plain"; gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/plain" 2>/dev/null
git -C "${HOME}/plain" init -q
repo_added_reported() { gc_refused --session gc && grep -q 'repo-added' "${LAST_OUT}"; }
check "gitcheck: a repository appearing under a non-repo root is a finding (repo-added)" repo_added_reported
rm -rf "${HOME}/plain"; gitcheck_baseline "${SDIR}" "${HOME}/proj" "${HOME}/extra" 2>/dev/null
gc_check --session gc >/dev/null 2>&1 || true

# === 6. Symlinked git metadata is refused at launch, never masked through =====
# plan_git_masks (run_agent's mask planner) driven directly, with the arrays
# it reads declared in a subshell: a hooks dir that is a symlink is refused.
# shellcheck disable=SC2034  # the arrays are read by plan_git_masks through dynamic scoping
plan_masks() { ( safe=("${HOME}/proj"); ro_dirs=""; declare -A masked=() dirmasked=(); mounts=(); empty_src="${WORK}/empty"; mkdir -p "${empty_src}"; TJOR_SESSION_DIR="${SDIR}"; plan_git_masks; printf '%s\n' "${mounts[@]}" ); }
plan_masks_hooks() { local out; out="$(plan_masks 2>/dev/null)"; grep -q ":${HOME}/proj/.git/hooks:ro" <<<"${out}"; }
check "git hooks: an ordinary hooks dir is masked" plan_masks_hooks
mv "${HOME}/proj/.git/hooks" "${WORK}/real-hooks"; ln -s "${WORK}/real-hooks" "${HOME}/proj/.git/hooks"
symlink_refused() { ! plan_masks >/dev/null 2>"${LAST_OUT}"; grep -q 'symbolic link' "${LAST_OUT}" && grep -q "$1" "${LAST_OUT}"; }   # $1 = the path the refusal must name
check "git hooks: a symlinked hooks dir refuses the launch instead of masking through the link" symlink_refused "${HOME}/proj/.git/hooks"
check "git hooks: the refusal names the fix (replace the link) and the opt-out" bash -c "grep -q 'remove the link' '${LAST_OUT}' && grep -q 'mask_git_hooks = false' '${LAST_OUT}'"
rm "${HOME}/proj/.git/hooks"; mv "${WORK}/real-hooks" "${HOME}/proj/.git/hooks"
mv "${HOME}/proj/.git" "${WORK}/real-git"; ln -s "${WORK}/real-git" "${HOME}/proj/.git"
check "git hooks: a symlinked .git entry is refused too" symlink_refused "${HOME}/proj/.git (a .git entry)"
rm "${HOME}/proj/.git"; mv "${WORK}/real-git" "${HOME}/proj/.git"
plan_ok() { plan_masks >/dev/null 2>&1; }
check "git hooks: with the real directories back the plan succeeds" plan_ok

# === 7. Help text ===========================================================
help_names() { usage | grep -qF 'git-check [<repo>' && usage | grep -qF -- '--ack [<token>]'; }
check "gitcheck: help text names git-check" help_names

echo
echo "gitcheck: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
