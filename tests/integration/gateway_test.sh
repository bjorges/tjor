#!/usr/bin/env bash
# LLM gateway (D4) launcher wiring, no docker. Sources bin/tjor for its
# functions (source-guard) and drives prepare_gateway + the policy augmentation
# ensure_topology performs, asserting the security-critical properties: the
# generated master key is 0600 and lives OUTSIDE the session dir (so it is never
# in a config hash), the LiteLLM config renders from [gateway].models with NO
# secret, provider keys land only in the egress-side env_file, and the session
# policy makes the gateway INFERENCE-ONLY (all admin paths denied). The real
# completion e2e (with a provider key) is a documented manual check.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# Isolate config + key file + secrets from the real environment.
USERCFG="${WORK}/xdg"; mkdir -p "${USERCFG}/tjor"
export XDG_CONFIG_HOME="${USERCFG}"
export TJOR_GATEWAY_KEY_FILE="${WORK}/gateway-master.key"
export FAKE_PROVIDER_KEY="provider-secret-DO-NOT-LEAK-$$"
cat >"${USERCFG}/tjor/config.toml" <<'TOML'
[gateway]
enabled = true
host = "tjor-gateway"
port = 4000
provider_key_envs = ["FAKE_PROVIDER_KEY"]
[[gateway.models]]
name = "gpt-4o"
model = "openai/gpt-4o"
api_key = "os.environ/FAKE_PROVIDER_KEY"
TOML

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

export TJOR_SESSION_DIR="${WORK}/session"; mkdir -p "${TJOR_SESSION_DIR}"
prepare_gateway

# --- master key: generated, 0600, and NOT inside the session dir --------------
[[ "${TJOR_GATEWAY_ENABLED:-}" == "1" ]] && ok "gateway enabled" || bad "gateway not enabled"
[[ "${TJOR_GATEWAY_KEY:-}" == sk-tjor-* ]] && ok "master key generated (sk-tjor-...)" || bad "master key wrong: ${TJOR_GATEWAY_KEY:-}"
perm="$(stat -c '%a' "${TJOR_GATEWAY_KEY_FILE}" 2>/dev/null || stat -f '%Lp' "${TJOR_GATEWAY_KEY_FILE}" 2>/dev/null)"
[[ "${perm}" == "600" ]] && ok "master key file is 0600" || bad "master key perms ${perm}"
case "${TJOR_GATEWAY_KEY_FILE}" in "${TJOR_SESSION_DIR}"/*) bad "master key stored INSIDE the session dir (would enter the config hash)";; *) ok "master key stored outside the session dir";; esac

# --- LiteLLM config: models rendered, NO secret literal -----------------------
cfgf="${TJOR_GATEWAY_CONFIG_MOUNT}"
grep -q '"model_name": "gpt-4o"' "${cfgf}" && ok "LiteLLM config renders the configured model" || bad "model missing from config"
grep -q 'os.environ/FAKE_PROVIDER_KEY' "${cfgf}" && ok "provider key referenced by env, not literal" || bad "provider key not an env ref"
grep -q "${FAKE_PROVIDER_KEY}" "${cfgf}" && bad "provider secret LEAKED into the rendered config" || ok "no provider secret in the rendered config"
grep -q "${TJOR_GATEWAY_KEY}" "${cfgf}" && bad "master key LEAKED into the rendered config" || ok "no master key in the rendered config"

# --- provider keys: only in the egress-side env_file, 0600 --------------------
envf="${TJOR_GATEWAY_ENV_MOUNT}"
eperm="$(stat -c '%a' "${envf}" 2>/dev/null || stat -f '%Lp' "${envf}" 2>/dev/null)"
[[ "${eperm}" == "600" ]] && ok "provider env_file is 0600" || bad "provider env_file perms ${eperm}"
grep -qx "FAKE_PROVIDER_KEY=${FAKE_PROVIDER_KEY}" "${envf}" && ok "provider key staged into the gateway env_file" || bad "provider key not staged"

# --- policy: the gateway is inference-ONLY (admin denied) ---------------------
# Reproduce ensure_topology's augmentation on the packaged default policy.
cp "${ROOT}/config/policy.toml" "${TJOR_SESSION_DIR}/policy.toml"
python3 "${ROOT}/python/tjor_gateway.py" augment-policy "${TJOR_SESSION_DIR}/policy.toml" "${TJOR_GATEWAY_HOST}" > "${TJOR_SESSION_DIR}/policy.aug"
mv "${TJOR_SESSION_DIR}/policy.aug" "${TJOR_SESSION_DIR}/policy.toml"
pol="${TJOR_SESSION_DIR}/policy.toml"
# Capture the verdict line (the CLI exits non-zero on DENY, which would trip
# `set -o pipefail` if we piped it) and match its leading ALLOW/DENY.
chk() { local out; out="$(python3 "${ROOT}/python/tjor_policy.py" check --policy "${pol}" "$1" 2>/dev/null || true)"; [[ "${out}" == "${2}"* ]]; }
chk "http://tjor-gateway:4000/v1/chat/completions" ALLOW && ok "inference path allowed to the gateway" || bad "inference path not allowed"
chk "http://tjor-gateway:4000/v1/messages" ALLOW && ok "anthropic inference path allowed" || bad "anthropic path not allowed"
chk "http://tjor-gateway:4000/key/generate" DENY && ok "admin /key/generate DENIED (unreachable by construction)" || bad "admin path was NOT denied"
chk "http://tjor-gateway:4000/ui" DENY && ok "admin /ui DENIED" || bad "/ui was not denied"
chk "https://api.anthropic.com/v1/messages" ALLOW && ok "base policy allow still honored" || bad "base allow broken"

echo "----"
echo "gateway wiring: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
