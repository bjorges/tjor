#!/usr/bin/env bash
# Multi-repo integration test (add-multi-repo): one session mounting two
# repos, both at their host paths, both writable, git works in each; and a
# nonexistent --dir aborts the launch. Plus --dir-ro (#44): a third repo
# mounted truly read-only — reads and git work, writes are refused
# container-wide, its dotenv is still masked, and a --dir/--dir-ro conflict
# aborts. Plus scoped prefix git trust (#53): writable roots are trusted as
# TREES (mid-session worktrees/clones and nested repos work), read-only
# roots stay exact-match, and the negative suite (vacuity guard, sibling,
# symlink escape, out-of-root, degenerate roots) pins the boundary — all
# trust assertions under GIT_TEST_ASSUME_DIFFERENT_OWNER=1.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
A="${HOME}/.tjor/tmp/mr-a"
B="${HOME}/.tjor/tmp/mr-b"
C="${HOME}/.tjor/tmp/mr-c"
P="${HOME}/.tjor/tmp/mr-p"     # parent of nested repos (#53 tree trust)
RO_SECRET="ro-secret-$$-do-not-leak"
# Forces git's ownership check even for own-uid repos (verified honored by
# the shipped git): without it the check short-circuits to success on
# uid-aligned engines and every trust assertion below would pass whether or
# not safe.directory is registered at all — vacuous tests.
GDO="GIT_TEST_ASSUME_DIFFERENT_OWNER=1"
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
    rm -rf "${A}" "${B}" "${C}" "${P}" "${HOME}/.tjor/tmp/mr-star" \
        "${HOME}/.tjor/sessions/${SID}" "${HOME}/.tjor/sessions/${SID}-other" \
        "${HOME}/.tjor/sessions/${SID}-g1" "${HOME}/.tjor/tmp/mr-run-out."*
}
trap cleanup EXIT

mkdir -p "${A}" "${B}" "${C}" "${P}/n1" "${P}/n2" "${C}/nested"
( cd "${A}" && git init -q 2>/dev/null && echo a > file-a )
( cd "${B}" && git init -q 2>/dev/null && echo b > file-b )
( cd "${C}" && git init -q 2>/dev/null && echo c > file-c )
( cd "${P}/n1" && git init -q 2>/dev/null && echo n1 > f )
( cd "${P}/n2" && git init -q 2>/dev/null && echo n2 > f )
( cd "${C}/nested" && git init -q 2>/dev/null && echo n > f )
printf 'API_KEY=%s\n' "${RO_SECRET}" > "${C}/.env"

echo "== launching one session: rw repos, a rw PARENT of repos, and a ro repo"
RUNOUT="${HOME}/.tjor/tmp/mr-run-out.$$"
( cd "${A}" && "${T}" run --detach --dir "${B}" --dir "${P}" --dir-ro "${C}" sleep 300 > "${RUNOUT}" 2>&1 )
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

echo "== --dir-ro: true read-only repo mount (#44)"
check "launch announced the read-only mount" grep -q "repo mount ${C} (read-only)" "${RUNOUT}"
check "ro repo mounted at its host path" bash -c "docker exec '${CTR}' test -f '${C}/file-c'"
check "ro repo is readable in-cage" bash -c "docker exec '${CTR}' grep -q c '${C}/file-c'"
check "write into the ro repo is refused (container-wide)" bash -c \
    "! docker exec '${CTR}' sh -c 'echo w > \"${C}/write-attempt\"' 2>/dev/null"
check "delete inside the ro repo is refused" bash -c \
    "! docker exec '${CTR}' rm -f '${C}/file-c' 2>/dev/null"
check "no write landed on the host" bash -c "! test -e '${C}/write-attempt'"
check "git works read-only in the ro repo (safe.directory covers it)" bash -c \
    "docker exec '${CTR}' git -C '${C}' status >/dev/null"
check "TJOR_RO_DIRS records the ro root (contract, #53)" bash -c \
    "docker exec '${CTR}' printenv TJOR_RO_DIRS | grep -qxF '${C}'"
# -e, not -f: the mask replaces the file with the /dev/null char device.
check "dotenv inside the ro repo is still masked" bash -c \
    "docker exec '${CTR}' sh -c 'test -e \"${C}/.env\" && ! grep -q \"${RO_SECRET}\" \"${C}/.env\"'"
check "launch announced the ro repo's dotenv mask" grep -q "dotenv mask ${C}/.env" "${RUNOUT}"

echo "== #53: writable roots are git-trusted as trees (prefix trust)"
# Vacuity guard FIRST: with the ownership short-circuit disabled, a repo in
# an UNREGISTERED location must be refused — proving every trust assertion
# below is decided by safe.directory, not by uid coincidence.
check "vacuity guard: unregistered repo refused under forced ownership check" bash -c \
    "docker exec '${CTR}' sh -c 'mkdir -p /tmp/vac && git init -q /tmp/vac && ! ${GDO} git -C /tmp/vac status >/dev/null 2>&1'"
check "writable roots registered starred, ro root exact-only" bash -c \
    "SD=\$(docker exec '${CTR}' git config --system --get-all safe.directory); \
     grep -qxF -- '${P}/*' <<<\"\$SD\" && grep -qxF -- '${P}' <<<\"\$SD\" \
     && grep -qxF -- '${C}' <<<\"\$SD\" && ! grep -qxF -- '${C}/*' <<<\"\$SD\""
check "#53 headline: mid-session worktree is git-usable immediately" bash -c \
    "docker exec '${CTR}' sh -c 'export ${GDO}; cd ${P}/n1 \
        && git config user.email t@tjor.test && git config user.name tjor-test \
        && git commit -q --allow-empty -m seed \
        && git worktree add -q ${P}/.worktrees/wt1 \
        && git -C ${P}/.worktrees/wt1 status >/dev/null \
        && git -C ${P}/.worktrees/wt1 log --oneline >/dev/null'"
check "mid-session clone under a writable root is trusted" bash -c \
    "docker exec '${CTR}' sh -c 'export ${GDO}; git clone -q ${P}/n2 ${P}/clone1 2>/dev/null && git -C ${P}/clone1 status >/dev/null'"
check "nested pre-existing repos under the writable parent are trusted" bash -c \
    "docker exec '${CTR}' sh -c '${GDO} git -C ${P}/n1 status >/dev/null && ${GDO} git -C ${P}/n2 status >/dev/null'"
check "nested repo under the ro parent stays refused (kept shield)" bash -c \
    "docker exec '${CTR}' sh -c '! ${GDO} git -C ${C}/nested status >/dev/null 2>&1'"
check "sibling name-extension is not covered by the starred root" bash -c \
    "docker exec '${CTR}' sh -c 'mkdir -p ${P}-evil/r && git init -q ${P}-evil/r && ! ${GDO} git -C ${P}-evil/r status >/dev/null 2>&1'"
check "symlink under a writable root does not extend trust" bash -c \
    "docker exec '${CTR}' sh -c 'ln -sfn /tmp/vac ${P}/esc && ! ${GDO} git -C ${P}/esc status >/dev/null 2>&1'"

echo "== nonexistent --dir aborts"
check "a nonexistent --dir aborts the launch" bash -c \
    "cd '${A}' && ! '${T}' run --detach --session other --dir /no/such/dir-xyz true >/dev/null 2>&1"
check "a nonexistent --dir-ro aborts the launch" bash -c \
    "cd '${A}' && ! '${T}' run --detach --session other --dir-ro /no/such/dir-xyz true >/dev/null 2>&1"

echo "== --dir/--dir-ro conflict aborts"
CONFOUT="${HOME}/.tjor/tmp/mr-run-out.conflict.$$"
if ( cd "${A}" && "${T}" run --detach --session other --dir "${C}" --dir-ro "${C}" true > "${CONFOUT}" 2>&1 ); then
    bad "same path via --dir and --dir-ro must abort"
else
    ok "same path via --dir and --dir-ro aborts"
fi
check "conflict error names the ambiguity" grep -q "conflicting mounts" "${CONFOUT}"

echo "== degenerate roots are refused (blanket-trust guard, #53)"
# A directory literally named '*' would register '<parent>/*' — a wildcard
# entry. The launcher must refuse it outright.
STARBASE="${HOME}/.tjor/tmp/mr-star"
mkdir -p "${STARBASE}/"'*'
STAROUT="${HOME}/.tjor/tmp/mr-run-out.star.$$"
if ( cd "${A}" && "${T}" run --detach --session g1 --dir "${STARBASE}/"'*' true > "${STAROUT}" 2>&1 ); then
    bad "a mount dir literally named '*' must abort the launch"
else
    ok "a mount dir literally named '*' aborts the launch"
fi
check "degenerate-root error names the wildcard risk" grep -q "wildcard-interpretable" "${STAROUT}"
# Regression: a ':' separator would mis-split a directory path that legally
# contains a colon, trusting a fragment and leaving the real repo untrusted.
# Feed the entrypoint a synthetic newline-delimited list with a colon-bearing
# path and assert git's system safe.directory holds the FULL path, not a split.
IMG="tjor-agent-opencode:local"
docker image inspect "${IMG}" >/dev/null 2>&1 || "${T}" build --harness opencode >/dev/null 2>&1
# plain is marked read-only: exact entry only, no starred sibling (#53);
# the colon-bearing writable entry must carry its starred sibling INTACT.
SDLIST=$'/repos/plain\n/repos/has:colon/inner\n'
GOT="$(docker run --rm -e TJOR_HARNESS=opencode -e TJOR_SAFE_DIRS="${SDLIST}" \
        -e TJOR_RO_DIRS=$'/repos/plain\n' "${IMG}" \
        git config --system --get-all safe.directory 2>/dev/null || true)"
if grep -qxF '/repos/has:colon/inner' <<<"${GOT}"; then ok "colon-bearing path kept intact in safe.directory"; else bad "colon-bearing path missing/split (got: ${GOT//$'\n'/ | })"; fi
if grep -qxF '/repos/has:colon/inner/*' <<<"${GOT}"; then ok "starred sibling of the colon path intact (#53)"; else bad "starred colon entry missing/mangled"; fi
if grep -qxF '/repos/plain' <<<"${GOT}"; then ok "plain path also trusted"; else bad "plain path missing"; fi
if grep -qxF '/repos/plain/*' <<<"${GOT}"; then bad "ro root got a starred entry (must stay exact-only)"; else ok "ro root stays exact-only (#53)"; fi
if grep -qxF '/repos/has' <<<"${GOT}"; then bad "path was SPLIT at the colon (/repos/has present)"; else ok "path was NOT split at the colon"; fi

echo "== entrypoint refuses degenerate trust entries; normalizes trailing slashes"
code=0
docker run --rm -e TJOR_HARNESS=opencode -e TJOR_SAFE_DIRS=$'/\n' "${IMG}" true >/dev/null 2>&1 || code=$?
if [ "${code}" -eq 90 ]; then ok "root '/' entry aborts with boundary code 90"; else bad "root '/' entry: expected 90, got ${code}"; fi
code=0
docker run --rm -e TJOR_HARNESS=opencode -e TJOR_SAFE_DIRS=$'/repos/x/*\n' "${IMG}" true >/dev/null 2>&1 || code=$?
if [ "${code}" -eq 90 ]; then ok "trailing-'/*' entry aborts with boundary code 90"; else bad "trailing-'/*' entry: expected 90, got ${code}"; fi
GOT="$(docker run --rm -e TJOR_HARNESS=opencode -e TJOR_SAFE_DIRS=$'/repos/slash/\n' "${IMG}" \
        git config --system --get-all safe.directory 2>/dev/null || true)"
if grep -qxF '/repos/slash/*' <<<"${GOT}" && ! grep -qxF '/repos/slash//*' <<<"${GOT}"; then
    ok "trailing-slash root normalized before registration"
else
    bad "trailing-slash root mishandled (got: ${GOT//$'\n'/ | })"
fi

echo
echo "multirepo: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
