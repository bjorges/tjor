#!/usr/bin/env bash
# Session state inventory, prune and the per-session lock (#68), no docker
# required. Sources bin/tjor with a throwaway $HOME, a custom session.root and
# a MOCK docker on PATH whose `docker ps` answers are scripted per check, and
# drives the lock helpers, `tjor ls --state` and every `tjor prune` refusal and
# deletion path deterministically. The interplay with real containers and a
# real launch is the lifecycle suite's job (tests/integration/lifecycle_test.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

WORK="${HOME}/.tjor/tmp/state-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
HOLD_PID=""
# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() { [[ -n "${HOLD_PID}" ]] && kill "${HOLD_PID}" 2>/dev/null; chmod -R u+rwx "${WORK}" 2>/dev/null || true; rm -rf "${WORK}"; }
trap cleanup EXIT
export GIT_CEILING_DIRECTORIES="${WORK}"
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
# Mock docker: `docker ps` answers from TJOR_MOCK_CONTAINERS ("<sid> <state>"
# per line), filtered by the session label when the query names one, in the
# format the launcher asked for; TJOR_MOCK_DOCKER_FAIL makes every call fail.
cat > "${MOCKBIN}/docker" <<'MOCK'
#!/usr/bin/env bash
[[ -n "${TJOR_MOCK_DOCKER_FAIL:-}" ]] && { echo "Cannot connect to the Docker daemon (mock)" >&2; exit 1; }
[[ "${1:-}" == ps ]] || exit 0
want=""; fmt=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --filter) [[ "$2" == label=tjor.session=* ]] && want="${2#label=tjor.session=}"; shift 2 ;;
        --format) fmt="$2"; shift 2 ;;
        *) shift ;;
    esac
done
while read -r sid state; do
    [[ -n "${sid}" ]] || continue
    [[ -z "${want}" || "${want}" == "${sid}" ]] || continue
    if [[ "${fmt}" == *'{{.Label "tjor.session"}}'* ]]; then printf '%s\x1f%s\n' "${sid}" "${state}"; else printf '%s\n' "${state}"; fi
done <<<"${TJOR_MOCK_CONTAINERS:-}"
MOCK
chmod +x "${MOCKBIN}/docker"
export PATH="${MOCKBIN}:${PATH}"
export HOME="${WORK}/home"; mkdir -p "${HOME}/proj"
git -C "${HOME}/proj" init -q
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
STATE="${WORK}/state"; mkdir -p "${STATE}"
printf '[session]\nroot = "%s"\n' "${STATE}" > "${XDG_CONFIG_HOME}/tjor/config.toml"
unset TJOR_USER_CONFIG TJOR_TEST_HOLD_LOCK
TJOR_MOCK_CONTAINERS=""; TJOR_MOCK_DOCKER_FAIL=""; export TJOR_MOCK_CONTAINERS TJOR_MOCK_DOCKER_FAIL
OUTSIDE="${WORK}/outside"; mkdir -p "${OUTSIDE}"; echo canary > "${OUTSIDE}/canary"

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

OUT="${WORK}/last.out"
run() { ( cd "${HOME}/proj" && "$@" ) >"${OUT}" 2>&1; }         # stdout+stderr captured, status returned
# The command runs in a subshell of THIS shell (sourced functions inherited),
# must fail, and the post-condition (plain grep/test) must hold.
refuse_check() { local msg="$1" cond="$2"; shift 2; if ! run "$@" && bash -c "${cond}" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }
# Same, but the command must succeed.
ok_check() { local msg="$1" cond="$2"; shift 2; if run "$@" && bash -c "${cond}" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }
BASE="$(session_base_id "${HOME}/proj")"
sid() { printf '%s-%s' "${BASE}" "$1"; }
sdir() { printf '%s/%s' "${STATE}" "$(sid "$1")"; }
plant() { # $1 short name -> a state dir with every reset tier populated
    local d; d="$(sdir "$1")"
    mkdir -p "${d}/home/.cache" "${d}/home/.local/state" "${d}/home/.local/share/opencode/storage" "${d}/home/.config/gh" \
             "${d}/broker" "${d}/proxy-ca" "${d}/home/.claude/backups" "${d}/gitcheck"
    echo x > "${d}/home/.cache/c1"; echo x > "${d}/home/.local/state/s1"; echo x > "${d}/home/.local/share/opencode/storage/h1"
    echo t > "${d}/home/.local/share/opencode/auth.json"; echo t > "${d}/home/.config/gh/hosts.yml"
    echo t > "${d}/broker/broker.json"; echo k > "${d}/proxy-ca/key.pem"; echo c > "${d}/ca.pem"
    echo t > "${d}/home/.claude/.credentials.json"; echo a > "${d}/home/.claude.json"; echo b > "${d}/home/.claude/backups/x"
    echo '{"repos":[]}' > "${d}/gitcheck/baseline.json"
}
age_all() { # $1 dir, $2 seconds ago -> every lstat time under it set that old
    python3 - "$1" "$2" <<'PY'
import os, sys, time
root, ago = sys.argv[1], int(sys.argv[2]); t = time.time() - ago
for dp, dns, fns in os.walk(root, followlinks=False):
    for n in dns + fns:
        os.utime(os.path.join(dp, n), (t, t), follow_symlinks=False)
os.utime(root, (t, t), follow_symlinks=False)
PY
}
newest() { python3 -c 'import os,sys; print(max(os.lstat(os.path.join(dp,n)).st_mtime_ns for dp,dns,fns in os.walk(sys.argv[1]) for n in dns+fns))' "$1"; }

# === 1. the per-session lock ===================================================
LOCK="${STATE}/.locks/$(sid l)"
session_lock_acquire "$(sid l)" test >/dev/null 2>&1
check "lock: acquire creates <root>/.locks/<sid> with our pid" grep -q "^pid=$$ cmd=test\$" "${LOCK}/owner"
session_lock_release "$(sid l)"
check "lock: release removes our lock" bash -c "! test -e '${LOCK}'"
sleep 300 & HOLD_PID=$!
mkdir -p "${LOCK}"; printf 'pid=%s cmd=run\n' "${HOLD_PID}" > "${LOCK}/owner"
refuse_check "lock: held by a live process -> refused, naming the lock" \
    "grep -q 'locked by another tjor command' '${OUT}' && grep -q '${LOCK}' '${OUT}' && test -e '${LOCK}/owner'" \
    session_lock_acquire "$(sid l)" prune
session_lock_release "$(sid l)"
check "lock: release never removes someone else's lock" test -e "${LOCK}/owner"
kill "${HOLD_PID}"; wait "${HOLD_PID}" 2>/dev/null || true; HOLD_PID=""
DEAD="$(bash -c 'echo $$')"
printf 'pid=%s cmd=run\n' "${DEAD}" > "${LOCK}/owner"
session_lock_acquire "$(sid l)" prune 2>"${OUT}" && ACQ=0 || ACQ=1
check "lock: left by a dead process -> cleared, said, acquired" bash -c \
    "[ ${ACQ} -eq 0 ] && grep -q 'clearing stale session lock' '${OUT}' && grep -q '^pid=$$ ' '${LOCK}/owner'"
session_lock_release "$(sid l)"
mkdir -p "${LOCK}"; : > "${LOCK}/owner"
refuse_check "lock: an empty owner (holder mid-write) counts as held" "true" session_lock_acquire "$(sid l)" prune
rm -rf "${LOCK}"
SECONDS=0; TJOR_TEST_HOLD_LOCK=1 session_lock_acquire "$(sid l)" test >/dev/null 2>&1; session_lock_release "$(sid l)"
check "lock: TJOR_TEST_HOLD_LOCK holds the lock after acquiring (test seam)" test "${SECONDS}" -ge 1

# === 2. lifecycle commands create no state ====================================
( cd "${HOME}/proj" && resolve_session opencode "" never >/dev/null 2>&1 )
check "resolve_session creates nothing for a lifecycle command" bash -c "! test -e '$(sdir never)'"
( cd "${HOME}/proj" && resolve_session opencode "" never launch >/dev/null 2>&1 )
check "resolve_session creates nothing on the launch path either (cmd_run does, under the lock)" bash -c "! test -e '$(sdir never)'"
run cmd_reset cache --session never
check "reset of a never-launched session: nothing to delete, no directory left behind" bash -c "grep -q 'nothing to delete' '${OUT}' && ! test -e '$(sdir never)'"
run cmd_prune --session never --dry-run
check "prune --session of a never-launched session: no state directory, none created" bash -c "grep -q 'no state directory' '${OUT}' && ! test -e '$(sdir never)' && ! test -e '${STATE}/.locks/$(sid never)'"

# === 3. reset reads the tier from the helper, and dies when it cannot ==========
plant r
run cmd_reset creds --session r --dry-run
check "reset creds (dry) lists every credential-tier path incl. Claude Code's" bash -c \
    "grep -q 'would delete .*broker\$' '${OUT}' && grep -q 'home/.claude/.credentials.json' '${OUT}' && grep -q 'home/.claude.json' '${OUT}' && grep -q 'home/.claude/backups' '${OUT}' && grep -q 'home/.config/gh' '${OUT}'"
python3() { if [[ "${1:-}" == *tjor_state.py && "${2:-}" == tier ]]; then echo "mock helper crash" >&2; return 1; fi; command python3 "$@"; }
refuse_check "reset dies before deleting anything when the state helper fails" \
    "grep -q 'state helper failed' '${OUT}' && test -f '$(sdir r)/home/.cache/c1' && ! test -e '${STATE}/.locks/$(sid r)'" \
    cmd_reset cache --session r
unset -f python3
run cmd_reset cache --session r
check "reset still deletes its tier and leaves no lock behind" bash -c "! test -e '$(sdir r)/home/.cache' && ! test -e '${STATE}/.locks/$(sid r)'"
rm -rf "$(sdir r)"

# === 4. prune: selectors ======================================================
plant old; age_all "$(sdir old)" $((40 * 86400))
plant fresh
refuse_check "prune: no selector is usage, nothing removed" \
    "grep -q 'usage: tjor prune' '${OUT}' && test -d '$(sdir old)' && test -d '$(sdir fresh)'" cmd_prune
refuse_check "prune: both selectors are refused before anything is selected" \
    "grep -q 'alternatives' '${OUT}' && test -d '$(sdir old)' && test -d '$(sdir fresh)'" cmd_prune --session fresh --older-than 30d
refuse_check "prune: --discard-unreviewed with --older-than is usage" \
    "grep -q 'only with --session' '${OUT}' && test -d '$(sdir old)'" cmd_prune --older-than 0d --discard-unreviewed
refuse_check "prune: a malformed duration is refused" "grep -q 'takes <N>d' '${OUT}'" cmd_prune --older-than 2w
BEFORE="$(newest "$(sdir old)")"
run cmd_prune --older-than 30d --dry-run
check "prune --older-than (dry): lists the old directory with age and credential flags, not the fresh one" bash -c \
    "grep -q 'would remove $(sdir old) (idle 40d) (creds: .*broker' '${OUT}' && ! grep -q '$(sdir fresh)' '${OUT}' && test -d '$(sdir old)'"
check "prune (dry) refreshes no timestamp" test "$(newest "$(sdir old)")" = "${BEFORE}"
run cmd_prune --older-than 30d
check "prune --older-than removes only the old directory and says the broker credential is forgotten, not revoked" bash -c \
    "! test -e '$(sdir old)' && test -d '$(sdir fresh)' && grep -q 'removed $(sdir old)' '${OUT}' && grep -q 'forgotten, not revoked' '${OUT}'"
if [[ "$(id -u)" != 0 ]]; then
    plant unread; age_all "$(sdir unread)" $((40 * 86400)); chmod 000 "$(sdir unread)/home/.local"
    run cmd_prune --older-than 0d --dry-run
    check "prune --older-than never selects a directory it could not fully read (unknown, not stale)" bash -c \
        "grep -q 'skipped: $(sid unread)' '${OUT}' && ! grep -q 'would remove $(sdir unread)' '${OUT}'"
    chmod 755 "$(sdir unread)/home/.local"; rm -rf "$(sdir unread)"
fi

# === 5. prune: refusals (containers, query failure, lock, marker) =============
plant used
TJOR_MOCK_CONTAINERS="$(sid used) running"
refuse_check "prune refuses a session with a running container, naming tjor down" \
    "grep -q 'refused: $(sid used) — has containers (running) — tjor down' '${OUT}' && test -d '$(sdir used)'" cmd_prune --session used
TJOR_MOCK_CONTAINERS="$(sid used) exited"
refuse_check "prune refuses a session whose only container has exited (any state counts)" \
    "grep -q 'has containers (exited)' '${OUT}' && test -d '$(sdir used)'" cmd_prune --session used
refuse_check "prune --creds-only is refused the same way" \
    "grep -q 'has containers' '${OUT}' && test -f '$(sdir used)/broker/broker.json'" cmd_prune --session used --creds-only
TJOR_MOCK_CONTAINERS=""
TJOR_MOCK_DOCKER_FAIL=1
refuse_check "prune refuses when the container query fails, never assuming none" \
    "grep -q 'container query failed' '${OUT}' && test -d '$(sdir used)'" cmd_prune --session used
refuse_check "ls --state fails when the container query fails, never guessing" "grep -q 'refusing to guess' '${OUT}'" cmd_ls --state
TJOR_MOCK_DOCKER_FAIL=""
check "prune leaves no lock behind after a refusal" bash -c "! test -e '${STATE}/.locks/$(sid used)'"
sleep 300 & HOLD_PID=$!
mkdir -p "${STATE}/.locks/$(sid used)"; printf 'pid=%s cmd=run\n' "${HOLD_PID}" > "${STATE}/.locks/$(sid used)/owner"
refuse_check "prune refuses a session whose lock a live launch holds" \
    "grep -q 'refused: $(sid used) — locked' '${OUT}' && test -d '$(sdir used)'" cmd_prune --session used
kill "${HOLD_PID}"; wait "${HOLD_PID}" 2>/dev/null || true; HOLD_PID=""
printf 'pid=%s cmd=run\n' "${DEAD}" > "${STATE}/.locks/$(sid used)/owner"
: > "$(sdir used)/gitcheck/pending"
refuse_check "prune clears a stale lock, then refuses the pending git-check marker and names the review command" \
    "grep -q 'clearing stale session lock' '${OUT}' && grep -q 'git-check pending' '${OUT}' && grep -q 'tjor git-check --session $(sid used)' '${OUT}' && test -d '$(sdir used)' && ! test -e '${STATE}/.locks/$(sid used)'" \
    cmd_prune --session used
age_all "$(sdir used)" $((40 * 86400))
refuse_check "prune --older-than leaves a pending session in place (and exits non-zero)" \
    "grep -q 'refused: $(sid used) — git-check pending' '${OUT}' && test -f '$(sdir used)/gitcheck/pending'" cmd_prune --older-than 30d
run cmd_prune --session used --creds-only
check "prune --creds-only is not blocked by the marker: credentials gone, baseline, marker and history kept" bash -c \
    "! test -e '$(sdir used)/broker' && ! test -e '$(sdir used)/proxy-ca' && ! test -e '$(sdir used)/ca.pem' \
     && ! test -e '$(sdir used)/home/.local/share/opencode/auth.json' && ! test -e '$(sdir used)/home/.config/gh' \
     && ! test -e '$(sdir used)/home/.claude/.credentials.json' && ! test -e '$(sdir used)/home/.claude.json' && ! test -e '$(sdir used)/home/.claude/backups' \
     && test -f '$(sdir used)/gitcheck/pending' && test -f '$(sdir used)/gitcheck/baseline.json' \
     && test -f '$(sdir used)/home/.local/state/s1' && test -f '$(sdir used)/home/.local/share/opencode/storage/h1' && test -f '$(sdir used)/home/.cache/c1'"
run cmd_prune --session used --discard-unreviewed
check "prune --session --discard-unreviewed removes the directory and says the findings were discarded" bash -c \
    "! test -e '$(sdir used)' && grep -q 'unreviewed git-check findings discarded' '${OUT}'"

# === 6. prune: the symlink guard, from the canonical root =====================
plant esc
rm -rf "$(sdir esc)/home/.local/share/opencode"
mkdir -p "${OUTSIDE}/opencode"; echo victim > "${OUTSIDE}/opencode/auth.json"
ln -s "${OUTSIDE}/opencode" "$(sdir esc)/home/.local/share/opencode"
refuse_check "prune --creds-only refuses the path behind a planted intermediate symlink, removes the rest, exits non-zero" \
    "grep -q 'REFUSING $(sdir esc)/home/.local/share/opencode/auth.json' '${OUT}' && test -f '${OUTSIDE}/opencode/auth.json' && ! test -e '$(sdir esc)/broker' && ! test -e '$(sdir esc)/home/.config/gh'" \
    cmd_prune --session esc --creds-only
rm -rf "$(sdir esc)"
ln -s "${OUTSIDE}" "$(sdir link)"
run cmd_prune --session link
check "prune of a symlinked state entry removes the link, never what it points to" bash -c \
    "! test -L '$(sdir link)' && test -f '${OUTSIDE}/canary' && test -f '${OUTSIDE}/opencode/auth.json'"

# === 7. ls --state ==============================================================
plant legacy; age_all "$(sdir legacy)" $((3 * 86400))
touch "$(sdir legacy)/home/.local/share/opencode/storage/h1"   # the newest file sits deep; parents stay old
plant current; python3 "${ROOT}/python/tjor_state.py" meta-write "$(sdir current)" --session "$(sid current)" --workspace "${HOME}/proj" --harness claude --task T-9
ln -s "${OUTSIDE}" "${STATE}/planted-link"
mkdir -p "${STATE}/.locks/$(sid current)"
TJOR_MOCK_CONTAINERS="$(sid current) exited
$(sid current) running"
BEFORE="$(newest "$(sdir legacy)")"
run cmd_ls --state
check "ls --state: a legacy directory shows unknown workspace and the deep file's age" bash -c \
    "grep -E '^$(sid legacy) +none +[0-9]+m +unknown +.*auth.json' '${OUT}'"
check "ls --state: a current directory shows its workspace, running containers and credential flags" bash -c \
    "grep -E '^$(sid current) +running +[0-9]+m +${HOME}/proj +broker,proxy-ca,ca.pem,home/.local/share/opencode/auth.json,home/.config/gh,home/.claude/.credentials.json,home/.claude.json,home/.claude/backups\$' '${OUT}'"
check "ls --state: a planted link is reported, not read; the lock dir is not listed" bash -c \
    "grep -q 'planted-link (link): not a session directory' '${OUT}' && ! grep -q '^.locks' '${OUT}' && ! grep -q '^planted-link ' '${OUT}'"
check "ls --state refreshes no timestamp" test "$(newest "$(sdir legacy)")" = "${BEFORE}"
TJOR_MOCK_CONTAINERS="$(sid current) exited"
run cmd_ls --state
check "ls --state: only exited containers show as stopped" bash -c "grep -E '^$(sid current) +stopped ' '${OUT}'"
TJOR_MOCK_CONTAINERS=""
run cmd_ls
check "plain ls is unchanged (no containers -> no sessions)" grep -q 'no sessions' "${OUT}"

echo
echo "state: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
