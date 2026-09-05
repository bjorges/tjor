#!/usr/bin/env bash
# Kube placeholder-config symlink-follow regression (#26 hardening). A prior
# session (agent-level access, no root) could plant ~/.kube/config.tmp as a
# symlink; the entrypoint renders the placeholder kubeconfig via a root redirect
# through that .tmp, so without de-symlinking it first the write would follow
# the link and clobber whatever it targets. Assert: a planted config.tmp symlink
# is NOT followed — its target is left intact and the real config is the
# placeholder. Runs the REAL entrypoint; no cluster needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="tjor-agent-opencode:local"
T="${TJOR_BIN:-${ROOT}/bin/tjor}"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

command -v docker >/dev/null || { echo "SKIP: docker unavailable"; exit 0; }
docker image inspect "${IMAGE}" >/dev/null 2>&1 || "${T}" build --harness opencode >/dev/null 2>&1

# Prepared home under $HOME so the docker VM shares it (see profile_test.sh).
WORK="${HOME}/.tjor/tmp/kube-symlink-$$"
HOMEDIR="${WORK}/home"
mkdir -p "${HOMEDIR}/.kube"
trap 'rm -rf "${WORK}"' EXIT

SENTINEL_CONTENT="PROTECTED-DO-NOT-CLOBBER-$$"
printf '%s\n' "${SENTINEL_CONTENT}" > "${HOMEDIR}/sentinel"
# Plant the hostile symlink: ~/.kube/config.tmp -> ~/sentinel (container path).
ln -s /home/agent/sentinel "${HOMEDIR}/.kube/config.tmp"

# Run the real entrypoint with the kube broker "active" (server set) so it
# renders the placeholder kubeconfig, writing through .tmp. TJOR_AGENT_UID is
# the host uid (as the real launcher passes), so the entrypoint aligns the agent
# to it — the files it writes stay host-owned, readable here and removable in
# cleanup (without it, native-Linux CI writes 0600 files as a foreign uid that
# the runner can neither read nor rm).
docker run --rm \
    -e TJOR_HARNESS=opencode \
    -e TJOR_BROKER_ENABLED=1 \
    -e TJOR_KUBE_SERVER=https://api.test.example:6443 \
    -e TJOR_AGENT_UID="$(id -u)" \
    -v "${HOMEDIR}:/home/agent" \
    "${IMAGE}" true >/dev/null 2>&1 || true

got="$(cat "${HOMEDIR}/sentinel" 2>/dev/null || true)"
if [[ "${got}" == "${SENTINEL_CONTENT}" ]]; then
    ok "planted config.tmp symlink was NOT followed (sentinel intact)"
else
    bad "sentinel was clobbered through the symlink (got: ${got})"
fi
# And the placeholder was still rendered to the real config.
if grep -q 'tjor-broker-placeholder' "${HOMEDIR}/.kube/config" 2>/dev/null; then
    ok "placeholder kubeconfig rendered to ~/.kube/config"
else
    bad "placeholder kubeconfig not rendered"
fi
# config.tmp must not linger as a symlink.
[[ -L "${HOMEDIR}/.kube/config.tmp" ]] && bad "config.tmp still a symlink after run" || ok "no lingering config.tmp symlink"

echo "----"
echo "kube symlink: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
