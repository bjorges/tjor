#!/usr/bin/env bash
# Multi-repo integration test (add-multi-repo): one session mounting two
# repos, both at their host paths, both writable, git works in each; and a
# nonexistent --dir aborts the launch.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
A="${HOME}/.tjor/tmp/mr-a"
B="${HOME}/.tjor/tmp/mr-b"
PASS=0; FAIL=0

ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

hash8() {
    if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8
    else printf %s "$1" | shasum -a 256 | cut -c1-8; fi
}
SID="mr-a-$(hash8 "${A}")"

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() {
    set +e
    ( cd "${A}" 2>/dev/null && "${T}" down >/dev/null 2>&1 )
    docker ps -aq --filter "label=tjor.session=${SID}" | xargs -r docker rm -f >/dev/null 2>&1
    docker network rm "tjor-${SID}_internal" >/dev/null 2>&1
    rm -rf "${A}" "${B}" "${HOME}/.tjor/sessions/${SID}"
}
trap cleanup EXIT

mkdir -p "${A}" "${B}"
( cd "${A}" && git init -q 2>/dev/null && echo a > file-a )
( cd "${B}" && git init -q 2>/dev/null && echo b > file-b )

echo "== launching one session over two repos"
( cd "${A}" && "${T}" run --detach --dir "${B}" sleep 300 >/dev/null 2>&1 )
CTR=""
for _ in $(seq 1 180); do
    CTR="$(docker ps -q --filter "label=tjor.role=agent" --filter "label=tjor.session=${SID}" --filter status=running | head -1)"
    [[ -n "${CTR}" ]] && break
    sleep 1
done
[[ -n "${CTR}" ]] || { echo "FATAL: multi-repo session never started"; exit 1; }

check "primary repo mounted at its host path" bash -c "docker exec '${CTR}' test -f '${A}/file-a'"
check "extra repo mounted at its host path" bash -c "docker exec '${CTR}' test -f '${B}/file-b'"
check "extra repo is writable by the agent" bash -c "docker exec '${CTR}' sh -c 'echo w > \"${B}/written-in-cage\"'"
check "write landed on the host" test -f "${B}/written-in-cage"
check "git works in the primary repo" bash -c "docker exec -w '${A}' '${CTR}' git status --porcelain >/dev/null 2>&1 || docker exec '${CTR}' git -C '${A}' status >/dev/null"
check "git works in the extra repo" bash -c "docker exec '${CTR}' git -C '${B}' status >/dev/null"
check "session id is derived from the primary (unchanged by --dir)" bash -c \
    "docker exec '${CTR}' printenv TJOR_SESSION_ID | grep -q '^${SID}\$'"

echo "== nonexistent --dir aborts"
check "a nonexistent --dir aborts the launch" bash -c \
    "cd '${A}' && ! '${T}' run --detach --session other --dir /no/such/dir-xyz true >/dev/null 2>&1"

echo
echo "multirepo: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
