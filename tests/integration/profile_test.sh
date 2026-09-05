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
mkdir -p "${SRC}/agent" "${SRC}/command"
printf 'You are a careful reviewer.\n' > "${SRC}/agent/reviewer.md"
printf 'deploy the app\n'             > "${SRC}/command/deploy.md"
printf '{"token":"%s"}\n' "${SECRET}" > "${SRC}/auth.json"           # MUST NOT leak
printf '{"apiKey":"%s"}\n' "${SECRET}" > "${SRC}/opencode.json"      # MUST NOT leak

# Stage host-side exactly as the launcher does.
STAGE="${WORK}/stage"
python3 "${ROOT}/python/tjor_profile.py" stage "${SRC}" "${STAGE}" >/dev/null

# The staged dir must already be credential-free (host-side guarantee).
if grep -rq "${SECRET}" "${STAGE}" 2>/dev/null; then bad "secret present in staged dir"; else ok "staging excluded credentials host-side"; fi

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
' 2>/dev/null)"

grep -q DEPLOYED <<<"${out}" && ok "profile agent + command deployed to harness config" || bad "profile definitions not deployed"
grep -q BASELINE <<<"${out}" && ok "baseline instruction cargo still present (overlay, not replace)" || bad "baseline cargo missing after overlay"
grep -q CONTENT  <<<"${out}" && ok "deployed agent has the profile's content" || bad "deployed agent content wrong"
grep -q LEAK     <<<"${out}" && bad "CREDENTIAL LEAK: secret reachable inside the container" || ok "no credential from the source is present in the container"

echo "----"
echo "profile deploy: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
