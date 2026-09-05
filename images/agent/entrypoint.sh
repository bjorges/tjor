#!/usr/bin/env bash
# tjor agent entrypoint. Runs as root for setup, then drops to the agent
# user. Instructions are image cargo (charter L16): re-deployed on EVERY
# start so they are versioned with the image, not with mutable user state.
set -euo pipefail

AGENT_HOME=/home/agent

# 1. Trust the session CA (the egress proxy re-signs all TLS). Append it
#    directly to the system bundle that git/curl read — instant, and avoids
#    update-ca-certificates, whose per-cert rehashing is pathologically slow
#    under a VM runtime and stalled session startup. Node reads the CA via
#    NODE_EXTRA_CA_CERTS (set in the image), independent of the bundle.
CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
if [[ -s /etc/tjor/ca/ca.pem ]]; then
    cp /etc/tjor/ca/ca.pem /usr/local/share/ca-certificates/tjor-session-ca.crt
    # Idempotent via a unique marker — do NOT grep the PEM itself, whose
    # boilerplate lines (-----BEGIN CERTIFICATE-----) match every cert in the
    # bundle and would make it look already-present.
    if ! grep -q '# tjor session CA' "${CA_BUNDLE}" 2>/dev/null; then
        printf '\n# tjor session CA\n' >> "${CA_BUNDLE}"
        cat /etc/tjor/ca/ca.pem >> "${CA_BUNDLE}"
    fi
else
    echo "tjor-entrypoint: WARNING: no session CA mounted — TLS through the proxy will fail" >&2
fi

# 2. Deploy instruction cargo and enforce autoupdate=false — symlink-safe
#    (charter L26): the home dir is agent-writable and persists across
#    sessions, so a previous session could have planted symlinks to redirect
#    these root-privileged writes. Every touched component is checked and
#    de-symlinked before any write. No agent process runs concurrently with
#    this (the harness starts only at the exec below), so a point-in-time
#    sweep is race-free.
python3 - <<'PY'
import json
import pathlib
import shutil

HOME = pathlib.Path("/home/agent")
CARGO = pathlib.Path("/opt/tjor/instructions/opencode")
CFG = HOME / ".config" / "opencode"


def desymlink(path: pathlib.Path) -> None:
    """Remove a symlink (or non-dir obstruction) at any component of path
    below HOME, then ensure path exists as a real directory."""
    parts = [p for p in [*reversed(path.parents), path] if HOME in p.parents or p == HOME]
    for p in parts:
        if p == HOME:
            continue
        if p.is_symlink() or (p.exists() and not p.is_dir()):
            p.unlink()
    path.mkdir(parents=True, exist_ok=True)


def safe_write_target(path: pathlib.Path) -> pathlib.Path:
    # Remove symlinks AND any non-regular-file obstruction (FIFO, socket,
    # directory) an earlier session may have planted where we write.
    if path.is_symlink() or (path.exists() and not path.is_file()):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return path


desymlink(CFG)
desymlink(HOME / ".local" / "share")
desymlink(HOME / ".local" / "state")

if CARGO.is_dir():
    for src in sorted(CARGO.rglob("*")):
        dst = CFG / src.relative_to(CARGO)
        if src.is_dir():
            desymlink(dst)
        else:
            shutil.copyfile(src, safe_write_target(dst))

# Harness self-update is an image concern, never a session one (charter L13):
# merge autoupdate=false into opencode's config, keep other user settings.
cfgfile = safe_write_target(CFG / "opencode.json")
try:
    data = json.loads(cfgfile.read_text()) if cfgfile.exists() else {}
    if not isinstance(data, dict):
        data = {}
except Exception:
    data = {}
data["autoupdate"] = False
cfgfile.write_text(json.dumps(data, indent=2) + "\n")
PY

# 3. Git transport: SSH egress is structurally blocked (only proxied
#    HTTP(S) leaves the cage), so rewrite SSH remotes to HTTPS system-wide.
#    Anonymous pulls of public repos work immediately; private repos and
#    pushes need a one-time in-session `gh auth login` + `gh auth setup-git`
#    (persisted in the session home). D2 will replace this with brokered,
#    short-TTL credentials.
# Idempotent across container restarts (/etc/gitconfig persists between
# them): clear the keys first, or every restart appends duplicate values.
git config --system --unset-all url."https://github.com/".insteadOf 2>/dev/null || true
git config --system --unset-all url."https://gitlab.com/".insteadOf 2>/dev/null || true
git config --system --add url."https://github.com/".insteadOf "git@github.com:"
git config --system --add url."https://github.com/".insteadOf "ssh://git@github.com/"
git config --system --add url."https://gitlab.com/".insteadOf "git@gitlab.com:"
git config --system --add url."https://gitlab.com/".insteadOf "ssh://git@gitlab.com/"
# Trust every bind-mounted repo regardless of the uid git runs as: git's
# dubious-ownership check guards shared multi-user hosts, but the cage is a
# single-user isolated environment working on the user's own mounted repos
# (and with runtime-uid-aligned images the owner uid may differ from git's).
git config --system --unset-all safe.directory 2>/dev/null || true
git config --system --add safe.directory '*'
if [[ -n "${TJOR_BROKER_ENABLED:-}" ]]; then
    # Credential broker (D2): git must ATTEMPT auth so the proxy can inject
    # the real, short-TTL credential. Wire a helper that returns a fixed
    # PLACEHOLDER (never a real secret) — the proxy overwrites the
    # Authorization header toward the broker's destination hosts. Overrides
    # any gh helper so no real token is ever sourced inside the cage.
    git config --system credential."https://github.com".helper \
        '!f() { echo username=x-access-token; echo password=tjor-broker-placeholder; }; f'
    git config --system credential."https://gist.github.com".helper \
        '!f() { echo username=x-access-token; echo password=tjor-broker-placeholder; }; f'
else
    # Pre-wire gh as git's credential helper: after a one-time in-session
    # `gh auth login`, git push/pull to private GitHub repos just works.
    git config --system credential."https://github.com".helper '!gh auth git-credential'
    git config --system credential."https://gist.github.com".helper '!gh auth git-credential'
fi

# 4. Ownership + writability. The setup above runs as root and creates XDG
#    dirs (.config, .local/share, .local/state) root-owned; chown them to the
#    agent uid (= the host user) so the session state stays host-manageable
#    (e.g. `tjor reset`) on a native-Linux engine — on a uid-mapping VM
#    (Colima virtiofs) chown can legitimately fail, so warn, then hard-verify
#    the invariant that actually matters: the agent user can write its home.
for d in "${AGENT_HOME}/.config" "${AGENT_HOME}/.local"; do
    if [[ -d "${d}" ]] && ! chown -R agent:agent "${d}" 2>/dev/null; then
        echo "tjor-entrypoint: WARNING: chown of ${d} failed (uid-mapped mount?)" >&2
    fi
done
if ! chown agent:agent "${AGENT_HOME}" 2>/dev/null; then
    echo "tjor-entrypoint: WARNING: chown of ${AGENT_HOME} failed (uid-mapped mount?)" >&2
fi
if ! gosu agent test -w "${AGENT_HOME}"; then
    echo "tjor-entrypoint: ERROR: ${AGENT_HOME} is not writable by the agent user — refusing to start." >&2
    echo "                 Rebuild with --harness matching your host uid (tjor passes AGENT_UID automatically)." >&2
    exit 1
fi

# 5. Drop privileges and hand over.
exec gosu agent env HOME="${AGENT_HOME}" USER=agent "$@"
