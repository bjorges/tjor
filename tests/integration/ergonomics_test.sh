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
# `trust` without --yes and no TTY must REFUSE (the two-step confirm gate):
# approval is a separate act from display, never implicit.
check "trust refuses to approve without confirmation (no TTY, no --yes)" bash -c \
    "cd '${REPO}' && ! '${T}' trust >/dev/null 2>&1"
( cd "${REPO}" && "${T}" trust --yes >/dev/null 2>&1 )
check "trusted repo policy is honored (repo marker allowed)" bash -c \
    "cd '${REPO}' && '${T}' policy https://repo-marker.test/ 2>/dev/null | grep -q ALLOW"
printf 'mode = "strict-allow"\n[hosts]\nallow = ["changed.test"]\n' > "${REPO}/.tjor/policy.toml"
check "editing the repo policy revokes trust" bash -c \
    "cd '${REPO}' && '${T}' policy https://changed.test/ 2>/dev/null | grep -q DENY"

# Terminal-escape injection defense: a hostile .tjor file's ANSI escape must be
# neutralized in the trust REVIEW (rendered as a visible ^[ token), never sent
# to the terminal raw — else the operator could approve hidden/spoofed content.
# (A raw ESC lives in a string value here; a TOML *comment* may not hold one.)
printf 'mode = "strict-allow"\n[hosts]\nallow = ["esc\x1b[31mX.test"]\n' > "${REPO}/.tjor/policy.toml"
check "trust review neutralizes ANSI escapes (renders ^[ marker)" bash -c \
    "cd '${REPO}' && '${T}' trust --show 2>&1 | grep -q '\\^\\['"
# Restore a clean, valid policy for the rest of the flow.
printf 'mode = "strict-allow"\n[hosts]\nallow = ["added.test"]\n' > "${REPO}/.tjor/policy.toml"

echo "== policy add + explain"
( cd "${REPO}" && "${T}" trust --yes >/dev/null 2>&1 )   # re-approve the edited policy
( cd "${REPO}" && "${T}" policy add added.test --yes >/dev/null 2>&1 )   # repo policy: confirmed re-approve
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

echo "== denial recap at teardown (#42)"
DOWN_LOG="${USERCFG}/down-recap.out"
# Seed the workload-log volume counter (#50) so teardown surfaces its recap too;
# the addon writes this file the same way (per-pod pod<TAB>bytes lines).
printf 'pod-alpha\t3145728\npod-beta\t1048576\n' > "${HOME}/.tjor/sessions/${SID}/logvolume.log"
# Seed the egress secret-tripwire signal (#62): host<TAB>kinds lines, as the
# addon writes them — the recap aggregates count + distinct kinds, never a value.
printf 'tjor-gateway\tgithub-token,aws-access-key-id\ntjor-gateway\tgithub-token\n' \
    > "${HOME}/.tjor/sessions/${SID}/secretscan.log"
( cd "${REPO}" && "${T}" down >"${DOWN_LOG}" 2>&1 || true )
check "down prints the denial recap (count + host)" bash -c \
    "grep -q 'denied egress attempt' '${DOWN_LOG}' && grep -q 'blocked-example-xyz.test' '${DOWN_LOG}'"
check "recap names the review/widen commands" grep -q 'tjor policy add' "${DOWN_LOG}"
check "down prints the workload-log volume recap (#50: total + distinct pods)" bash -c \
    "grep -q 'read 4.0 MB of workload logs across 2 pod(s)' '${DOWN_LOG}'"
check "down prints the secret-tripwire recap (#62: count + distinct kinds)" bash -c \
    "grep -q '2 outbound inference request(s)' '${DOWN_LOG}' && grep -q 'aws-access-key-id, github-token' '${DOWN_LOG}'"
: > "${HOME}/.tjor/sessions/${SID}/denials.log"
: > "${HOME}/.tjor/sessions/${SID}/logvolume.log"
: > "${HOME}/.tjor/sessions/${SID}/secretscan.log"
( cd "${REPO}" && "${T}" down >"${DOWN_LOG}.quiet" 2>&1 || true )
check "clean session tears down without a recap" bash -c \
    "! grep -q 'denied egress attempt' '${DOWN_LOG}.quiet'"
check "clean session tears down without a log-volume recap" bash -c \
    "! grep -q 'workload logs' '${DOWN_LOG}.quiet'"
check "clean session tears down without a secret-tripwire recap" bash -c \
    "! grep -q 'inference request' '${DOWN_LOG}.quiet'"

echo
echo "ergonomics: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
