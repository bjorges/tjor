#!/usr/bin/env bash
# Kube credential-broker wiring (#26), no cluster required. Sources bin/tjor
# for its functions (source-guard) and drives prepare_broker with a MOCKED
# kubectl, asserting: the SA token is minted and lands in a pat-shaped
# broker.json; injection is scoped to the derived API host; the agent gets the
# server URL (for its placeholder kubeconfig) but never the token; and every
# fail-closed branch DISABLES the broker rather than downgrading. The real
# proxy injection is the D2 pat path (already conformance-tested); a live
# cluster e2e (RBAC denies a write) is a documented manual check.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# --- mock kubectl: server URL for `config view`, a fixed token for `create
#     token`; records the create-token argv so we can assert the command shape.
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
MINTED_TOKEN="MOCK-SA-TOKEN-abc123"
SERVER_URL="https://api.test.example:6443"
cat >"${MOCKBIN}/kubectl" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do :; done
case " \$* " in
    *" config view "*) [[ -n "\${MOCK_NO_CONFIG_VIEW:-}" ]] && exit 1; printf '%s' "${SERVER_URL}" ;;
    *" create token "*) printf '%s' "\$*" > "${WORK}/create_token_argv"; printf '%s' "${MINTED_TOKEN}" ;;
    *) echo "mock kubectl: unhandled: \$*" >&2; exit 2 ;;
esac
EOF
chmod +x "${MOCKBIN}/kubectl"

# Isolate config: a user config selects the kube source.
USERCFG="${WORK}/xdg"; mkdir -p "${USERCFG}/tjor"
write_user_cfg() { cat >"${USERCFG}/tjor/config.toml"; }
export XDG_CONFIG_HOME="${USERCFG}"

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

run_prepare() { # runs prepare_broker in a subshell-safe way, capturing exports
    export TJOR_SESSION_DIR="${WORK}/session"; rm -rf "${TJOR_SESSION_DIR}"; mkdir -p "${TJOR_SESSION_DIR}"
    prepare_broker
}

# === 1. Happy path: mint + scope + placeholder-only agent =================
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "ci-runner"
kube_namespace = "builds"
kube_duration = "30m"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare

[[ "${TJOR_BROKER_ENABLED:-}" == "1" ]] && ok "kube broker enabled on happy path" || bad "kube broker not enabled"
[[ "${TJOR_BROKER_HOSTS:-}" == "api.test.example:6443" ]] && ok "injection scoped to the exact API origin (host:port, #49)" || bad "TJOR_BROKER_HOSTS='${TJOR_BROKER_HOSTS:-}' != api.test.example:6443"
[[ "${TJOR_KUBE_SERVER:-}" == "${SERVER_URL}" ]] && ok "agent gets API server URL for placeholder kubeconfig" || bad "TJOR_KUBE_SERVER='${TJOR_KUBE_SERVER:-}'"
[[ "${TJOR_KUBE_API_HOST:-}" == "api.test.example" ]] && ok "proxy gets the API host for the scoped ip_guard exemption (#45)" || bad "TJOR_KUBE_API_HOST='${TJOR_KUBE_API_HOST:-}' != api.test.example"

# The minted token must be in the proxy-only broker.json, pat-shaped...
BJSON="${TJOR_BROKER_CONFIG_MOUNT}"
if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get("source")=="pat" and d.get("token")==sys.argv[2] else 1)' "${BJSON}" "${MINTED_TOKEN}"; then
    ok "minted token stored pat-shaped in proxy-only broker.json"
else
    bad "broker.json is not the minted pat token"
fi
# ...and the create-token command must carry the configured SA/ns/duration.
argv="$(cat "${WORK}/create_token_argv")"
[[ "${argv}" == *"create token ci-runner"* && "${argv}" == *"--namespace builds"* && "${argv}" == *"--duration 30m"* ]] \
    && ok "mint command construction (SA + namespace + duration)" || bad "create token argv wrong: ${argv}"

# broker.json is 0600 (secret never world-readable). GNU stat: `-c %a`; BSD
# (macOS) stat: `-f %Lp`. Try GNU first — on Linux `stat -f` means FILESYSTEM
# info and would succeed with the wrong output, never reaching a BSD fallback.
perm="$(stat -c '%a' "${BJSON}" 2>/dev/null || stat -f '%Lp' "${BJSON}" 2>/dev/null)"
[[ "${perm}" == "600" ]] && ok "broker.json is 0600" || bad "broker.json perms ${perm} != 600"

# The placeholder kubeconfig the entrypoint would render carries NO token.
KCFG="$(python3 "${ROOT}/python/tjor_kube.py" config "${TJOR_KUBE_SERVER}" /etc/ssl/certs/ca-certificates.crt)"
if grep -q "${MINTED_TOKEN}" <<<"${KCFG}"; then bad "placeholder kubeconfig leaked the real token"; else ok "placeholder kubeconfig holds no real token"; fi
grep -q 'tjor-broker-placeholder' <<<"${KCFG}" && ok "placeholder kubeconfig carries the placeholder token" || bad "placeholder token missing"

# === 2. API host override pinning the active cluster (#58) ================
# The override is a validated PIN: an equivalent spelling of the active
# context's server (bare host:port vs the kubeconfig's full https URL) must
# validate as the same server and behave exactly like the happy path.
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "ci-runner"
kube_api_host = "api.test.example:6443"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare
[[ "${TJOR_BROKER_ENABLED:-}" == "1" ]] && ok "equivalent-spelling kube_api_host validates as the same server (#58)" || bad "equivalent-spelling override disabled the broker"
[[ "${TJOR_BROKER_HOSTS:-}" == "api.test.example:6443" && "${TJOR_KUBE_SERVER:-}" == "${SERVER_URL}" ]] \
    && ok "override honored: injection scoped to the exact origin, unchanged from the happy path" || bad "override wiring wrong (hosts='${TJOR_BROKER_HOSTS:-}', server='${TJOR_KUBE_SERVER:-}')"

# === 3. Fail-closed: kube_api_host names a DIFFERENT cluster (#58) =========
# The token is always minted against the ACTIVE context, so a mismatching
# override must disable the broker BEFORE minting — no token for the wrong
# cluster may ever be requested — and the warning must name both servers.
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "ci-runner"
kube_api_host = "https://pinned.example.com:6443"
TOML
rm -f "${WORK}/create_token_argv"
PATH="${MOCKBIN}:${PATH}" run_prepare 2>"${WORK}/mismatch_warn"
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: mismatched kube_api_host disables the broker (#58)" || bad "mismatched kube_api_host did NOT disable the broker"
[[ ! -e "${WORK}/create_token_argv" ]] && ok "no token minted for the wrong cluster" || bad "a token was minted despite the mismatch"
[[ -z "${TJOR_KUBE_API_HOST:-}" ]] && ok "no ip_guard exemption exported on mismatch (#45)" || bad "TJOR_KUBE_API_HOST leaked on mismatch: '${TJOR_KUBE_API_HOST:-}'"
if grep -q "pinned.example.com" "${WORK}/mismatch_warn" && grep -q "api.test.example" "${WORK}/mismatch_warn"; then
    ok "mismatch warning names both the override and the active context's server"
else
    bad "mismatch warning does not name both servers: $(cat "${WORK}/mismatch_warn")"
fi

# === 4. Fail-closed: kube_api_host set but active context unreadable (#58) =
# With the override set and `kubectl config view` failing, the pin cannot be
# validated against the cluster the token would be minted for — fail closed.
rm -f "${WORK}/create_token_argv"
MOCK_NO_CONFIG_VIEW=1 PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: unvalidatable kube_api_host disables the broker (#58)" || bad "unvalidatable kube_api_host did NOT disable the broker"
[[ ! -e "${WORK}/create_token_argv" ]] && ok "no token minted when the pin cannot be validated" || bad "a token was minted with an unvalidated pin"

# === 5. Fail-closed: empty kube_sa ========================================
write_user_cfg <<'TOML'
[broker]
source = "kube"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: empty kube_sa disables the broker" || bad "empty kube_sa did NOT disable the broker"
[[ -z "${TJOR_KUBE_API_HOST:-}" ]] && ok "no kube broker -> no ip_guard exemption host exported (#45)" || bad "TJOR_KUBE_API_HOST leaked without an active kube broker: '${TJOR_KUBE_API_HOST:-}'"

# === 6. Fail-closed: kubectl absent =======================================
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "ci-runner"
TOML
# note: do NOT put MOCKBIN on PATH; ensure no real kubectl either
PATH="${WORK}/empty" run_prepare 2>/dev/null || true
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: missing kubectl disables the broker" || bad "missing kubectl did NOT disable the broker"

# === 7. Fail-closed: argument-injection-shaped kube_sa (leading dash) =====
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "-oh-no"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null || true
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: flag-shaped kube_sa (leading '-') refused" || bad "flag-shaped kube_sa was accepted (arg injection)"

# === 8. Fail-closed: bogus kube_duration ==================================
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "ci-runner"
kube_duration = "; rm -rf /"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null || true
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: non-duration kube_duration refused" || bad "bogus kube_duration was accepted"

echo "----"
echo "kube wiring: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
