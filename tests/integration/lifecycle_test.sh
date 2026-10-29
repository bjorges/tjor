#!/usr/bin/env bash
# Lifecycle integration test (add-session-lifecycle): two concurrent named
# sessions, label-driven discovery, degradation detection, attach, gc with
# state survival, relaunch of a stopped session with a changed --dir list (#78),
# every reset tier including a symlink-escape attempt, and the state-root
# inventory and prune with a real launch interleaved against the session lock
# (#68). The suite OWNS its session root: a scratch root under $HOME (the
# Docker VM shares $HOME; /tmp is not shared) selected through
# TJOR_USER_CONFIG, so the age sweep in section 6 can never reach an
# operator's real ~/.tjor/sessions (review round 2).
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
REPO="${HOME}/.tjor/tmp/lifecycle-repo"
OUTSIDE="${HOME}/.tjor/tmp/lifecycle-outside"
EXTRA="${HOME}/.tjor/tmp/lifecycle-extra"     # a repo added by --dir on relaunch (#78)
FAKE_SID="fakedeg"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/tjor-lifecycle.XXXXXX")"
SROOT="${HOME}/.tjor/tmp/lifecycle-sessions"            # this suite's own session root (never the real one)
# The config lives in its OWN directory: the sensitive-path gate treats the
# directory of TJOR_USER_CONFIG as tjor's config dir and refuses everything
# under it, which would include the test repo if the file sat in ~/.tjor/tmp.
LIFECYCLE_CONFIG_DIR="${HOME}/.tjor/tmp/lifecycle-config"
mkdir -p "${SROOT}" "${LIFECYCLE_CONFIG_DIR}"
printf '[session]\nroot = "%s"\n' "${SROOT}" > "${LIFECYCLE_CONFIG_DIR}/config.toml"
export TJOR_USER_CONFIG="${LIFECYCLE_CONFIG_DIR}/config.toml"
# Isolation is unconditional (review round 3): an inherited TJOR_REPO_ROOT
# could let a trusted repo config move session.root, so it is cleared, and the
# effective root is asserted here and again right before the age sweep.
unset TJOR_REPO_ROOT
TJOR_PY="$(cd "$(dirname "${T}")/../python" && pwd)"
assert_scratch_root() {
    local eff
    eff="$(python3 "${TJOR_PY}/tjor_cfg.py" get session.root)"
    [[ "${eff}" == "${SROOT}" ]] || { echo "lifecycle: REFUSING to run — effective session.root is '${eff}', not the scratch root ${SROOT}" >&2; exit 1; }
}
assert_scratch_root
PASS=0; FAIL=0

ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

hash8() {
    if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8
    else printf %s "$1" | shasum -a 256 | cut -c1-8; fi
}

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() {
    set +e
    jobs -p | xargs -r kill 2>/dev/null
    docker ps -aq --filter "label=tjor.workspace=${REPO}" | xargs -r docker rm -f >/dev/null 2>&1
    docker ps -aq --filter "label=tjor.session=${FAKE_SID}" | xargs -r docker rm -f >/dev/null 2>&1
    local sid
    for sid in "${SID_A:-}" "${SID_B:-}" "${SID_C:-}"; do
        [[ -n "${sid}" ]] || continue
        docker compose -p "tjor-${sid}" down --volumes --remove-orphans >/dev/null 2>&1 \
            || docker-compose -p "tjor-${sid}" down --volumes --remove-orphans >/dev/null 2>&1
        docker network rm "tjor-${sid}_internal" >/dev/null 2>&1
    done
    docker network rm "tjor-${FAKE_SID}_internal" >/dev/null 2>&1
    rm -rf "${REPO}" "${OUTSIDE}" "${EXTRA}" "${SCRATCH}" "${SROOT}" "${LIFECYCLE_CONFIG_DIR}"
}
trap cleanup EXIT

wait_for_agent() { # session id -> echoes container id
    local ctr
    for _ in $(seq 1 180); do
        ctr="$(docker ps -q --filter "label=tjor.role=agent" --filter "label=tjor.session=$1" --filter status=running | head -1)"
        [[ -n "${ctr}" ]] && { echo "${ctr}"; return 0; }
        sleep 1
    done
    return 1
}

# ---- setup -------------------------------------------------------------------
mkdir -p "${REPO}" "${OUTSIDE}"
echo canary > "${OUTSIDE}/canary"
cd "${REPO}" && git init -q 2>/dev/null; echo x > f.txt
echo "== pre-building images"
"${T}" build >/dev/null 2>&1

BASE_SID="lifecycle-repo-$(hash8 "${REPO}")"
SID_A="${BASE_SID}-a"
SID_B="${BASE_SID}-b"

echo "== launching two named detached sessions"
"${T}" run --detach --session a --task LIFE-1 sleep 600 >/dev/null 2>&1
CTR_A="$(wait_for_agent "${SID_A}")" || { echo "FATAL: session a never started"; exit 1; }
"${T}" run --detach --session b sleep 600 >/dev/null 2>&1
CTR_B="$(wait_for_agent "${SID_B}")" || { echo "FATAL: session b never started"; exit 1; }

# ---- 1. labels & discovery ----------------------------------------------------
check "agent carries discovery labels" bash -c \
    "docker inspect -f '{{index .Config.Labels \"tjor.workspace\"}}|{{index .Config.Labels \"tjor.harness\"}}|{{index .Config.Labels \"tjor.task\"}}' '${CTR_A}' | grep -q '${REPO}|opencode|LIFE-1'"
check "launched-at label is an epoch timestamp" bash -c \
    "docker inspect -f '{{index .Config.Labels \"tjor.launched-at\"}}' '${CTR_A}' | grep -Eq '^[0-9]{10}\$'"

# ---- 3. multiplexing isolation -------------------------------------------------
check "distinct session ids" test "${SID_A}" != "${SID_B}"
check "distinct identity in-cage" test \
    "$(docker exec "${CTR_A}" printenv TJOR_SESSION_ID)" != "$(docker exec "${CTR_B}" printenv TJOR_SESSION_ID)"
check "distinct internal networks" \
    docker network inspect "tjor-${SID_A}_internal" "tjor-${SID_B}_internal"
check "distinct state roots" bash -c \
    "test -d '${SROOT}/${SID_A}/home' && test -d '${SROOT}/${SID_B}/home'"
check "relaunching a running session id is refused (collision guard)" bash -c \
    "cd '${REPO}' && ! '${T}' run --detach --session a sleep 60 >/dev/null 2>&1"
check "reset refuses a running session (TOCTOU guard)" bash -c \
    "cd '${REPO}' && ! '${T}' reset cache --session a >/dev/null 2>&1"
check "reset --force overrides the running-session guard (dry-run)" bash -c \
    "cd '${REPO}' && '${T}' reset cache --session a --dry-run >/dev/null 2>&1"

# ---- 1.2 ls + degradation ------------------------------------------------------
"${T}" ls > "${SCRATCH}/ls.out" 2>/dev/null
check "ls shows session a RUNNING with task" bash -c \
    "grep -E '^${SID_A}[[:space:]]+RUNNING' '${SCRATCH}/ls.out' | grep -q LIFE-1"
check "ls shows session b RUNNING" \
    grep -Eq "^${SID_B}[[:space:]]+RUNNING" "${SCRATCH}/ls.out"

docker rm -f tjor-lifecycle-fake >/dev/null 2>&1 || true
docker run -d --name tjor-lifecycle-fake --label tjor.role=agent \
    --label "tjor.session=${FAKE_SID}" --label "tjor.launched-at=$(date +%s)" \
    --entrypoint python3 tjor-conformance:local -c 'import time; time.sleep(600)' >/dev/null
docker network create --label "tjor.session=${FAKE_SID}" "tjor-${FAKE_SID}_internal" >/dev/null  # NOT --internal: sabotage
"${T}" ls > "${SCRATCH}/ls2.out" 2>/dev/null
check "ls flags non-internal network as DEGRADED" \
    grep -Eq "^${FAKE_SID}[[:space:]]+DEGRADED" "${SCRATCH}/ls2.out"

# ---- 2. attach (resolution; the exec is a trusted docker shell-out) ---------
# TJOR_ATTACH_DRY reports the resolved "<session> <container>" instead of
# exec'ing docker attach (which needs a real TTY and can't be driven under
# timeout deterministically). We assert it resolves the right container and
# leaves it untouched.
ATT="$(TJOR_ATTACH_DRY=1 "${T}" attach "${SID_A}" 2>/dev/null)"
check "attach resolves the named session to its agent container" bash -c \
    "grep -q '^${SID_A} ' <<<'${ATT}' && docker ps -q --no-trunc --filter label=tjor.session=${SID_A} | grep -q \"\$(awk '{print \$2}' <<<'${ATT}')\""
check "attach did not disturb the agent" bash -c "docker ps -q --no-trunc | grep -q '${CTR_A}'"
check "attach with no running agent for a session errors" bash -c "! TJOR_ATTACH_DRY=1 '${T}' attach no-such-session-xyz >/dev/null 2>&1"
ATT_SHORT="$(TJOR_ATTACH_DRY=1 "${T}" attach a 2>/dev/null)"
check "attach resolves a SHORT name against this workspace (#52)" bash -c \
    "grep -q '^${SID_A} ' <<<'${ATT_SHORT}'"

# ---- 2b. session-name resolution (#52) -----------------------------------------
# The footgun: tjor's own messages show the FULLY-QUALIFIED id; passing it back
# through --session used to get the workspace prefix blindly re-prepended,
# tearing down a doubled phantom while the real session kept running.
SID_C="${BASE_SID}-c"
"${T}" run --detach --session c sleep 600 >/dev/null 2>&1
wait_for_agent "${SID_C}" >/dev/null || { echo "FATAL: session c never started"; exit 1; }
check "launching with a FOREIGN qualified session id is refused" bash -c \
    "cd '${SCRATCH}' && '${T}' run --detach --session '${SID_C}' sleep 60 2>&1 | grep -q 'another workspace'"
check "foreign-id launch refusal created no phantom container" bash -c \
    "docker ps -aq --filter 'label=tjor.session=${SID_C}' --filter 'label=tjor.workspace=${SCRATCH}' | wc -l | grep -q '^ *0\$'"
( cd "${REPO}" && "${T}" down --session "${SID_C}" >/dev/null 2>&1 )
check "down with the fully-qualified id tears down the REAL session" bash -c \
    "! docker ps -aq --filter 'label=tjor.session=${SID_C}' | grep -q ."
check "no doubled phantom id was constructed" bash -c \
    "! docker ps -aq --filter 'label=tjor.session=${BASE_SID}-${SID_C}' | grep -q . && ! test -d '${SROOT}/${BASE_SID}-${SID_C}'"
"${T}" run --detach --session c sleep 600 >/dev/null 2>&1
wait_for_agent "${SID_C}" >/dev/null || { echo "FATAL: session c never restarted"; exit 1; }
check "down with the qualified id works from a DIFFERENT cwd" bash -c \
    "cd '${SCRATCH}' && '${T}' down --session '${SID_C}' >/dev/null 2>&1 && ! docker ps -aq --filter 'label=tjor.session=${SID_C}' | grep -q ."
check "down against a nonexistent session says so" bash -c \
    "cd '${REPO}' && '${T}' down --session never-was 2>&1 | grep -q 'nothing found for session'"
# A truncated paste of the qualified prefix (trailing dash, empty name) must be
# refused — it used to resolve silently to the DEFAULT session (#52 class).
check "a truncated qualified id (trailing dash) is refused, not defaulted" bash -c \
    "cd '${REPO}' && '${T}' down --session '${BASE_SID}-' 2>&1 | grep -q 'truncated'"
check "the truncated-id refusal exits nonzero" bash -c \
    "cd '${REPO}' && ! '${T}' down --session '${BASE_SID}-' >/dev/null 2>&1"

# ---- 4. gc ---------------------------------------------------------------------
"${T}" gc --age 0 --dry-run > "${SCRATCH}/gc0.out" 2>&1
check "gc dry-run reaps nothing while sessions run" bash -c \
    "! grep -q 'would tear down session ${SID_A}' '${SCRATCH}/gc0.out'"
echo marker > "${SROOT}/${SID_A}/gc-survivor"
docker rm -f "${CTR_A}" tjor-lifecycle-fake >/dev/null 2>&1
"${T}" gc --age 0 --dry-run > "${SCRATCH}/gc1.out" 2>&1
check "gc dry-run lists the idle session" \
    grep -q "would tear down session ${SID_A}" "${SCRATCH}/gc1.out"
check "gc dry-run removed nothing" docker network inspect "tjor-${SID_A}_internal"
"${T}" gc --age 0 >/dev/null 2>&1
check "gc removed the idle session's containers" bash -c \
    "! docker ps -aq --filter 'label=tjor.session=${SID_A}' | grep -q ."
check "gc removed the idle session's networks" bash -c \
    "! docker network inspect 'tjor-${SID_A}_internal'"
check "gc removed the sabotaged orphan network" bash -c \
    "! docker network inspect 'tjor-${FAKE_SID}_internal'"
check "gc left running session b alone" bash -c "docker ps -q --no-trunc | grep -q '${CTR_B}'"
check "gc never touches state dirs" test -f "${SROOT}/${SID_A}/gc-survivor"

( cd "${REPO}" && "${T}" run --session a true >/dev/null 2>&1 )
check "session resumes after gc, state intact" test -f "${SROOT}/${SID_A}/gc-survivor"
( cd "${REPO}" && "${T}" down --session a >/dev/null 2>&1 )

# ---- 4b. relaunch of a STOPPED session applies the current --dir list (#78) ----
# Every `tjor run` creates the agent container afresh from its own command
# line (the only collision guard is against a RUNNING agent), so adding a
# --dir and relaunching the same session mounts it — no --restart needed. The
# exited container stays until gc/down; the session is listed once.
mkdir -p "${EXTRA}" && ( cd "${EXTRA}" && git init -q 2>/dev/null && echo extra > canary )
( cd "${REPO}" && "${T}" run --detach --session a sleep 600 >/dev/null 2>&1 )
CTR_A2="$(wait_for_agent "${SID_A}")"
check "before relaunch: the extra repo is not mounted" \
    docker exec "${CTR_A2}" sh -c "! test -e '${EXTRA}'"
check "an explicit docker stop leaves the agent container exited" bash -c \
    "docker stop -t 2 '${CTR_A2}' >/dev/null 2>&1 && [ \"\$(docker inspect -f '{{.State.Status}}' '${CTR_A2}')\" = exited ]"
( cd "${REPO}" && "${T}" run --detach --session a --dir "${EXTRA}" sleep 600 >/dev/null 2>&1 )
CTR_A3="$(wait_for_agent "${SID_A}")"
check "relaunch of a stopped session creates a new agent container (#78)" \
    test -n "${CTR_A3}" -a "${CTR_A3}" != "${CTR_A2}"
check "relaunch applies the added --dir: mounted and writable in-cage (#78)" \
    docker exec "${CTR_A3}" sh -c "test -f '${EXTRA}/canary' && touch '${EXTRA}/written-in-cage'"
check "relaunch hands the cage an allowlist that names the added --dir (#78)" \
    docker exec "${CTR_A3}" sh -c "printf '%s' \"\$TJOR_SAFE_DIRS\" | grep -qx '${EXTRA}'"
check "the stopped container stays for gc; ls lists the session once, RUNNING (#78)" bash -c \
    "[ \"\$(docker ps -aq --filter label=tjor.role=agent --filter 'label=tjor.session=${SID_A}' | wc -l)\" -eq 2 ] \
     && [ \"\$('${T}' ls 2>/dev/null | grep -c '^${SID_A} ')\" -eq 1 ] && '${T}' ls 2>/dev/null | grep '^${SID_A} ' | grep -q RUNNING"
( cd "${REPO}" && "${T}" down --session a >/dev/null 2>&1 )
check "down after relaunch removes both agent containers" bash -c \
    "! docker ps -aq --filter 'label=tjor.session=${SID_A}' | grep -q ."

# ---- 5. reset ------------------------------------------------------------------
SDIR="${SROOT}/${SID_A}"
mkdir -p "${SDIR}/home/.local/state" "${SDIR}/home/.local/share/opencode/storage" "${SDIR}/home/.config/gh"
echo x > "${SDIR}/home/.local/state/s1"
echo x > "${SDIR}/home/.local/share/opencode/storage/h1"
echo x > "${SDIR}/home/.local/share/opencode/auth.json"
rm -rf "${SDIR}/home/.cache"
ln -s "${OUTSIDE}" "${SDIR}/home/.cache"   # symlink-escape attempt

cd "${REPO}"
check "reset requires an explicit tier" bash -c "! '${T}' reset --session a"
"${T}" reset cache --session a --dry-run > "${SCRATCH}/reset.out" 2>&1
check "reset dry-run lists and preserves" bash -c \
    "grep -q 'would delete' '${SCRATCH}/reset.out' && test -L '${SDIR}/home/.cache'"
"${T}" reset cache --session a >/dev/null 2>&1
check "reset removed the planted symlink itself" bash -c \
    "! test -e '${SDIR}/home/.cache' && ! test -L '${SDIR}/home/.cache'"
check "symlink escape failed: outside canary survived" test -f "${OUTSIDE}/canary"

# INTERMEDIATE-symlink escape on a NESTED tier: swap home/.local/share/opencode
# (an ancestor of the sessions/creds targets) for a symlink pointing outside
# the session, where the escape target has REAL content the wipe would hit.
# reset must REFUSE — rm -rf follows symlinks in a path prefix.
mkdir -p "${OUTSIDE}/storage"
echo escape-victim > "${OUTSIDE}/storage/victim"
rm -rf "${SDIR}/home/.local/share/opencode"
ln -s "${OUTSIDE}" "${SDIR}/home/.local/share/opencode"
"${T}" reset sessions --session a > "${SCRATCH}/reset-nested.out" 2>&1 && RESET_RC=0 || RESET_RC=$?
check "reset refuses a tier with an intermediate symlink ancestor" \
    grep -qi "REFUSING" "${SCRATCH}/reset-nested.out"
check "a refused path makes reset exit non-zero (review round 3)" test "${RESET_RC}" -ne 0
check "intermediate-symlink escape failed: outside victim survived" test -f "${OUTSIDE}/storage/victim"
rm -f "${SDIR}/home/.local/share/opencode"   # remove the planted link
rm -rf "${OUTSIDE}/storage"
# the escape-block 'reset sessions' legitimately wiped .local/state; recreate
# every dir the tier checks below need.
mkdir -p "${SDIR}/home/.local/state" "${SDIR}/home/.local/share/opencode/storage" "${SDIR}/home/.config/gh"
echo x > "${SDIR}/home/.local/state/s1"
echo x > "${SDIR}/home/.local/share/opencode/storage/h1"
echo x > "${SDIR}/home/.local/share/opencode/auth.json"

"${T}" reset sessions --session a >/dev/null 2>&1
check "reset sessions wiped history, kept auth" bash -c \
    "! test -e '${SDIR}/home/.local/share/opencode/storage/h1' && test -f '${SDIR}/home/.local/share/opencode/auth.json'"
mkdir -p "${SDIR}/broker"; echo secret > "${SDIR}/broker/broker.json"
"${T}" reset creds --session a >/dev/null 2>&1
check "reset creds wiped auth, CA, and the broker dir (App key)" bash -c \
    "! test -e '${SDIR}/home/.local/share/opencode/auth.json' && ! test -e '${SDIR}/proxy-ca' && ! test -e '${SDIR}/broker'"
"${T}" reset all --session a >/dev/null 2>&1
check "reset all removed the state dir" bash -c "! test -d '${SDIR}'"

# ---- 6. state inventory + prune (#68) ------------------------------------------
# Session a: no containers, no state dir (reset all above). Session b: running.
SDIR_A="${SROOT}/${SID_A}"; SDIR_B="${SROOT}/${SID_B}"
wait_for_file() { local f="$1" n="${2:-300}" i; for ((i = 0; i < n; i++)); do [[ -e "${f}" ]] && return 0; sleep 0.1; done; return 1; }
lock_free() { bash -c 'exec 7>>"$1"; python3 "$2" lock-try 7 "$1"' _ "${SROOT}/.locks/$1" "${TJOR_PY}/tjor_state.py"; }   # a separate process can take it
age_tree() { # $1 dir, $2 days -> every lstat time under it set that old (deep files stay the newest signal)
    python3 - "$1" "$2" <<'PY'
import os, sys, time
root, t = sys.argv[1], time.time() - int(sys.argv[2]) * 86400
for dp, dns, fns in os.walk(root, followlinks=False):
    for n in dns + fns:
        os.utime(os.path.join(dp, n), (t, t), follow_symlinks=False)
os.utime(root, (t, t), follow_symlinks=False)
PY
}
# (a) lifecycle commands create nothing
( cd "${REPO}" && "${T}" down --session never >/dev/null 2>&1 ) || true
( cd "${REPO}" && "${T}" reset cache --session never >/dev/null 2>&1 ) || true
( cd "${REPO}" && "${T}" status --session never >/dev/null 2>&1 ) || true
( cd "${REPO}" && "${T}" denials --session never >/dev/null 2>&1 ) || true
( cd "${REPO}" && "${T}" git-check --session never >/dev/null 2>&1 ) || true
( cd "${REPO}" && "${T}" prune --session never --dry-run >/dev/null 2>&1 ) || true
check "lifecycle commands naming a never-launched session create no state directory (#68)" bash -c \
    "! test -e '${SROOT}/${BASE_SID}-never' && ! test -e '${SROOT}/.locks/${BASE_SID}-never'"
check "a launch of a never-launched session refused at a path gate (--dir /etc) creates no state directory and holds no lock (#68)" bash -c \
    "cd '${REPO}' && ! '${T}' run --detach --session fresh --dir /etc sleep 1 >/dev/null 2>&1 && ! test -e '${SROOT}/${BASE_SID}-fresh' && $(declare -f lock_free); SROOT='${SROOT}'; TJOR_PY='${TJOR_PY}'; lock_free '${BASE_SID}-fresh' >/dev/null 2>&1"
check "a launch refused at a profile gate (unknown --profile) creates no state directory and holds no lock (review round 3)" bash -c \
    "cd '${REPO}' && ! '${T}' run --detach --session fresh --profile nosuch sleep 1 > '${SCRATCH}/run-prof.out' 2>&1 && grep -q 'no profile named' '${SCRATCH}/run-prof.out' && ! test -e '${SROOT}/${BASE_SID}-fresh' && $(declare -f lock_free); SROOT='${SROOT}'; TJOR_PY='${TJOR_PY}'; lock_free '${BASE_SID}-fresh' >/dev/null 2>&1"
# (b) metadata from the real launch; inventory of a legacy dir beside it
check "launch wrote meta.json: workspace, harness, no task, launch count 1, the documented keys only (#68)" bash -c \
    "python3 -c \"import json,sys; m=json.load(open('${SDIR_B}/meta.json')); sys.exit(0 if m['workspace']=='${REPO}' and m['harness']=='opencode' and m['task'] is None and m['launches']==1 and m['created']==m['last_launch'] and set(m)=={'schema','session','workspace','harness','profile','task','created','last_launch','launches'} else 1)\""
check "meta.json holds no key or certificate material" bash -c "! grep -qi 'PRIVATE KEY\\|BEGIN CERT\\|token' '${SDIR_B}/meta.json'"
LEGACY_SID="${BASE_SID}-legacy"; LEGACY="${SROOT}/${LEGACY_SID}"
DEEP="${LEGACY}/home/.local/share/opencode/storage/a/b/c/d/e/f"
mkdir -p "${DEEP}" "${LEGACY}/home/.config/gh"
echo h > "${DEEP}/h1"; echo t > "${LEGACY}/home/.local/share/opencode/auth.json"; echo t > "${LEGACY}/home/.config/gh/hosts.yml"
age_tree "${LEGACY}" 40
touch "${DEEP}/h1"   # the newest file sits eleven levels down; every parent stays 40 days old
"${T}" ls --state > "${SCRATCH}/lsstate.out" 2>&1
check "ls --state: the legacy dir shows unknown workspace, no containers, the deep file's age and its credentials (#68)" bash -c \
    "grep -E '^${LEGACY_SID} +none +[0-9]+m +unknown +home/.local/share/opencode/auth.json,home/.config/gh\$' '${SCRATCH}/lsstate.out'"
check "ls --state: the running session shows its workspace (meta.json), running, and the session CA (#68)" bash -c \
    "grep -E '^${SID_B} +running +[0-9]+[mhd] +${REPO} +proxy-ca,ca.pem\$' '${SCRATCH}/lsstate.out'"
BEFORE="$(python3 -c 'import os,sys; print(max(os.lstat(os.path.join(dp,n)).st_mtime_ns for dp,dns,fns in os.walk(sys.argv[1]) for n in dns+fns))' "${LEGACY}")"
"${T}" ls --state >/dev/null 2>&1; "${T}" prune --older-than 30d --dry-run >/dev/null 2>&1 || true
check "reading (ls --state, prune --dry-run) refreshes no timestamp (#68)" bash -c \
    "[ \"\$(python3 -c 'import os,sys; print(max(os.lstat(os.path.join(dp,n)).st_mtime_ns for dp,dns,fns in os.walk(sys.argv[1]) for n in dns+fns))' '${LEGACY}')\" = '${BEFORE}' ]"
age_tree "${LEGACY}" 40   # the deep touch above made it fresh; back to 40 days old for the age sweeps below
# (c) selectors
check "prune without a selector is usage and removes nothing" bash -c \
    "! '${T}' prune >/dev/null 2>&1 && test -d '${LEGACY}' && test -d '${SDIR_B}'"
check "prune with both selectors is refused before anything is selected" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session b --older-than 0d >/dev/null 2>&1 && test -d '${LEGACY}' && test -d '${SDIR_B}'"
check "prune --discard-unreviewed with --older-than is refused" bash -c \
    "! '${T}' prune --older-than 0d --discard-unreviewed >/dev/null 2>&1 && test -d '${LEGACY}'"
# (d) any container, in any state, refuses; tjor down is the way out
check "prune refuses the running session, naming tjor down" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session b > '${SCRATCH}/prune-b.out' 2>&1 && grep -q 'has containers' '${SCRATCH}/prune-b.out' && grep -q 'tjor down --session ${SID_B}' '${SCRATCH}/prune-b.out' && test -d '${SDIR_B}'"
docker stop -t 2 "${CTR_B}" >/dev/null 2>&1
check "prune refuses the session with its agent exited and sidecars running" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session b > '${SCRATCH}/prune-b2.out' 2>&1 && grep -q 'has containers' '${SCRATCH}/prune-b2.out' && test -d '${SDIR_B}'"
docker ps -q --filter "label=tjor.session=${SID_B}" | xargs -r docker stop -t 2 >/dev/null 2>&1
check "prune refuses the session with every container stopped (any state counts; tjor down removes them)" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session b > '${SCRATCH}/prune-b3.out' 2>&1 && grep -q 'has containers (exited)' '${SCRATCH}/prune-b3.out' && test -d '${SDIR_B}'"
( cd "${REPO}" && "${T}" down --session b >/dev/null 2>&1 )
check "after tjor down, prune --dry-run would remove the session's dir with its credential flags" bash -c \
    "cd '${REPO}' && '${T}' prune --session b --dry-run > '${SCRATCH}/prune-b4.out' 2>&1 && grep -q 'would remove ${SDIR_B} (creds: proxy-ca,ca.pem)' '${SCRATCH}/prune-b4.out' && test -d '${SDIR_B}'"
# (e) a pending git-check marker
PEND_SID="${BASE_SID}-pend"; PEND="${SROOT}/${PEND_SID}"
mkdir -p "${PEND}/gitcheck" "${PEND}/broker" "${PEND}/home/.local/state"
: > "${PEND}/gitcheck/pending"; echo '{"repos":[]}' > "${PEND}/gitcheck/baseline.json"; echo s > "${PEND}/broker/broker.json"; echo x > "${PEND}/home/.local/state/s1"
age_tree "${PEND}" 40
check "reset all refuses while the git-check marker is pending and names the explicit way out (#68)" bash -c \
    "cd '${REPO}' && ! '${T}' reset all --session ${PEND_SID} > '${SCRATCH}/reset-pend.out' 2>&1 && grep -q 'pending git-check' '${SCRATCH}/reset-pend.out' && test -f '${PEND}/gitcheck/pending' && test -f '${PEND}/broker/broker.json'"
check "prune refuses whole-directory deletion while the git-check marker is pending, naming the review command" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session ${PEND_SID} > '${SCRATCH}/prune-pend.out' 2>&1 && grep -q 'git-check pending' '${SCRATCH}/prune-pend.out' && grep -q 'tjor git-check --session ${PEND_SID}' '${SCRATCH}/prune-pend.out' && test -f '${PEND}/gitcheck/pending'"
check "prune --older-than refuses the pending session and still previews the legacy one" bash -c \
    "! '${T}' prune --older-than 30d --dry-run > '${SCRATCH}/prune-age.out' 2>&1 && grep -q 'refused: ${PEND_SID} — git-check pending' '${SCRATCH}/prune-age.out' && grep -q 'would remove ${LEGACY}' '${SCRATCH}/prune-age.out' && test -d '${LEGACY}' && test -d '${PEND}'"
check "prune --creds-only is not blocked by the marker: broker gone, baseline, marker and history kept, forgotten not revoked" bash -c \
    "cd '${REPO}' && '${T}' prune --session ${PEND_SID} --creds-only > '${SCRATCH}/prune-co.out' 2>&1 && ! test -e '${PEND}/broker' && test -f '${PEND}/gitcheck/pending' && test -f '${PEND}/gitcheck/baseline.json' && test -f '${PEND}/home/.local/state/s1' && grep -q 'forgotten, not revoked' '${SCRATCH}/prune-co.out'"
check "prune --session --discard-unreviewed removes the directory and says the findings were discarded" bash -c \
    "cd '${REPO}' && '${T}' prune --session ${PEND_SID} --discard-unreviewed > '${SCRATCH}/prune-disc.out' 2>&1 && grep -q 'unreviewed git-check findings discarded' '${SCRATCH}/prune-disc.out' && ! test -e '${PEND}'"
# (f) the symlink guard, from the canonical root
ESC_SID="${BASE_SID}-esc"; ESC="${SROOT}/${ESC_SID}"
mkdir -p "${ESC}/broker" "${ESC}/home/.local/share" "${OUTSIDE}/opencode"
echo s > "${ESC}/broker/broker.json"; echo victim > "${OUTSIDE}/opencode/auth.json"
ln -s "${OUTSIDE}/opencode" "${ESC}/home/.local/share/opencode"
check "prune --creds-only refuses the path behind a planted intermediate symlink, removes the rest, exits non-zero (charter L26)" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session ${ESC_SID} --creds-only > '${SCRATCH}/prune-esc.out' 2>&1 && grep -q 'REFUSING ${ESC}/home/.local/share/opencode/auth.json' '${SCRATCH}/prune-esc.out' && test -f '${OUTSIDE}/opencode/auth.json' && test -f '${OUTSIDE}/canary' && ! test -e '${ESC}/broker'"
rm -rf "${ESC}" "${OUTSIDE}/opencode"
# (g)+(h) dry run preserves; --creds-only removes exactly the credential tier
CR_SID="${BASE_SID}-cr"; CR="${SROOT}/${CR_SID}"
mkdir -p "${CR}/broker" "${CR}/proxy-ca" "${CR}/home/.local/share/opencode" "${CR}/home/.config/gh" "${CR}/home/.claude/backups" "${CR}/home/.local/state"
echo s > "${CR}/broker/broker.json"; echo k > "${CR}/proxy-ca/key.pem"; echo c > "${CR}/ca.pem"
echo t > "${CR}/home/.local/share/opencode/auth.json"; echo t > "${CR}/home/.config/gh/hosts.yml"
echo t > "${CR}/home/.claude/.credentials.json"; echo a > "${CR}/home/.claude.json"; echo b > "${CR}/home/.claude/backups/x"; echo x > "${CR}/home/.local/state/s1"
check "prune --creds-only --dry-run lists every credential path and preserves all of them" bash -c \
    "cd '${REPO}' && '${T}' prune --session ${CR_SID} --creds-only --dry-run > '${SCRATCH}/prune-crd.out' 2>&1 && [ \"\$(grep -c 'would remove' '${SCRATCH}/prune-crd.out')\" -eq 8 ] && test -f '${CR}/broker/broker.json' && test -f '${CR}/home/.claude.json'"
check "prune --creds-only removes exactly the credential tier (tjor's own, opencode, gh, Claude Code) and keeps history" bash -c \
    "cd '${REPO}' && '${T}' prune --session ${CR_SID} --creds-only >/dev/null 2>&1; ! test -e '${CR}/broker' && ! test -e '${CR}/proxy-ca' && ! test -e '${CR}/ca.pem' && ! test -e '${CR}/home/.local/share/opencode/auth.json' && ! test -e '${CR}/home/.config/gh' && ! test -e '${CR}/home/.claude/.credentials.json' && ! test -e '${CR}/home/.claude.json' && ! test -e '${CR}/home/.claude/backups' && test -f '${CR}/home/.local/state/s1'"
rm -rf "${CR}"
# (i) the lock: a launch and a prune of one session cannot interleave. The
# holder signals readiness through the TJOR_TEST_HOLD_LOCK seam and is
# released by a file, never by a timing guess.
READY="${SCRATCH}/lock-ready"; RELEASE="${SCRATCH}/lock-release"
mkdir -p "${SDIR_A}/home"; echo old > "${SDIR_A}/home/marker"
rm -f "${READY}" "${RELEASE}"
( cd "${REPO}" && TJOR_TEST_HOLD_LOCK=120 TJOR_TEST_HOLD_LOCK_READY="${READY}" TJOR_TEST_HOLD_LOCK_RELEASE="${RELEASE}" "${T}" prune --session a > "${SCRATCH}/prune-hold.out" 2>&1 ) &
HOLD_PID=$!
wait_for_file "${READY}" || bad "prune never signalled that it holds the lock"
( cd "${REPO}" && "${T}" run --detach --session a sleep 600 > "${SCRATCH}/run-locked.out" 2>&1 ) && RUN_RC=0 || RUN_RC=$?
: > "${RELEASE}"; wait "${HOLD_PID}" || true
check "a launch while prune holds the session lock is refused, naming the lock and its holder (#68)" bash -c \
    "[ ${RUN_RC} -ne 0 ] && grep -q 'locked by another tjor command' '${SCRATCH}/run-locked.out' && grep -q 'cmd=prune' '${SCRATCH}/run-locked.out'"
check "the held prune then removed the directory; the refused launch left no state, no credential, no container" bash -c \
    "grep -q 'removed ${SDIR_A}' '${SCRATCH}/prune-hold.out' && ! test -e '${SDIR_A}' && ! docker ps -aq --filter 'label=tjor.session=${SID_A}' | grep -q ."
mkdir -p "${SDIR_A}/home"   # a relaunch: the dir exists while the launch holds the lock
rm -f "${READY}" "${RELEASE}"
( cd "${REPO}" && TJOR_TEST_HOLD_LOCK=120 TJOR_TEST_HOLD_LOCK_READY="${READY}" TJOR_TEST_HOLD_LOCK_RELEASE="${RELEASE}" "${T}" run --detach --session a --task LIFE-2 sleep 600 > "${SCRATCH}/run-hold.out" 2>&1 ) &
HOLD_PID=$!
wait_for_file "${READY}" || bad "the launch never signalled that it holds the lock"
check "prune while a launch holds the session lock is refused, naming the launch (#68)" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session a > '${SCRATCH}/prune-locked.out' 2>&1 && grep -q 'refused: ${SID_A} — locked' '${SCRATCH}/prune-locked.out' && grep -q 'cmd=run' '${SCRATCH}/prune-locked.out' && test -d '${SDIR_A}'"
check "prune --dry-run while the launch holds the lock says so as well" bash -c \
    "cd '${REPO}' && ! '${T}' prune --session a --dry-run > '${SCRATCH}/prune-locked-dry.out' 2>&1 && grep -q 'refused: ${SID_A} — locked' '${SCRATCH}/prune-locked-dry.out'"
: > "${RELEASE}"; wait "${HOLD_PID}" || true
CTR_A4="$(wait_for_agent "${SID_A}")" || true
check "the held launch completed and released its lock once the agent container existed" bash -c \
    "test -n '${CTR_A4}' && $(declare -f lock_free); SROOT='${SROOT}'; TJOR_PY='${TJOR_PY}'; lock_free '${SID_A}' >/dev/null 2>&1"
check "launch metadata records the task; a refused launch after the lock (sensitive --dir) leaves no lock behind" bash -c \
    "python3 -c \"import json,sys; m=json.load(open('${SDIR_A}/meta.json')); sys.exit(0 if m['task']=='LIFE-2' and m['launches']==1 else 1)\" \
     && cd '${REPO}' && ! '${T}' run --detach --session a --dir /etc sleep 1 >/dev/null 2>&1 && $(declare -f lock_free); SROOT='${SROOT}'; TJOR_PY='${TJOR_PY}'; lock_free '${SID_A}' >/dev/null 2>&1"
docker stop -t 2 "${CTR_A4}" >/dev/null 2>&1 || true
( cd "${REPO}" && "${T}" run --detach --session a --task LIFE-3 sleep 600 >/dev/null 2>&1 )
CTR_A5="$(wait_for_agent "${SID_A}")" || true
check "relaunch keeps created, bumps launches to 2 and updates the task (#68)" bash -c \
    "test -n '${CTR_A5}' && python3 -c \"import json,sys; m=json.load(open('${SDIR_A}/meta.json')); sys.exit(0 if m['task']=='LIFE-3' and m['launches']==2 and m['created']<=m['last_launch'] else 1)\""
# A holder that dies leaves nothing stale: kill -9 a launch while it holds the lock.
CRASH_SID="${BASE_SID}-crash"; CRASH="${SROOT}/${CRASH_SID}"
mkdir -p "${CRASH}/home"; echo x > "${CRASH}/home/marker"
rm -f "${READY}" "${RELEASE}"
( cd "${REPO}" && exec env TJOR_TEST_HOLD_LOCK=120 TJOR_TEST_HOLD_LOCK_READY="${READY}" "${T}" run --detach --session crash sleep 600 > "${SCRATCH}/run-crash.out" 2>&1 ) &
CRASH_PID=$!
wait_for_file "${READY}" || bad "the launch to be crashed never signalled that it holds the lock"
kill -9 "${CRASH_PID}"; wait "${CRASH_PID}" 2>/dev/null || true
check "a launch killed -9 while holding the lock leaves no stale lock: prune of that session proceeds at once (#68)" bash -c \
    "cd '${REPO}' && '${T}' prune --session crash > '${SCRATCH}/prune-crash.out' 2>&1 && grep -q 'removed ${CRASH}' '${SCRATCH}/prune-crash.out' && ! grep -q 'locked' '${SCRATCH}/prune-crash.out' && ! test -e '${CRASH}'"
STALE_SID="${BASE_SID}-stale"; STALE="${SROOT}/${STALE_SID}"
mkdir -p "${STALE}/home" "${SROOT}/.locks"; printf 'pid=%s cmd=run\n' "$(bash -c 'echo $$')" > "${SROOT}/.locks/${STALE_SID}"
check "a lock file whose recorded holder is long gone is simply free: prune proceeds without a reclaim step" bash -c \
    "cd '${REPO}' && '${T}' prune --session ${STALE_SID} > '${SCRATCH}/prune-stale.out' 2>&1 && ! grep -q 'locked' '${SCRATCH}/prune-stale.out' && ! test -e '${STALE}'"
# (j) a real age sweep: the legacy dir goes, the running session's dir stays (refused, exit non-zero)
assert_scratch_root   # never against an operator's real sessions
check "prune --older-than 30d removes the legacy dir and leaves the running session's dir (refused)" bash -c \
    "! '${T}' prune --older-than 30d > '${SCRATCH}/prune-real.out' 2>&1; grep -q 'removed ${LEGACY}' '${SCRATCH}/prune-real.out' && ! test -e '${LEGACY}' && test -d '${SDIR_A}'"
check "gc --dry-run is unchanged by prune: it still names only containers and networks, never state" bash -c \
    "'${T}' gc --age 0 --dry-run > '${SCRATCH}/gc2.out' 2>&1; ! grep -qi 'state dir\\b.*remov\\|prune' '${SCRATCH}/gc2.out'"


echo
echo "lifecycle: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
