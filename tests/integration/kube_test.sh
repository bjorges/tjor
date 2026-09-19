#!/usr/bin/env bash
# Kube credential-broker wiring (#26 single-cluster, #57 multi-cluster), no
# cluster required. Sources bin/tjor for its functions (source-guard) and
# drives prepare_broker with a MOCKED kubectl, asserting: SA tokens are minted
# per cluster and land in a v2 (source=kube) broker.json; injection is scoped
# to each cluster's exact API origin; the agent gets the server URLs (for its
# multi-context placeholder kubeconfig) but never a token; and every
# fail-closed branch DISABLES the broker rather than downgrading. The real
# proxy injection is exercised by the addon unit suite; a live cluster e2e
# (RBAC denies a write) is a documented manual check.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# --- mock kubectl: per-context server for `config view [--context <ctx>]`, a
#     per-context token for `create token`; APPENDS each create-token argv so a
#     test can assert how many mints ran and against which contexts. Special
#     contexts: 'badctx' has no readable server; 'failmint' fails to mint;
#     'prodalias' resolves to prod's server (duplicate-origin case).
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
MINTED_TOKEN="MOCK-SA-TOKEN-abc123"
SERVER_URL="https://api.test.example:6443"
cat >"${MOCKBIN}/kubectl" <<EOF
#!/usr/bin/env bash
args=("\$@"); ctx=""
for ((i=0; i<\${#args[@]}; i++)); do [[ "\${args[i]}" == "--context" ]] && ctx="\${args[i+1]}"; done
case " \$* " in
    *" config view "*)
        [[ -n "\${MOCK_NO_CONFIG_VIEW:-}" ]] && exit 1
        case "\${ctx}" in
            prod)      printf '%s' "https://api.prod.example:6443" ;;
            staging)   printf '%s' "https://api.staging.example:6443" ;;
            prodalias) printf '%s' "https://api.prod.example:6443" ;;  # same origin as prod
            failmint)  printf '%s' "https://api.failmint.example:6443" ;;
            badctx)    exit 1 ;;
            "")        printf '%s' "${SERVER_URL}" ;;
            *)         printf '%s' "https://api.\${ctx}.example:6443" ;;
        esac ;;
    *" create token "*)
        printf '%s\n' "\$*" >> "${WORK}/create_token_argv"
        [[ "\${ctx}" == failmint ]] && exit 1
        case "\${ctx}" in
            "") printf '%s' "${MINTED_TOKEN}" ;;
            *)  printf '%s' "MOCK-TOKEN-\${ctx}" ;;
        esac ;;
    *) echo "mock kubectl: unhandled: \$*" >&2; exit 2 ;;
esac
EOF
chmod +x "${MOCKBIN}/kubectl"

# broker.json v2 assertions live in python (source=kube, per-origin tokens).
bjson_has_cluster() { # $1 broker.json, $2 origin, $3 token
    python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
if d.get("source")!="kube": sys.exit(1)
for c in d.get("clusters",[]):
    if c.get("origin")==sys.argv[2] and c.get("token")==sys.argv[3]: sys.exit(0)
sys.exit(1)' "$1" "$2" "$3"
}
bjson_cluster_count() { # $1 broker.json -> prints count
    python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("clusters",[])))' "$1"
}

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

# === 1. Back-compat: flat single-cluster config (#26, now Bearer/#57) =====
# The flat form still works — one cluster minted against the ACTIVE context —
# now producing the v2 (source=kube) broker.json and the plural env vars.
write_user_cfg <<'TOML'
[broker]
source = "kube"
kube_sa = "ci-runner"
kube_namespace = "builds"
kube_duration = "30m"
TOML
rm -f "${WORK}/create_token_argv"
PATH="${MOCKBIN}:${PATH}" run_prepare

[[ "${TJOR_BROKER_ENABLED:-}" == "1" ]] && ok "flat single-cluster broker enabled (back-compat)" || bad "flat kube broker not enabled"
[[ "${TJOR_BROKER_HOSTS:-}" == "api.test.example:6443" ]] && ok "injection scoped to the exact API origin (host:port, #49)" || bad "TJOR_BROKER_HOSTS='${TJOR_BROKER_HOSTS:-}' != api.test.example:6443"
[[ "${TJOR_KUBE_SERVERS:-}" == "${SERVER_URL}" ]] && ok "agent gets the API server URL (plural env)" || bad "TJOR_KUBE_SERVERS='${TJOR_KUBE_SERVERS:-}'"
[[ "${TJOR_KUBE_CONTEXTS:-}" == "tjor" ]] && ok "flat entry named context 'tjor' (unchanged)" || bad "TJOR_KUBE_CONTEXTS='${TJOR_KUBE_CONTEXTS:-}' != tjor"
[[ "${TJOR_KUBE_API_HOSTS:-}" == "api.test.example" ]] && ok "proxy gets the API host for the scoped ip_guard exemption (#45)" || bad "TJOR_KUBE_API_HOSTS='${TJOR_KUBE_API_HOSTS:-}' != api.test.example"

# The minted token lands in a v2 (source=kube) broker.json, keyed by origin.
BJSON="${TJOR_BROKER_CONFIG_MOUNT}"
if bjson_has_cluster "${BJSON}" "api.test.example:6443" "${MINTED_TOKEN}"; then
    ok "minted token stored in v2 (source=kube) broker.json keyed by origin"
else
    bad "broker.json is not the v2 kube shape with the minted token"
fi
# ...and the create-token command must carry the configured SA/ns/duration
# (flat entry mints against the active context — NO --context).
argv="$(cat "${WORK}/create_token_argv")"
[[ "${argv}" == *"create token ci-runner"* && "${argv}" == *"--namespace builds"* && "${argv}" == *"--duration 30m"* ]] \
    && ok "mint command construction (SA + namespace + duration)" || bad "create token argv wrong: ${argv}"
[[ "${argv}" != *"--context"* ]] && ok "flat entry mints against the active context (no --context)" || bad "flat entry unexpectedly passed --context: ${argv}"

# broker.json is 0600 (secret never world-readable). GNU stat: `-c %a`; BSD
# (macOS) stat: `-f %Lp`. Try GNU first — on Linux `stat -f` means FILESYSTEM
# info and would succeed with the wrong output, never reaching a BSD fallback.
perm="$(stat -c '%a' "${BJSON}" 2>/dev/null || stat -f '%Lp' "${BJSON}" 2>/dev/null)"
[[ "${perm}" == "600" ]] && ok "broker.json is 0600" || bad "broker.json perms ${perm} != 600"

# The multi-context placeholder kubeconfig the entrypoint would render carries
# NO real token — even in the one-context flat case.
KCFG="$(python3 "${ROOT}/python/tjor_kube.py" multiconfig /etc/ssl/certs/ca-certificates.crt "${TJOR_KUBE_CONTEXTS}" "${TJOR_KUBE_SERVERS}")"
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
[[ "${TJOR_BROKER_HOSTS:-}" == "api.test.example:6443" && "${TJOR_KUBE_SERVERS:-}" == "${SERVER_URL}" ]] \
    && ok "override honored: injection scoped to the exact origin, unchanged from the happy path" || bad "override wiring wrong (hosts='${TJOR_BROKER_HOSTS:-}', servers='${TJOR_KUBE_SERVERS:-}')"

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
[[ -z "${TJOR_KUBE_API_HOSTS:-}" ]] && ok "no ip_guard exemption exported on mismatch (#45)" || bad "TJOR_KUBE_API_HOSTS leaked on mismatch: '${TJOR_KUBE_API_HOSTS:-}'"
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
[[ -z "${TJOR_KUBE_API_HOSTS:-}" ]] && ok "no kube broker -> no ip_guard exemption host exported (#45)" || bad "TJOR_KUBE_API_HOSTS leaked without an active kube broker: '${TJOR_KUBE_API_HOSTS:-}'"

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

# === 9. Multi-cluster happy path (#57): two clusters, per-context mint ======
write_user_cfg <<'TOML'
[broker]
source = "kube"

[[broker.kube_clusters]]
context = "prod"
kube_sa = "ci-runner"

[[broker.kube_clusters]]
context = "staging"
kube_sa = "ci-runner"
kube_namespace = "builds"
TOML
rm -f "${WORK}/create_token_argv"
PATH="${MOCKBIN}:${PATH}" run_prepare 2>"${WORK}/multi_out"
[[ "${TJOR_BROKER_ENABLED:-}" == "1" ]] && ok "multi-cluster broker enabled (#57)" || bad "multi-cluster broker not enabled"
[[ "$(bjson_cluster_count "${TJOR_BROKER_CONFIG_MOUNT}")" == "2" ]] && ok "broker.json holds two clusters" || bad "broker.json cluster count != 2"
bjson_has_cluster "${TJOR_BROKER_CONFIG_MOUNT}" "api.prod.example:6443" "MOCK-TOKEN-prod" \
    && ok "prod cluster: token minted against its own context, keyed by its origin" || bad "prod cluster missing/mismatched in broker.json"
bjson_has_cluster "${TJOR_BROKER_CONFIG_MOUNT}" "api.staging.example:6443" "MOCK-TOKEN-staging" \
    && ok "staging cluster: token minted against its own context, keyed by its origin" || bad "staging cluster missing/mismatched in broker.json"
# cross-cluster isolation at the broker.json level: prod's origin never carries staging's token
if bjson_has_cluster "${TJOR_BROKER_CONFIG_MOUNT}" "api.prod.example:6443" "MOCK-TOKEN-staging"; then
    bad "cross-cluster leak: prod origin carries staging's token"
else ok "cross-cluster isolation in broker.json (prod origin != staging token)"; fi
[[ "${TJOR_BROKER_HOSTS:-}" == "api.prod.example:6443,api.staging.example:6443" ]] && ok "TJOR_BROKER_HOSTS lists both origins" || bad "TJOR_BROKER_HOSTS='${TJOR_BROKER_HOSTS:-}'"
[[ "${TJOR_KUBE_API_HOSTS:-}" == "api.prod.example,api.staging.example" ]] && ok "TJOR_KUBE_API_HOSTS lists both cluster hosts (#45 per-cluster)" || bad "TJOR_KUBE_API_HOSTS='${TJOR_KUBE_API_HOSTS:-}'"
[[ "${TJOR_KUBE_CONTEXTS:-}" == "prod,staging" ]] && ok "TJOR_KUBE_CONTEXTS lists both contexts" || bad "TJOR_KUBE_CONTEXTS='${TJOR_KUBE_CONTEXTS:-}'"
# each mint carried its own --context
argv="$(cat "${WORK}/create_token_argv")"
[[ "${argv}" == *"--context prod"* && "${argv}" == *"--context staging"* ]] \
    && ok "each cluster minted against its own --context" || bad "per-context mint argv wrong: ${argv}"
[[ "$(grep -c 'create token' "${WORK}/create_token_argv")" == "2" ]] && ok "exactly two mints ran" || bad "expected 2 mints, got $(grep -c 'create token' "${WORK}/create_token_argv")"
[[ "$(grep -c 'tjor policy add' "${WORK}/multi_out")" == "2" ]] && ok "one 'tjor policy add' hint printed per cluster" || bad "expected 2 policy hints"
# the rendered multi-context kubeconfig has both contexts and no real token
KCFG="$(python3 "${ROOT}/python/tjor_kube.py" multiconfig /ca.pem prod https://api.prod.example:6443 staging https://api.staging.example:6443)"
grep -q '"prod"' <<<"${KCFG}" && grep -q '"staging"' <<<"${KCFG}" && ok "multi-context kubeconfig names both clusters" || bad "kubeconfig missing a context"
grep -q "MOCK-TOKEN" <<<"${KCFG}" && bad "kubeconfig leaked a real token" || ok "multi-context kubeconfig holds no real token"

# === 10. Fail-closed: one cluster's api_host pin mismatches (#58, per entry) =
# Validation is all-before-any-mint, so a bad pin on ANY entry means NO mint.
write_user_cfg <<'TOML'
[broker]
source = "kube"

[[broker.kube_clusters]]
context = "prod"
kube_sa = "ci-runner"

[[broker.kube_clusters]]
context = "staging"
kube_sa = "ci-runner"
api_host = "https://wrong.example:6443"
TOML
rm -f "${WORK}/create_token_argv"
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: a mismatched per-cluster pin disables the whole broker (#58)" || bad "mismatched per-cluster pin did NOT disable the broker"
[[ ! -e "${WORK}/create_token_argv" ]] && ok "no token minted for ANY cluster (validate-all-before-mint)" || bad "a token was minted despite a bad pin"

# === 11. All-or-nothing: one cluster's mint fails (#57) =====================
write_user_cfg <<'TOML'
[broker]
source = "kube"

[[broker.kube_clusters]]
context = "prod"
kube_sa = "ci-runner"

[[broker.kube_clusters]]
context = "failmint"
kube_sa = "ci-runner"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "all-or-nothing: one failed mint disables the whole broker" || bad "partial multi-cluster provisioning was allowed"
[[ -z "${TJOR_BROKER_CONFIG_MOUNT:-}" ]] && ok "no broker.json exported on partial failure" || bad "broker.json exported despite a failed mint"

# === 12. Refused: two clusters resolve to the same origin (#49/#57) =========
write_user_cfg <<'TOML'
[broker]
source = "kube"

[[broker.kube_clusters]]
context = "prod"
kube_sa = "ci-runner"

[[broker.kube_clusters]]
context = "prodalias"
kube_sa = "ci-runner"
TOML
rm -f "${WORK}/create_token_argv"
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "duplicate API origin refused (an origin cannot carry two tokens)" || bad "duplicate origin was accepted"
[[ ! -e "${WORK}/create_token_argv" ]] && ok "no token minted when a duplicate origin is detected (validate-first)" || bad "a token was minted before the duplicate-origin refusal"

# === 13. Fail-closed: a list entry with an unknown key aborts (security table) =
write_user_cfg <<'TOML'
[broker]
source = "kube"

[[broker.kube_clusters]]
context = "prod"
kube_sa = "ci-runner"
kube_ns = "typo"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: unknown per-cluster key aborts (no silent mis-scope)" || bad "unknown per-cluster key was accepted"

# === 14. Fail-closed: a list entry missing 'context' =======================
write_user_cfg <<'TOML'
[broker]
source = "kube"

[[broker.kube_clusters]]
kube_sa = "ci-runner"
TOML
PATH="${MOCKBIN}:${PATH}" run_prepare 2>/dev/null
[[ -z "${TJOR_BROKER_ENABLED:-}" ]] && ok "fail-closed: a list entry without 'context' is refused" || bad "list entry without context was accepted"

echo "----"
echo "kube wiring: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
