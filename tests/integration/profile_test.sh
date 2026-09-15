#!/usr/bin/env bash
# Agent-profile deploy (#29), end-to-end through the REAL entrypoint. Proves the
# whole guarantee: an opted-in profile's agent/command definitions reach the
# harness config dir, overlaid on the baseline instruction cargo, while a
# credential file sitting beside them in the source NEVER enters the container
# (the host-side allow-list stages only definitions; only the staged dir is
# mounted). No cluster/model needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="tjor-agent-opencode:local"
T="${TJOR_BIN:-${ROOT}/bin/tjor}"
SECRET="PROFILE-SECRET-$(date +%s 2>/dev/null || echo x)$$"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

command -v docker >/dev/null || { echo "SKIP: docker unavailable"; exit 0; }
docker image inspect "${IMAGE}" >/dev/null 2>&1 || "${T}" build --harness opencode >/dev/null 2>&1

# The staged dir is bind-mounted into the container, so it must live somewhere
# the docker VM shares (under $HOME on Colima/Docker Desktop) — mirroring the
# launcher, which stages into the session dir under ~/.tjor. A macOS `mktemp -d`
# lands in /var/folders, which the VM does NOT share (mount would be empty).
WORK="${HOME}/.tjor/tmp/profile-test-$$"
mkdir -p "${WORK}"
trap 'rm -rf "${WORK}"' EXIT

# A realistic profile source: definitions PLUS a credential file beside them
# (exactly the ~/.opencode shape that must not leak).
SRC="${WORK}/profile-src"
mkdir -p "${SRC}/agent" "${SRC}/command" "${SRC}/managed"
printf 'You are a careful reviewer.\n' > "${SRC}/agent/reviewer.md"
printf 'deploy the app\n'             > "${SRC}/command/deploy.md"
printf '{"token":"%s"}\n' "${SECRET}" > "${SRC}/auth.json"           # MUST NOT leak
printf '{"apiKey":"%s"}\n' "${SECRET}" > "${SRC}/opencode.json"      # MUST NOT leak
# Managed tier (#46): deployed root-owned to /etc/opencode, agent-immutable.
MMARK="tjor-managed-marker-$$"
printf '{"permission":{"bash":"ask"},"_marker":"%s"}\n' "${MMARK}" > "${SRC}/managed/opencode.json"

# Stage host-side exactly as the launcher does.
STAGE="${WORK}/stage"
python3 "${ROOT}/python/tjor_profile.py" stage "${SRC}" "${STAGE}" >/dev/null

# The staged dir must already be credential-free (host-side guarantee).
if grep -rq "${SECRET}" "${STAGE}" 2>/dev/null; then bad "secret present in staged dir"; else ok "staging excluded credentials host-side"; fi
[ -f "${STAGE}/managed/opencode.json" ] && ok "managed/opencode.json staged" || bad "managed/opencode.json not staged"

# Run the REAL entrypoint with the staged profile mounted read-only, as the
# launcher would, and inspect the resulting container state as the agent.
out="$(docker run --rm -e TJOR_HARNESS=opencode -e TJOR_PROFILE_DIR=/opt/tjor/profile \
        -v "${STAGE}:/opt/tjor/profile:ro" "${IMAGE}" bash -c '
    home=/home/agent
    a="$home/.config/opencode/agent/reviewer.md"
    c="$home/.config/opencode/command/deploy.md"
    base="$home/.config/opencode/AGENTS.md"
    [ -s "$a" ] && [ -s "$c" ] && echo "DEPLOYED"
    [ -s "$base" ] && echo "BASELINE"
    grep -q "careful reviewer" "$a" && echo "CONTENT"
    # the secret must be nowhere in the container filesystem the agent can read
    if grep -rIq "'"${SECRET}"'" "$home" /opt/tjor 2>/dev/null; then echo "LEAK"; fi
    # Managed tier (#46): root-owned, agent-immutable, out of the overlay.
    m=/etc/opencode/opencode.json
    [ -f "$m" ] && echo "MANAGED-PRESENT"
    grep -q "'"${MMARK}"'" "$m" 2>/dev/null && echo "MANAGED-CONTENT"
    [ "$(stat -c %u "$m" 2>/dev/null)" = 0 ] && echo "MANAGED-ROOT"
    (echo clobber > "$m") 2>/dev/null && echo "MANAGED-WRITABLE"
    rm -f "$m" 2>/dev/null
    [ -f "$m" ] && echo "MANAGED-IMMUTABLE"
    [ -e "$home/.config/opencode/managed" ] && echo "OVERLAY-LEAK"
    true  # the leak probes above are EXPECTED to fail; do not fail the run
' 2>/dev/null)"

grep -q DEPLOYED <<<"${out}" && ok "profile agent + command deployed to harness config" || bad "profile definitions not deployed"
grep -q BASELINE <<<"${out}" && ok "baseline instruction cargo still present (overlay, not replace)" || bad "baseline cargo missing after overlay"
grep -q CONTENT  <<<"${out}" && ok "deployed agent has the profile's content" || bad "deployed agent content wrong"
grep -q LEAK     <<<"${out}" && bad "CREDENTIAL LEAK: secret reachable inside the container" || ok "no credential from the source is present in the container"
grep -q MANAGED-PRESENT   <<<"${out}" && ok "managed opencode config deployed to /etc/opencode" || bad "managed config not deployed"
grep -q MANAGED-CONTENT   <<<"${out}" && ok "managed config carries the staged content" || bad "managed config content wrong"
grep -q MANAGED-ROOT      <<<"${out}" && ok "managed config is root-owned" || bad "managed config not root-owned"
grep -q MANAGED-WRITABLE  <<<"${out}" && bad "managed config is WRITABLE by the agent" || ok "agent cannot overwrite the managed config"
grep -q MANAGED-IMMUTABLE <<<"${out}" && ok "agent cannot remove the managed config" || bad "agent removed the managed config"
grep -q OVERLAY-LEAK      <<<"${out}" && bad "managed/ leaked into the harness config overlay" || ok "managed/ stays out of the harness config overlay"

# No profile staged: a stale managed file from an earlier start of the SAME
# container is removed (idempotent restarts; no-profile behavior unchanged).
out="$(docker run --rm --entrypoint bash -e TJOR_HARNESS=opencode "${IMAGE}" -c '
    mkdir -p /etc/opencode && echo "{\"stale\":true}" > /etc/opencode/opencode.json
    /usr/local/bin/tjor-entrypoint sh -c "[ -f /etc/opencode/opencode.json ] && echo STALE-KEPT || echo STALE-REMOVED"
' 2>/dev/null)"
grep -q STALE-REMOVED <<<"${out}" && ok "stale managed config removed when no profile stages one" || bad "stale managed config survived a no-profile start"

# Invalid managed JSON: the entrypoint refuses with the boundary exit code
# (90) and the harness never runs — never a silently unhardened session.
BADSTAGE="${WORK}/bad-stage"
mkdir -p "${BADSTAGE}/managed"
printf 'not json{' > "${BADSTAGE}/managed/opencode.json"
inv_code=0
docker run --rm -e TJOR_HARNESS=opencode -e TJOR_PROFILE_DIR=/opt/tjor/profile \
    -v "${BADSTAGE}:/opt/tjor/profile:ro" "${IMAGE}" sh -c 'echo SHOULD-NOT-RUN' \
    > "${WORK}/invalid.out" 2>&1 || inv_code=$?
[ "${inv_code}" -eq 90 ] && ok "invalid managed JSON aborts with the boundary exit code 90" || bad "invalid managed JSON exit code was ${inv_code}, expected 90"
grep -q SHOULD-NOT-RUN "${WORK}/invalid.out" && bad "harness ran despite invalid managed JSON" || ok "harness did not run with invalid managed JSON"
grep -q "not valid JSON" "${WORK}/invalid.out" && ok "invalid managed JSON error states the reason" || bad "invalid managed JSON error message missing"

# Launcher-side too: prepare_profile refuses the same profile up front, where
# the operator typed it — no container work happens.
LREPO="${WORK}/prof-inv-repo-$$"
mkdir -p "${LREPO}"
( cd "${LREPO}" && git init -q 2>/dev/null || true )
if ( cd "${LREPO}" && "${T}" run --detach --profile-dir "${BADSTAGE}" true > "${WORK}/launcher-invalid.out" 2>&1 ); then
    bad "launcher accepted a profile with invalid managed JSON"
    ( cd "${LREPO}" && "${T}" down >/dev/null 2>&1 )
else
    ok "launcher refuses a profile with invalid managed JSON"
fi
grep -q "not valid JSON" "${WORK}/launcher-invalid.out" && ok "launcher names the invalid managed file" || bad "launcher error message missing"
rm -rf "${HOME}/.tjor/sessions/prof-inv-repo-$$"* 2>/dev/null || true

echo "----"
echo "profile deploy: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
