#!/usr/bin/env bash
# Real-PTY integration test (fix-interactive-tty-allocation, #51): drives the
# ACTUAL create-detached-then-attach flow under a genuine pseudo-terminal via
# script(1) — no TJOR_ATTACH_DRY shortcut — asserting the harness process sees
# an interactive stdin/stdout from its own first instruction and that input
# typed through the attach reaches it. This is exactly the flow the previous
# suite skipped, which is how #51 evaded it.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
REPO="${HOME}/.tjor/tmp/tty-repo"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/tjor-tty.XXXXXX")"
PASS=0; FAIL=0

ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

hash8() {
    if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8
    else printf %s "$1" | shasum -a 256 | cut -c1-8; fi
}

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() {
    set +e
    jobs -p | xargs -r kill 2>/dev/null
    local s
    for s in a b c; do
        (cd "${REPO}" 2>/dev/null && "${T}" down --session "tty${s}" >/dev/null 2>&1)
    done
    docker ps -aq --filter "label=tjor.workspace=${REPO}" | xargs -r docker rm -f >/dev/null 2>&1
    rm -rf "${REPO}" "${SCRATCH}" "${HOME}"/.tjor/sessions/tty-repo-*
}
trap cleanup EXIT

# run_pty <typescript-file> <cmd...>: run cmd under a REAL pseudo-terminal via
# script(1). BSD (macOS) and util-linux (Linux) script have incompatible
# syntax, and util-linux takes the command as one string — so the command is
# staged into a wrapper file, keeping quoting trivial on both. script's own
# stdout must NOT be redirected to a non-tty sink (BSD script then fails with
# tcgetattr errors when the outer stdin is also not a tty); the typescript
# file is the capture channel. Input for the child is whatever run_pty's
# stdin provides (a pipe works: script forwards it into the PTY).
run_pty() {
    local log="$1"; shift
    local wrapper="${SCRATCH}/pty-cmd.$$.sh"
    {
        echo '#!/usr/bin/env bash'
        printf '%q ' "$@"
        echo
        # the child's exit code, recoverable from the typescript
        # shellcheck disable=SC2016  # literal $? must expand inside the wrapper, not here
        echo 'echo "run-pty-rc=$?"'
    } > "${wrapper}"
    chmod +x "${wrapper}"
    if script --version 2>/dev/null | grep -q util-linux; then
        script -qec "${wrapper}" "${log}" | cat
    else
        script -q "${log}" "${wrapper}" | cat
    fi
}

pty_rc() { # extracts the child's exit code from a typescript
    tr -d '\r' < "$1" | grep -o 'run-pty-rc=[0-9]*' | tail -1 | cut -d= -f2
}

wait_agent_ctr() { # session id -> echoes the (possibly exited) agent container id
    local ctr
    for _ in $(seq 1 180); do
        ctr="$(docker ps -aq --filter "label=tjor.role=agent" --filter "label=tjor.session=$1" | head -1)"
        [[ -n "${ctr}" ]] && { echo "${ctr}"; return 0; }
        sleep 1
    done
    return 1
}

# ---- setup -------------------------------------------------------------------
mkdir -p "${REPO}"
cd "${REPO}" && git init -q 2>/dev/null; echo x > f.txt
echo "== pre-building images"
"${T}" build >/dev/null 2>&1

BASE_SID="tty-repo-$(hash8 "${REPO}")"

# ---- A. the harness sees a live PTY at its own startup ------------------------
# The in-cage probe runs [ -t 0 ] && [ -t 1 ] as its FIRST instruction — the
# exact check claude/opencode effectively make — long before any attach client
# could connect. Pre-fix (compose run -d without the TTY force, under command
# substitution) this reliably printed TTY-FAIL.
echo "== A: PTY present at harness startup"
run_pty "${SCRATCH}/a.log" "${T}" run --session ttya -- \
    sh -c 'if [ -t 0 ] && [ -t 1 ]; then echo TTY-OK; else echo TTY-FAIL; fi' >/dev/null
CTR_A="$(wait_agent_ctr "${BASE_SID}-ttya")" || { bad "session ttya never created a container"; CTR_A=""; }
if [[ -n "${CTR_A}" ]]; then
    if docker logs "${CTR_A}" 2>&1 | grep -q 'TTY-OK'; then ok "harness saw a TTY on stdin+stdout at startup"
    else bad "harness saw a TTY on stdin+stdout at startup"; fi
    if [[ "$(docker inspect -f '{{.Config.Tty}}' "${CTR_A}")" == "true" ]]; then ok "agent container created with Tty=true"
    else bad "agent container created with Tty=true"; fi
    if [[ "$(pty_rc "${SCRATCH}/a.log")" == "0" ]]; then ok "tjor run propagated the probe's exit code 0"
    else bad "tjor run propagated the probe's exit code 0"; fi
fi
(cd "${REPO}" && "${T}" down --session ttya >/dev/null 2>&1)

# ---- B. interactive input through the real attach reaches the harness ---------
# The probe announces READY, then blocks on read. The feeder waits for READY in
# docker logs before writing the line into the PTY: bytes fed EARLIER are
# consumed by compose's own startup (verified), so readiness-gating is
# load-bearing, not paranoia. This exercises the full chain:
# terminal -> tjor's docker attach -> container PTY -> harness read.
echo "== B: typed input reaches the harness through attach"
SID_B="${BASE_SID}-ttyb"
{
    for _ in $(seq 1 180); do
        c="$(docker ps -aq --filter "label=tjor.role=agent" --filter "label=tjor.session=${SID_B}" | head -1)"
        [[ -n "${c}" ]] && docker logs "${c}" 2>/dev/null | grep -q READY && break
        sleep 1
    done
    printf 'tjor-tty-ping\n'
    sleep 3
} | run_pty "${SCRATCH}/b.log" "${T}" run --session ttyb -- \
    sh -c 'echo READY; read -r line; if [ "$line" = "tjor-tty-ping" ]; then echo INPUT-PASS; else echo "INPUT-FAIL:[$line]"; fi' >/dev/null
CTR_B="$(wait_agent_ctr "${SID_B}")" || { bad "session ttyb never created a container"; CTR_B=""; }
if [[ -n "${CTR_B}" ]]; then
    for _ in $(seq 1 30); do
        docker logs "${CTR_B}" 2>&1 | grep -q 'INPUT-' && break
        sleep 1
    done
    if docker logs "${CTR_B}" 2>&1 | grep -q 'INPUT-PASS'; then ok "interactive input reached the harness through attach"
    else bad "interactive input reached the harness through attach"; fi
fi
(cd "${REPO}" && "${T}" down --session ttyb >/dev/null 2>&1)

# ---- C. no terminal: loud degradation, one-shot exit codes intact --------------
echo "== C: non-terminal launch degrades loudly"
RC=0
"${T}" run --session ttyc -- sh -c 'exit 7' < /dev/null > "${SCRATCH}/c.log" 2>&1 || RC=$?
if [[ "${RC}" == "7" ]]; then ok "one-shot exit code propagated without a terminal"
else bad "one-shot exit code propagated without a terminal (got rc=${RC})"; fi
if grep -q 'no terminal on stdin' "${SCRATCH}/c.log"; then ok "no-PTY warning printed"
else bad "no-PTY warning printed"; fi
CTR_C="$(docker ps -aq --filter "label=tjor.role=agent" --filter "label=tjor.session=${BASE_SID}-ttyc" | head -1)"
if [[ -n "${CTR_C}" && "$(docker inspect -f '{{.Config.Tty}}' "${CTR_C}")" == "false" ]]; then
    ok "terminal-less container has no PTY (auto-detect path unchanged)"
else
    bad "terminal-less container has no PTY (auto-detect path unchanged)"
fi
(cd "${REPO}" && "${T}" down --session ttyc >/dev/null 2>&1)

echo
echo "tty: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
