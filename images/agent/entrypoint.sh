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

# 2. Deploy instruction cargo per active harness and disable harness
#    self-update — symlink-safe (charter L26): the home dir is agent-writable
#    and persists across sessions, so a previous session could have planted
#    symlinks to redirect these root-privileged writes. Every touched component
#    is checked and de-symlinked before any write. No agent process runs
#    concurrently with this (the harness starts only at the exec below), so a
#    point-in-time sweep is race-free. TJOR_HARNESS names the session's
#    harness(es) (a comma list for a multi-harness image); the ONE neutral
#    instruction file is rendered into each harness's own dialect path
#    (opencode AGENTS.md / claude CLAUDE.md / copilot copilot-instructions.md).
python3 - <<'PY'
import json
import os
import pathlib
import shutil

HOME = pathlib.Path("/home/agent")
NEUTRAL = pathlib.Path("/opt/tjor/instructions/AGENTS.md")

# harness -> (config dir, instruction filename in that harness's dialect).
TARGETS = {
    "opencode": (HOME / ".config" / "opencode", "AGENTS.md"),
    "claude":   (HOME / ".claude",              "CLAUDE.md"),
    "copilot":  (HOME / ".copilot",             "copilot-instructions.md"),
}
requested = [h for h in os.environ.get("TJOR_HARNESS", "").split(",") if h in TARGETS]
harnesses = requested or ["opencode"]


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


# opencode keeps state under these XDG dirs; keep them real regardless.
desymlink(HOME / ".local" / "share")
desymlink(HOME / ".local" / "state")

profile = pathlib.Path(os.environ.get("TJOR_PROFILE_DIR", "") or "/nonexistent")

for h in harnesses:
    cfg, fname = TARGETS[h]
    desymlink(cfg)
    if NEUTRAL.is_file():
        shutil.copyfile(NEUTRAL, safe_write_target(cfg / fname))
    # Overlay an opted-in host profile (#29) on top of the baseline cargo. The
    # staged dir was credential-filtered host-side (allow-list in
    # tjor_profile.py), so we copy it wholesale into this harness's config dir;
    # an operator definition wins over the baseline. Symlink-safe per target.
    if profile.is_dir():
        for src in sorted(p for p in profile.rglob("*") if p.is_file()):
            dst = cfg / src.relative_to(profile)
            desymlink(dst.parent)
            shutil.copyfile(src, safe_write_target(dst))
    # Harness self-update is an image concern, never a session one (charter
    # L13). opencode has no env knob, so disable it via its config file; claude
    # and copilot are disabled via image ENV (DISABLE_AUTOUPDATER /
    # COPILOT_AUTO_UPDATE) and need no per-session write.
    if h == "opencode":
        cfgfile = safe_write_target(cfg / "opencode.json")
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
# operator mounted (TJOR_SAFE_DIRS, NEWLINE-delimited: the workspace + any
# --dir), NOT '*', so an arbitrary path is not blanket-trusted. Newline (not
# ':') separates entries because a directory path may legally contain a colon.
#   Residual risk (documented, ADR 0008): marking a repo safe lets git read
#   its local .git/config, so an adversarial --dir'd third-party repo could
#   carry a hostile core.fsmonitor/pager/hook. This is bounded by the cage
#   itself — non-root agent (enforced above) + no direct egress — and by the
#   operator having explicitly chosen to mount that repo.
git config --system --unset-all safe.directory 2>/dev/null || true
if [[ -n "${TJOR_SAFE_DIRS:-}" ]]; then
    # Read one path per line so a colon inside a path is preserved verbatim.
    while IFS= read -r _d; do
        [[ -n "${_d}" ]] && git config --system --add safe.directory "${_d}"
    done <<<"${TJOR_SAFE_DIRS}"
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

# 3b. Kube broker (#26): render a PLACEHOLDER kubeconfig so caged `kubectl`
#     sends `Authorization: Bearer <placeholder>` and the proxy overwrites it
#     with the real short-TTL SA token (which never enters the cage). Uses the
#     SAME tjor_kube.py the launcher used to derive the host. TLS to the
#     (proxy-MITM'd) API server is trusted via the session CA in CA_BUNDLE.
#     Symlink-safe: the home persists, so a prior session could have planted a
#     symlink here — de-symlink the dir and target before this root-owned write.
if [[ -n "${TJOR_BROKER_ENABLED:-}" && -n "${TJOR_KUBE_SERVER:-}" ]]; then
    kube_dir="${AGENT_HOME}/.kube"
    [[ -L "${kube_dir}" || ( -e "${kube_dir}" && ! -d "${kube_dir}" ) ]] && rm -rf "${kube_dir}"
    mkdir -p "${kube_dir}"
    kube_cfg="${kube_dir}/config"
    kube_tmp="${kube_cfg}.tmp"
    # De-symlink BOTH the final config AND the .tmp we redirect through: a prior
    # session (agent-level access, no root) could have planted config.tmp as a
    # symlink, and the root redirect below would then write the placeholder
    # THROUGH it, clobbering whatever the entrypoint's root can reach. Every
    # root write in this file is de-symlinked at its touch point (charter L26);
    # this .tmp is one such point. Race-free: no agent runs until the exec below.
    for kube_target in "${kube_cfg}" "${kube_tmp}"; do
        [[ -L "${kube_target}" || ( -e "${kube_target}" && ! -f "${kube_target}" ) ]] && rm -rf "${kube_target}"
    done
    if python3 /opt/tjor/python/tjor_kube.py config "${TJOR_KUBE_SERVER}" "${CA_BUNDLE}" >"${kube_tmp}" 2>/dev/null; then
        mv -f "${kube_tmp}" "${kube_cfg}"
        chmod 600 "${kube_cfg}"
        chown -R agent:agent "${kube_dir}" 2>/dev/null || true
    else
        rm -f "${kube_tmp}"
        echo "tjor-entrypoint: WARNING: failed to render kube placeholder config" >&2
    fi
    unset kube_dir kube_cfg kube_tmp kube_target
fi

# 4. Ownership + writability. The setup above runs as root and creates XDG
#    dirs (.config, .local/share, .local/state) root-owned; chown them to the
#    agent uid (= the host user) so the session state stays host-manageable
#    (e.g. `tjor reset`) on a native-Linux engine — on a uid-mapping VM
#    (Colima virtiofs) chown can legitimately fail, so warn, then hard-verify
#    the invariant that actually matters: the agent user can write its home.
for d in "${AGENT_HOME}/.config" "${AGENT_HOME}/.local" "${AGENT_HOME}/.claude" "${AGENT_HOME}/.copilot"; do
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
