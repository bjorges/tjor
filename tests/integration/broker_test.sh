#!/usr/bin/env bash
# Broker integration test (add-credential-broker): the real credential lives
# ONLY in the proxy sidecar; a broker-enabled AGENT container never possesses
# it (filesystem, env, or process args), yet git is wired to attempt auth via
# a placeholder. Uses the pat source with a stub token — no network.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
REPO="${HOME}/.tjor/tmp/broker-repo"
CFG="$(mktemp -d "${TMPDIR:-/tmp}/tjor-broker-cfg.XXXXXX")"
SECRET="tjor-broker-secret-$$-do-not-leak"
PASS=0; FAIL=0

ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

hash8() {
    if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8
    else printf %s "$1" | shasum -a 256 | cut -c1-8; fi
}

SID="broker-repo-$(hash8 "${REPO}")"

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() {
    set +e
    ( cd "${REPO}" 2>/dev/null && TJOR_USER_CONFIG="${CFG}/config.toml" "${T}" down >/dev/null 2>&1 )
    docker ps -aq --filter "label=tjor.session=${SID}" | xargs -r docker rm -f >/dev/null 2>&1
    docker network rm "tjor-${SID}_internal" >/dev/null 2>&1
    rm -rf "${REPO}" "${CFG}" "${HOME}/.tjor/sessions/${SID}"
}
trap cleanup EXIT

mkdir -p "${REPO}"
( cd "${REPO}" && git init -q 2>/dev/null && echo x > f )
cat > "${CFG}/config.toml" <<EOF
[broker]
source = "pat"
hosts = ["github.com", "*.github.com"]
pat_env = "TJOR_TEST_PAT"
EOF

echo "== launching a broker-enabled session (pat source, stub token)"
export TJOR_TEST_PAT="${SECRET}"
( cd "${REPO}" && TJOR_USER_CONFIG="${CFG}/config.toml" "${T}" run --detach sleep 300 >/dev/null 2>&1 )

CTR=""
for _ in $(seq 1 180); do
    CTR="$(docker ps -q --filter "label=tjor.role=agent" --filter "label=tjor.session=${SID}" --filter status=running | head -1)"
    [[ -n "${CTR}" ]] && break
    sleep 1
done
[[ -n "${CTR}" ]] || { echo "FATAL: broker session never started"; exit 1; }
PROXY="$(docker ps -q --filter "label=tjor.role=proxy" --filter "label=tjor.session=${SID}" | head -1)"

# 1. The secret is present in the PROXY (egress side) ...
check "proxy sidecar holds the real credential" bash -c \
    "docker exec '${PROXY}' cat /broker/broker.json | grep -q '${SECRET}'"

# 2. ... and ABSENT everywhere in the AGENT container.
check "agent env has no credential" bash -c \
    "! docker exec '${CTR}' env | grep -q '${SECRET}'"
check "agent filesystem has no credential" bash -c \
    "! docker exec '${CTR}' grep -rIl '${SECRET}' /home/agent /etc /tmp 2>/dev/null | grep -q ."
check "agent process args have no credential" bash -c \
    "! docker exec '${CTR}' sh -c 'cat /proc/*/cmdline 2>/dev/null | tr \"\\0\" \" \"' | grep -q '${SECRET}'"
check "agent cannot read the broker dir at all" bash -c \
    "! docker exec '${CTR}' test -e /broker"

# 3. git is wired to a PLACEHOLDER (attempts auth) — never a real secret.
HELPER="$(docker exec "${CTR}" git config --system --get 'credential.https://github.com.helper' 2>/dev/null || true)"
check "git credential helper is wired to a placeholder" bash -c "grep -q placeholder <<<'${HELPER}'"
check "git credential helper does not contain the real secret" bash -c "! grep -q '${SECRET}' <<<'${HELPER}'"

echo
echo "broker: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
