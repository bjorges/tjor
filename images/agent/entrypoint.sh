#!/usr/bin/env bash
# tjor agent entrypoint. Runs as root for setup, then drops to the agent
# user. Instructions are image cargo (charter L16): re-deployed on EVERY
# start so they are versioned with the image, not with mutable user state.
set -euo pipefail

AGENT_HOME=/home/agent

# Exit code for "a required security boundary could not be established" (#40).
# MUST match TJOR_EXIT_BOUNDARY in bin/tjor: run_agent propagates this
# container exit code out through `tjor run`, so an in-cage boundary abort
# (non-root guarantee, required kernel sandbox unavailable) surfaces with the
# same code as a host-side one. Documented in README (Exit codes).
TJOR_EXIT_BOUNDARY=90

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
    exit "${TJOR_EXIT_BOUNDARY}"
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
#    An opted-in profile's instructions/AGENTS.md (#C2), if staged, is
#    APPENDED after the baseline — never a replacement — before that render.
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

# An opted-in profile may APPEND to (never replace) the baseline instruction
# cargo via one staged file, instructions/AGENTS.md (#C2). Read it once, up
# front, so every harness dialect below gets the same combined content; a
# missing file leaves EXTRA_INSTRUCTIONS empty and behavior identical to
# today (baseline only). This file is excluded from the generic per-harness
# overlay loop below — it has no harness-native home of its own.
EXTRA_INSTRUCTIONS = ""
_extra_path = profile / "instructions" / "AGENTS.md"
if _extra_path.is_file():
    EXTRA_INSTRUCTIONS = _extra_path.read_text()

for h in harnesses:
    cfg, fname = TARGETS[h]
    desymlink(cfg)
    if NEUTRAL.is_file():
        baseline = NEUTRAL.read_text()
        combined = baseline + "\n" + EXTRA_INSTRUCTIONS if EXTRA_INSTRUCTIONS else baseline
        safe_write_target(cfg / fname).write_text(combined)
    # Overlay an opted-in host profile (#29) on top of the baseline cargo. The
    # staged dir was credential-filtered host-side (allow-list in
    # tjor_profile.py), so we copy it wholesale into this harness's config dir;
    # an operator definition wins over the baseline. Symlink-safe per target.
    # instructions/AGENTS.md is handled above (appended, not copied verbatim)
    # and is skipped here so it doesn't also land as a stray file.
    if profile.is_dir():
        for src in sorted(p for p in profile.rglob("*") if p.is_file()):
            rel = src.relative_to(profile)
            if rel == pathlib.Path("instructions") / "AGENTS.md":
                continue
            # managed/ (#46) is not a harness definition dir: its
            # opencode.json is deployed root-owned to /etc/opencode by the
            # entrypoint (step 2b), never into the agent-writable config.
            if rel.parts and rel.parts[0] == "managed":
                continue
            dst = cfg / rel
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

# 2b. Managed opencode config tier (#46): a staged profile may carry
#     managed/opencode.json; deploy it ROOT-owned to opencode's managed
#     settings path, which opencode loads after — and which cannot be
#     overridden by — any user- or project-level opencode config. Deployed
#     before the privilege drop, so the agent user can never write, replace,
#     or remove it: the one config control that survives whatever trees the
#     session grows. Invalid JSON aborts with the boundary code — a session
#     must never LOOK hardened without BEING it (the launcher already
#     validated; this is the enforcement point for non-launcher starts).
#     With no staged managed file, a stale one (an earlier restart of this
#     container) is removed, keeping no-profile behavior identical to
#     pre-#46. NOTE: OPENCODE_CONFIG_DIR is deliberately NOT set — in the
#     shipped opencode it REPLACES the global config dir, which would
#     displace the baseline cargo and autoupdate pin deployed in step 2
#     (design: add-ro-mounts-and-config-neutralization).
managed_src="${TJOR_PROFILE_DIR:-}/managed/opencode.json"
if [[ -n "${TJOR_PROFILE_DIR:-}" && -f "${managed_src}" ]]; then
    if ! python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "${managed_src}" 2>/dev/null; then
        echo "tjor-entrypoint: FATAL: staged managed/opencode.json is not valid JSON — refusing to start (a hardened profile must not silently lose its managed settings)." >&2
        exit "${TJOR_EXIT_BOUNDARY}"
    fi
    mkdir -p /etc/opencode
    chmod 0755 /etc/opencode
    install -m 0644 -o root -g root "${managed_src}" /etc/opencode/opencode.json
    echo "tjor-entrypoint: managed opencode config deployed (/etc/opencode/opencode.json, root-owned)" >&2
else
    rm -f /etc/opencode/opencode.json
fi
unset managed_src

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
    #
    # Tree trust (#53, spec: session-launch): a WRITABLE root is registered
    # as '<root>' AND '<root>/*' — git >= 2.46 gives the trailing-/* entry
    # prefix semantics (the image gates >= 2.46 at build), so worktrees and
    # repos created under it mid-session, and nested pre-existing repos,
    # are trusted without any dynamic registration step. A READ-ONLY root
    # (TJOR_RO_DIRS) keeps the exact entry only: git's ownership refusal is
    # what stops hostile pre-existing nested .git/config (fsmonitor, pager,
    # filters, hooks, credential helpers) from executing in unvetted
    # content, and nothing new can be created under a :ro mount anyway.
    #
    # Degenerate roots are REFUSED, not skipped: an entry that is '/', '*',
    # or ends in '/*' would itself be wildcard-interpretable — verified:
    # safe.directory '/*' trusts every absolute path, the bare-'*' ADR 0008
    # forbids. Trailing slashes are normalized first ('root/' would
    # register an inert 'root//*'). Blank lines are list formatting, not
    # roots. The launcher refuses these earlier; this is the enforcement
    # point for non-launcher starts.
    while IFS= read -r _d; do
        [[ -n "${_d}" ]] || continue
        while [[ "${_d}" == */ && "${_d}" != "/" ]]; do _d="${_d%/}"; done
        case "${_d}" in
            /|\*|*/\*)
                echo "tjor-entrypoint: FATAL: mount root '${_d}' would make git trust wildcard-interpretable (blanket trust) — refusing to start." >&2
                exit "${TJOR_EXIT_BOUNDARY}"
                ;;
        esac
        git config --system --add safe.directory "${_d}"
        if ! grep -qxF -- "${_d}" <<<"${TJOR_RO_DIRS:-}"; then
            git config --system --add safe.directory "${_d}/*"
        fi
    done <<<"${TJOR_SAFE_DIRS}"
fi
# The placeholder helper is wired only when the broker actually COVERS GitHub
# (#47): decided with the proxy's own host matcher (tjor_identity/tjor_policy,
# shipped as image cargo — ONE matcher, never a bash re-implementation). A
# broker scoped elsewhere (e.g. kube-only) keeps the gh fallback, so git never
# sends an unsubstitutable placeholder to github.com — an intentional
# no-GitHub-credential session behaves like a broker-less one there.
broker_covers_github=""
if [[ -n "${TJOR_BROKER_ENABLED:-}" ]]; then
    if python3 - <<'PY'
import os
import sys

sys.path.insert(0, "/opt/tjor/python")
import tjor_identity

pairs = tjor_identity.parse_broker_hosts(os.environ.get("TJOR_BROKER_HOSTS", ""))
# Port-aware (#49): git talks to GitHub on 443 — a broker scoped to another
# port would never have its credential injected there, so the placeholder
# would only break git; coverage means github/gist on 443 specifically.
covered = tjor_identity.broker_covers(pairs, "github.com", 443) \
    or tjor_identity.broker_covers(pairs, "gist.github.com", 443)
sys.exit(0 if covered else 1)
PY
    then
        broker_covers_github=1
    fi
fi
if [[ -n "${broker_covers_github}" ]]; then
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

# 5. Kernel-sandbox tier (#9): probe Landlock IN THE ENFORCEMENT CONTEXT (as
#    the aligned agent user), then branch on TJOR_LANDLOCK. Any probe error —
#    ENOSYS (kernel too old / syscall filtered), EOPNOTSUPP (disabled at
#    boot), EPERM (hardened seccomp) — classifies the tier unavailable; the
#    session NEVER degrades silently. Availability is never inferred from
#    kernel version or runtime name (spec: kernel-sandbox).
TJOR_LANDLOCK="${TJOR_LANDLOCK:-auto}"
case "${TJOR_LANDLOCK}" in
    auto|require|off) ;;
    *)
        echo "tjor-entrypoint: FATAL: invalid TJOR_LANDLOCK mode '${TJOR_LANDLOCK}' — must be auto, require, or off." >&2
        exit 1
        ;;
esac

landlock_abi=""
landlock_err=""
if [[ "${TJOR_LANDLOCK}" != "off" ]]; then
    # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION):
    # syscall 444 on both amd64 and arm64. Success prints the ABI version;
    # any failure prints the errno name and exits nonzero.
    if probe_out="$(gosu agent python3 - 2>&1 <<'PY'
import ctypes, errno, sys
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
res = libc.syscall(444, None, 0, 1)
if res < 0:
    e = ctypes.get_errno()
    print(errno.errorcode.get(e, "errno=%d" % e))
    sys.exit(1)
print(res)
PY
)"; then
        landlock_abi="${probe_out}"
    else
        landlock_err="${probe_out:-probe failed}"
    fi
fi

# Project dir for the wrap: the first TJOR_SAFE_DIRS entry is the workspace
# the launcher mounted (host path == container path, newline-delimited, step
# 3); fall back to the working directory (cplt resolves the git toplevel
# itself). With no workspace at all (a direct `docker run` without the
# launcher, PWD=/), cplt rightly refuses to sandbox "/" — classify the tier
# unavailable so auto degrades LOUDLY and require refuses; never a silent
# unwrapped run.
project_dir="${TJOR_SAFE_DIRS:-}"
project_dir="${project_dir%%$'\n'*}"
[[ -n "${project_dir}" && -d "${project_dir}" ]] || project_dir="${PWD}"
if [[ -n "${landlock_abi}" && "${project_dir}" == "/" ]]; then
    landlock_abi=""
    landlock_err="no workspace mounted (direct container run without the launcher?)"
fi

# 6. Drop privileges and hand over — under the cplt Landlock wrap when the
#    tier is active. Flag rationale lives in the design doc (add-landlock-tier
#    decision 2); the short version: tjor's egress proxy is the ONLY network
#    and action policy (--no-proxy, no guards), the cage env is load-bearing
#    and secret-free by construction (--inherit-env + the lowercase proxy vars
#    cplt's sanitizer would strip), the harness must reach the proxy port, and
#    the session home holds no host secrets (granted wholesale — per-dir
#    grants proved brittle). In-tree dotenv secrets are masked by the LAUNCHER
#    (read-only mounts), not here: Landlock cannot deny in-tree paths.
#    Fail-closed: if the probe passed but cplt then fails to exec, set -e
#    aborts the start — a session must never LOOK sandboxed without BEING it.
if [[ "${TJOR_LANDLOCK}" == "off" ]]; then
    echo "tjor-entrypoint: kernel-sandbox: disabled by config (mode=off)" >&2
elif [[ -n "${landlock_abi}" ]]; then
    echo "tjor-entrypoint: kernel-sandbox: active (landlock ABI ${landlock_abi})" >&2
    wrap=(cplt --project-dir "${project_dir}"
          --no-proxy --no-gh-guard --no-git-guard
          --inherit-env --pass-env http_proxy --pass-env https_proxy --pass-env no_proxy
          --allow-port "${TJOR_PROXY_PORT:-8080}" --allow-localhost-any
          --allow-read "${AGENT_HOME}" --allow-write "${AGENT_HOME}")
    # Grant each further operator-mounted repo (--dir extras) — the same
    # newline-delimited list git trusts (step 3). A root also listed in
    # TJOR_RO_DIRS was mounted read-only (#44): grant --allow-read so the
    # kernel tier AGREES with the :ro mount instead of claiming a
    # writability the mount would refuse anyway (the :ro mount is the
    # enforcement; this keeps the two layers telling the same story).
    # Exact-line match (grep -qxF) for the same reason the list is
    # newline-delimited: paths may contain colons, and a prefix match would
    # misclassify a sibling.
    if [[ -n "${TJOR_SAFE_DIRS:-}" ]]; then
        while IFS= read -r _d; do
            [[ -n "${_d}" && "${_d}" != "${project_dir}" ]] || continue
            if grep -qxF -- "${_d}" <<<"${TJOR_RO_DIRS:-}"; then
                wrap+=(--allow-read "${_d}")
            else
                wrap+=(--allow-write "${_d}")
            fi
        done <<<"${TJOR_SAFE_DIRS}"
    fi
    exec gosu agent env HOME="${AGENT_HOME}" USER=agent "${wrap[@]}" exec -- "$@"
elif [[ "${TJOR_LANDLOCK}" == "require" ]]; then
    echo "tjor-entrypoint: FATAL: kernel-sandbox required (mode=require) but Landlock is unavailable (${landlock_err}) — refusing to start the harness." >&2
    exit "${TJOR_EXIT_BOUNDARY}"
else
    echo "tjor-entrypoint: kernel-sandbox: INACTIVE — ${landlock_err}; sessions run without the kernel FS-deny tier (the container boundary remains in force)" >&2
fi
exec gosu agent env HOME="${AGENT_HOME}" USER=agent "$@"
