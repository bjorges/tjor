#!/usr/bin/env bash
# uid-agnostic image test (add-prebuilt-images): the same agent image, run
# with different TJOR_AGENT_UID values, aligns the agent user to that uid and
# leaves its home writable — the guarantee that lets one published image serve
# any host user. No topology needed; runs the image directly.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
IMAGE="${TJOR_AGENT_IMAGE:-tjor-agent-opencode:local}"
BASE="${HOME}/.tjor/tmp/uidtest"
PASS=0; FAIL=0

# Build the image if it isn't present (CI jobs are isolated — nothing built
# it here). `tjor build` produces the default-uid, uid-agnostic image.
docker image inspect "${IMAGE}" >/dev/null 2>&1 || "${T}" build >/dev/null 2>&1
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() { rm -rf "${BASE}"; }
trap cleanup EXIT

for uid in 4242 5555; do
    home="${BASE}/${uid}/home"
    mkdir -p "${home}"
    out="$(docker run --rm -e TJOR_AGENT_UID="${uid}" -v "${home}:/home/agent" \
        "${IMAGE}" bash -c 'echo "uid=$(id -u)"; (touch "$HOME/wtest" && echo "home-writable") || echo "home-RO"' 2>/dev/null || true)"
    if grep -q "uid=${uid}" <<<"${out}"; then ok "agent runs as host uid ${uid}"; else bad "agent uid != ${uid} (got: $(grep uid= <<<"${out}"))"; fi
    if grep -q "home-writable" <<<"${out}"; then ok "home writable under uid ${uid}"; else bad "home not writable under uid ${uid}"; fi
done

# Default (no TJOR_AGENT_UID): the image's built-in non-root uid, still non-root.
out="$(docker run --rm "${IMAGE}" bash -c 'id -u' 2>/dev/null || true)"
if [[ "${out}" =~ ^[0-9]+$ ]] && [[ "${out}" != "0" ]]; then ok "default run is non-root (uid ${out})"; else bad "default run is not a clean non-root uid (got: ${out})"; fi

echo
echo "uid: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
