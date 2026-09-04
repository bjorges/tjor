#!/usr/bin/env bash
# tjor agent entrypoint. Runs as root for setup, then drops to the agent
# user. Instructions are image cargo (charter L16): re-deployed on EVERY
# start so they are versioned with the image, not with mutable user state.
set -euo pipefail

AGENT_HOME=/home/agent

# 1. Trust the session CA (the egress proxy re-signs all TLS).
if [[ -s /etc/tjor/ca/ca.pem ]]; then
    cp /etc/tjor/ca/ca.pem /usr/local/share/ca-certificates/tjor-session-ca.crt
    if ! update-ca-certificates >/dev/null 2>&1; then
        echo "tjor-entrypoint: WARNING: system CA install failed — TLS through the proxy will fail" >&2
    fi
else
    echo "tjor-entrypoint: WARNING: no session CA mounted — TLS through the proxy will fail" >&2
fi

# 2. Session home is a bind mount; make sure the skeleton exists.
install -d "${AGENT_HOME}/.config/opencode" "${AGENT_HOME}/.local/share" "${AGENT_HOME}/.local/state"

# 3. Deploy instruction cargo (overwrite; image is the source of truth).
if [[ -d /opt/tjor/instructions/opencode ]]; then
    cp -Rf /opt/tjor/instructions/opencode/. "${AGENT_HOME}/.config/opencode/"
fi

# 4. Harness self-update is an image concern, never a session one (charter
#    L13): merge autoupdate=false into opencode's config, keep user settings.
python3 - <<'PY'
import json, pathlib
path = pathlib.Path("/home/agent/.config/opencode/opencode.json")
try:
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
except Exception:
    data = {}
data["autoupdate"] = False
path.write_text(json.dumps(data, indent=2) + "\n")
PY

chown -R agent:agent "${AGENT_HOME}/.config/opencode" 2>/dev/null || true
chown agent:agent "${AGENT_HOME}" 2>/dev/null || true

# 5. Drop privileges and hand over.
exec gosu agent env HOME="${AGENT_HOME}" USER=agent "$@"
