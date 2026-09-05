#!/usr/bin/env bash
# Config + policy-ergonomics integration test (#22/#23): init/trust flow,
# repo-config trust gating, policy add, and the session denial log.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
REPO="${HOME}/.tjor/tmp/ergo-repo"
STORE="$(mktemp -d)/trusted.toml"
USERCFG="$(mktemp -d)"
export TJOR_TRUST_STORE="${STORE}"
export XDG_CONFIG_HOME="${USERCFG}"   # isolate user policy/config from the real one
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

hash8() { if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8; else printf %s "$1" | shasum -a 256 | cut -c1-8; fi; }
SID="ergo-repo-$(hash8 "${REPO}")"

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() {
    set +e
    ( cd "${REPO}" 2>/dev/null && "${T}" down >/dev/null 2>&1 )
    docker ps -aq --filter "label=tjor.session=${SID}" | xargs -r docker rm -f >/dev/null 2>&1
    docker network rm "tjor-${SID}_internal" >/dev/null 2>&1
    rm -rf "${REPO}" "$(dirname "${STORE}")" "${USERCFG}" "${HOME}/.tjor/sessions/${SID}"
}
trap cleanup EXIT

mkdir -p "${REPO}"; ( cd "${REPO}" && git init -q 2>/dev/null && echo x > f )

echo "== init + trust flow"
( cd "${REPO}" && "${T}" init >/dev/null 2>&1 )
check "init scaffolds .tjor/policy.toml and config.toml" bash -c "test -f '${REPO}/.tjor/policy.toml' && test -f '${REPO}/.tjor/config.toml'"
# Make the repo policy meaningfully different so we can tell it's in effect.
printf 'mode = "strict-allow"\n[hosts]\nallow = ["repo-marker.test"]\n' > "${REPO}/.tjor/policy.toml"
check "untrusted repo policy is ignored (repo marker not allowed)" bash -c \
    "cd '${REPO}' && '${T}' policy https://repo-marker.test/ 2>/dev/null | grep -q DENY"
( cd "${REPO}" && "${T}" trust >/dev/null 2>&1 )
check "trusted repo policy is honored (repo marker allowed)" bash -c \
    "cd '${REPO}' && '${T}' policy https://repo-marker.test/ 2>/dev/null | grep -q ALLOW"
printf 'mode = "strict-allow"\n[hosts]\nallow = ["changed.test"]\n' > "${REPO}/.tjor/policy.toml"
check "editing the repo policy revokes trust" bash -c \
    "cd '${REPO}' && '${T}' policy https://changed.test/ 2>/dev/null | grep -q DENY"

echo "== policy add + explain"
( cd "${REPO}" && "${T}" trust >/dev/null 2>&1 )   # re-approve the edited policy
( cd "${REPO}" && "${T}" policy add added.test >/dev/null 2>&1 )
check "policy add makes a host allowed" bash -c \
    "cd '${REPO}' && '${T}' policy https://added.test/ 2>/dev/null | grep -q ALLOW"
check "policy --explain names the active policy" bash -c \
    "cd '${REPO}' && '${T}' policy https://added.test/ --explain 2>&1 | grep -q 'active policy'"

echo "== denial log"
( cd "${REPO}" && "${T}" run --detach sleep 200 >/dev/null 2>&1 )
CTR=""; for _ in $(seq 1 180); do CTR="$(docker ps -q --filter "label=tjor.session=${SID}" --filter "label=tjor.role=agent" --filter status=running | head -1)"; [[ -n "${CTR}" ]] && break; sleep 1; done
[[ -n "${CTR}" ]] || { echo "FATAL: session never started"; exit 1; }
docker exec "${CTR}" sh -c 'curl -sS --max-time 15 https://blocked-example-xyz.test/ >/dev/null 2>&1 || true'
sleep 1
check "denied egress is recorded and surfaced by tjor denials" bash -c \
    "cd '${REPO}' && '${T}' denials 2>/dev/null | grep -q blocked-example-xyz.test"

echo
echo "ergonomics: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
