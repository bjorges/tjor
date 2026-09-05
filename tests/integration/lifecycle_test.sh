#!/usr/bin/env bash
# Lifecycle integration test (add-session-lifecycle): two concurrent named
# sessions, label-driven discovery, degradation detection, attach, gc with
# state survival, and every reset tier including a symlink-escape attempt.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
REPO="${HOME}/.tjor/tmp/lifecycle-repo"
OUTSIDE="${HOME}/.tjor/tmp/lifecycle-outside"
FAKE_SID="fakedeg"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/tjor-lifecycle.XXXXXX")"
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
    for sid in "${SID_A:-}" "${SID_B:-}"; do
        [[ -n "${sid}" ]] || continue
        docker compose -p "tjor-${sid}" down --volumes --remove-orphans >/dev/null 2>&1 \
            || docker-compose -p "tjor-${sid}" down --volumes --remove-orphans >/dev/null 2>&1
        docker network rm "tjor-${sid}_internal" >/dev/null 2>&1
    done
    docker network rm "tjor-${FAKE_SID}_internal" >/dev/null 2>&1
    rm -rf "${REPO}" "${OUTSIDE}" "${SCRATCH}" "${HOME}"/.tjor/sessions/lifecycle-repo-*
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
    "test -d '${HOME}/.tjor/sessions/${SID_A}/home' && test -d '${HOME}/.tjor/sessions/${SID_B}/home'"
check "relaunching a running session id is refused (collision guard)" bash -c \
    "cd '${REPO}' && ! '${T}' run --detach --session a sleep 60 >/dev/null 2>&1"

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

# ---- 4. gc ---------------------------------------------------------------------
"${T}" gc --age 0 --dry-run > "${SCRATCH}/gc0.out" 2>&1
check "gc dry-run reaps nothing while sessions run" bash -c \
    "! grep -q 'would tear down session ${SID_A}' '${SCRATCH}/gc0.out'"
echo marker > "${HOME}/.tjor/sessions/${SID_A}/gc-survivor"
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
check "gc never touches state dirs" test -f "${HOME}/.tjor/sessions/${SID_A}/gc-survivor"

( cd "${REPO}" && "${T}" run --session a true >/dev/null 2>&1 )
check "session resumes after gc, state intact" test -f "${HOME}/.tjor/sessions/${SID_A}/gc-survivor"
( cd "${REPO}" && "${T}" down --session a >/dev/null 2>&1 )

# ---- 5. reset ------------------------------------------------------------------
SDIR="${HOME}/.tjor/sessions/${SID_A}"
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
"${T}" reset sessions --session a > "${SCRATCH}/reset-nested.out" 2>&1
check "reset refuses a tier with an intermediate symlink ancestor" \
    grep -qi "REFUSING" "${SCRATCH}/reset-nested.out"
check "intermediate-symlink escape failed: outside victim survived" test -f "${OUTSIDE}/storage/victim"
rm -f "${SDIR}/home/.local/share/opencode"   # remove the planted link
rm -rf "${OUTSIDE}/storage"
mkdir -p "${SDIR}/home/.local/share/opencode/storage" "${SDIR}/home/.config/gh"
echo x > "${SDIR}/home/.local/state/s1"
echo x > "${SDIR}/home/.local/share/opencode/storage/h1"
echo x > "${SDIR}/home/.local/share/opencode/auth.json"

"${T}" reset sessions --session a >/dev/null 2>&1
check "reset sessions wiped history, kept auth" bash -c \
    "! test -e '${SDIR}/home/.local/share/opencode/storage/h1' && test -f '${SDIR}/home/.local/share/opencode/auth.json'"
"${T}" reset creds --session a >/dev/null 2>&1
check "reset creds wiped auth and CA" bash -c \
    "! test -e '${SDIR}/home/.local/share/opencode/auth.json' && ! test -e '${SDIR}/proxy-ca'"
"${T}" reset all --session a >/dev/null 2>&1
check "reset all removed the state dir" bash -c "! test -d '${SDIR}'"


echo
echo "lifecycle: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
