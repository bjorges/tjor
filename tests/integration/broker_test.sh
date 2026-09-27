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
# The harness dumps ITS OWN environment and git's view of the credential
# helper first (what gh and git actually see, past the kernel-sandbox wrap's
# env filter and overrides) — asserted in 2b/2c — then sleeps.
( cd "${REPO}" && TJOR_USER_CONFIG="${CFG}/config.toml" "${T}" run --detach sh -c 'env > "$HOME/.harness-env"; git config --show-origin --get credential.https://github.com.helper > "$HOME/.harness-githelper" 2>&1; exec sleep 300' >/dev/null 2>&1 )

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
# 2b. gh (#65): the covered session hands gh the PLACEHOLDER via GH_TOKEN —
#     never the secret. Asserted on the HARNESS's own environment dump (the
#     launch command above), i.e. what gh inherits AFTER the kernel-sandbox
#     wrap's env sanitizer — not PID 1 (cplt, pre-sanitizer) and not a
#     `docker exec` shell (docker's own env list): both would pass wrongly.
HENV="$(docker exec "${CTR}" cat /home/agent/.harness-env 2>/dev/null || true)"
check "harness env dump exists (launch command ran past the wrap)" bash -c "grep -q '^HOME=' <<<'${HENV}'"
check "harness env carries the gh placeholder (GH_TOKEN)" bash -c "grep -qx 'GH_TOKEN=tjor-broker-placeholder' <<<'${HENV}'"
check "harness env has no credential either" bash -c "! grep -q '${SECRET}' <<<'${HENV}'"
# 2c. git under the wrap (#65 end-to-end): cplt sets GIT_CONFIG_NOSYSTEM=1
#     for the sandboxed child, which made git ignore /etc/gitconfig — the
#     placeholder helper, the SSH rewrites and the tree trust all live there.
#     The entrypoint unsets it inside the sandbox; git must see the helper.
HGIT="$(docker exec "${CTR}" cat /home/agent/.harness-githelper 2>/dev/null || true)"
check "harness env does not carry GIT_CONFIG_NOSYSTEM" bash -c "! grep -q '^GIT_CONFIG_NOSYSTEM=' <<<'${HENV}'"
check "git in the harness resolves the placeholder helper from /etc/gitconfig" bash -c \
    "grep -q 'file:/etc/gitconfig' <<<'${HGIT}' && grep -q placeholder <<<'${HGIT}'"

# 3. git is wired to a PLACEHOLDER (attempts auth) — never a real secret.
HELPER="$(docker exec "${CTR}" git config --system --get 'credential.https://github.com.helper' 2>/dev/null || true)"
check "git credential helper is wired to a placeholder" bash -c "grep -q placeholder <<<'${HELPER}'"
check "git credential helper does not contain the real secret" bash -c "! grep -q '${SECRET}' <<<'${HELPER}'"

# 4. Placeholder wiring is SCOPED to brokered destinations (#47): driven on
#    the real entrypoint directly (like the landlock handoff tests). The
#    coverage decision uses the proxy's own host matcher, so a broker scoped
#    elsewhere (kube-only) keeps the gh fallback — git must never send an
#    unsubstitutable placeholder to github.com.
IMAGE="${TJOR_AGENT_IMAGE:-tjor-agent-opencode:local}"
helper_for() { # $1 = TJOR_BROKER_HOSTS value, $2 = helper host
    docker run --rm -e TJOR_BROKER_ENABLED=1 -e "TJOR_BROKER_HOSTS=$1" "${IMAGE}" \
        sh -c "git config --system --get 'credential.https://$2.helper'" 2>/dev/null || true
}
H_COVERED="$(helper_for 'github.com,*.github.com' github.com)"
H_KUBE="$(helper_for 'kubeapi.example.com' github.com)"
H_KUBE_GIST="$(helper_for 'kubeapi.example.com' gist.github.com)"
H_GLOB="$(helper_for '*.github.com' github.com)"
check "github-covering hosts wire the placeholder pair" bash -c \
    "grep -q placeholder <<<'${H_COVERED}'"
check "kube-only hosts keep the gh fallback for github.com" bash -c \
    "grep -q 'gh auth git-credential' <<<'${H_KUBE}'"
check "kube-only hosts wire no placeholder anywhere" bash -c \
    "! grep -q placeholder <<<'${H_KUBE_GIST}'"
check "a glob covering gist.github.com wires the pair (shared matcher semantics)" bash -c \
    "grep -q placeholder <<<'${H_GLOB}'"
# 5. gh coverage (#65) is decided independently, on api.github.com:443:
#    the default glob covers it; kube-only and a glob-less "github.com" do
#    not (git may still be wired — the proxy would never inject toward the
#    API host for that list, so a gh placeholder would only misfire).
gh_token_for() { # $1 = TJOR_BROKER_HOSTS value -> prints GH_TOKEN or 'unset'
    docker run --rm -e TJOR_BROKER_ENABLED=1 -e "TJOR_BROKER_HOSTS=$1" "${IMAGE}" \
        sh -c 'printf %s "${GH_TOKEN:-unset}"' 2>/dev/null || true
}
G_COVERED="$(gh_token_for 'github.com,*.github.com')"
G_KUBE="$(gh_token_for 'kubeapi.example.com')"
G_GITONLY="$(gh_token_for 'github.com')"
H_GITONLY="$(helper_for 'github.com' github.com)"
check "api-covering hosts export the gh placeholder" test "${G_COVERED}" = "tjor-broker-placeholder"
check "kube-only hosts leave GH_TOKEN unset" test "${G_KUBE}" = "unset"
check "github.com alone (no glob) leaves GH_TOKEN unset" test "${G_GITONLY}" = "unset"
check "github.com alone still wires the git placeholder (independent decisions)" bash -c \
    "grep -q placeholder <<<'${H_GITONLY}'"

echo
echo "broker: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
