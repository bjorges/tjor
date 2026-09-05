#!/usr/bin/env bash
# tjor agent entrypoint. Runs as root for setup, then drops to the agent
# user. Instructions are image cargo (charter L16): re-deployed on EVERY
# start so they are versioned with the image, not with mutable user state.
set -euo pipefail

AGENT_HOME=/home/agent

# 0. Runtime uid alignment — makes the image uid-AGNOSTIC so one (published)
#    image serves any host user. If the launcher passed a host uid that
#    differs from the built-in agent uid, re-point the agent user before any
#    ownership work below. -o allows a non-unique uid (target may already
#    exist in the image). The .config/.local/home chowns in step 4 then land
#    on the aligned uid.
#
#    uid 0 is REFUSED. Aligning the agent user to 0 (e.g. `sudo tjor run`, or a
#    root-default container executor where $(id -u) is 0) would make gosu drop
#    to nothing and run the harness as real root — silently defeating the
#    non-root guarantee. We keep the image's default non-root uid instead; the
#    session's bind-mounted home is chowned to that uid below, so a root host
#    can still run, just never as root inside the cage.
if [[ "${TJOR_AGENT_UID:-}" == "0" ]]; then
    echo "tjor-entrypoint: refusing TJOR_AGENT_UID=0 — the agent must never run as root; keeping the image's non-root uid ($(id -u agent))" >&2
elif [[ -n "${TJOR_AGENT_UID:-}" && "${TJOR_AGENT_UID}" =~ ^[1-9][0-9]*$ ]]; then
    cur_uid="$(id -u agent)"
    if [[ "${TJOR_AGENT_UID}" != "${cur_uid}" ]]; then
        usermod -o -u "${TJOR_AGENT_UID}" agent
        groupmod -o -g "${TJOR_AGENT_UID}" agent 2>/dev/null || true
    fi
fi

# Hard invariant: whatever happened above, the agent user must not be uid 0.
if [[ "$(id -u agent)" == "0" ]]; then
    echo "tjor-entrypoint: FATAL: agent user resolved to uid 0 — refusing to start (non-root guarantee)." >&2
    exit 1
fi

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
# git's dubious-ownership check refuses to operate on a repo owned by a
# different uid than the one running git — which a bind-mounted repo is,
# whenever the owner uid differs from the (runtime-aligned) agent uid. Mark
# the mounted repos safe so git works. SCOPED to exactly the repos the
# operator mounted (TJOR_SAFE_DIRS: the workspace + any --dir), NOT '*', so
# an arbitrary path is not blanket-trusted.
#   Residual risk (documented, ADR 0008): marking a repo safe lets git read
#   its local .git/config, so an adversarial --dir'd third-party repo could
#   carry a hostile core.fsmonitor/pager/hook. This is bounded by the cage
#   itself — non-root agent (enforced above) + no direct egress — and by the
#   operator having explicitly chosen to mount that repo.
git config --system --unset-all safe.directory 2>/dev/null || true
if [[ -n "${TJOR_SAFE_DIRS:-}" ]]; then
    IFS=':' read -r -a _safe <<<"${TJOR_SAFE_DIRS}"
    for _d in "${_safe[@]}"; do
        [[ -n "${_d}" ]] && git config --system --add safe.directory "${_d}"
    done
fi
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
    echo "tjor-entrypoint: ERROR: ${AGENT_HOME} is not writable by the agent user (uid $(id -u agent)) — refusing to start." >&2
    echo "                 The session home should be owned by, or chownable to, your host uid (TJOR_AGENT_UID=${TJOR_AGENT_UID:-unset})." >&2
    exit 1
fi

# 5. Drop privileges and hand over.
exec gosu agent env HOME="${AGENT_HOME}" USER=agent "$@"
