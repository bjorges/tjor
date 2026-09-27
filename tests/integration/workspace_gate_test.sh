#!/usr/bin/env bash
# Workspace sensitive-path gate (#64), no docker required. Sources bin/tjor
# for its functions (source-guard) and drives resolve_session / cmd_run under
# a throwaway host layout — a git repo rooted at $HOME (dotfiles-style), a
# custom session.root, a custom XDG config dir — asserting: the primary
# workspace is refused exactly like a --dir would be, BEFORE any state dir
# exists; a refusal reached by git climbing above the launch dir explains
# itself; --unsafe-dir is the one override and is loud only when it actually
# overrides; tjor's own roots (session root, config dir) are sensitive in
# both directions, for the workspace AND for --dir/--dir-ro; lifecycle
# commands never see the gate. Every refusal fires before the launcher's
# first docker call — a docker shim on PATH fails loudly if reached. The
# `check "…"` names below are literal: they feed the boundary matrix
# (python/gen_boundary_matrix.py) as the launcher-side `workspace-gate` suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

# Scratch lives under the REAL home's ~/.tjor/tmp (like the sibling live
# tests), not mktemp: a macOS mktemp dir resolves to /private/var/..., which
# dir_is_sensitive refuses as a system directory — every case would "pass"
# for the wrong reason. Physical spelling: git canonicalizes its toplevel and
# dir_is_sensitive compares against $HOME verbatim, so both must share one
# namespace. GIT_CEILING_DIRECTORIES keeps git discovery from climbing above
# the scratch dir into whatever the real home happens to be.
WORK="${HOME}/.tjor/tmp/wsgate-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
trap 'rm -rf "${WORK}"' EXIT
export GIT_CEILING_DIRECTORIES="${WORK}"

# A docker shim that fails loudly and leaves a trace: reaching docker on a
# path that must have refused already is itself a failure.
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
cat >"${MOCKBIN}/docker" <<SHIM
#!/usr/bin/env bash
echo "docker reached: \$*" >> "${WORK}/docker_reached"
exit 1
SHIM
chmod +x "${MOCKBIN}/docker"
export PATH="${MOCKBIN}:${PATH}"

# Throwaway host layout:
#   $HOME               a git repo rooted at the home dir (dotfiles-style)
#   $HOME/notes         a plain directory inside it (NOT a repo)
#   $HOME/proj, proj2   ordinary repositories
#   $STATE              custom session.root = $WORK/state/sessions (outside $HOME)
#   $XDG_CONFIG_HOME    $WORK/xdg → the user-config dir is $WORK/xdg/tjor
export HOME="${WORK}/home"
mkdir -p "${HOME}/notes" "${HOME}/proj" "${HOME}/proj2"
git -C "${HOME}" init -q
git -C "${HOME}/proj" init -q
git -C "${HOME}/proj2" init -q
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
STATE="${WORK}/state/sessions"; mkdir -p "${STATE}"
# A stub pat broker (no network) so the test can prove WHEN credential
# material gets minted: never before a refusal (v0.19.0 review).
export TJOR_TEST_PAT="stub-not-a-secret-$$"
cat >"${XDG_CONFIG_HOME}/tjor/config.toml" <<TOML
[session]
root = "${STATE}"
[broker]
source = "pat"
hosts = ["github.com", "*.github.com"]
pat_env = "TJOR_TEST_PAT"
TOML
unset TJOR_USER_CONFIG TJOR_UNSAFE_DIR

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

LAST_OUT="${WORK}/last.out"
# resolve_session on the LAUNCH path from a directory; stderr → LAST_OUT.
launch_from() { ( cd "$1" && resolve_session opencode "" "" launch ) >/dev/null 2>"${LAST_OUT}"; }
refused()     { ! launch_from "$1"; }
launch_unsafe() { ( cd "$1" && TJOR_UNSAFE_DIR=1 resolve_session opencode "" "" launch ) >/dev/null 2>"${LAST_OUT}"; }
# cmd_run from a directory with the given flags; stderr → LAST_OUT.
run_from()    { ( cd "$1" && shift && cmd_run "$@" ) >/dev/null 2>"${LAST_OUT}"; }
refused_run() { ! run_from "$@"; }
lifecycle_resolve() { ( cd "$1" && resolve_session opencode "" "" && [[ -n "${TJOR_SESSION_DIR}" ]] ) >/dev/null 2>"${LAST_OUT}"; }
not_sensitive() { ! dir_is_sensitive "$1"; }
no_gate_text()  { ! grep -q -E 'sensitive|unsafe-dir' "${LAST_OUT}"; }
state_root_empty() { [[ -z "$(ls -A "${STATE}" 2>/dev/null)" ]]; }
never_reached_docker() { [[ ! -e "${WORK}/docker_reached" ]]; }
alt_cfg_dir() { ( mkdir -p "${WORK}/alt"; export TJOR_USER_CONFIG="${WORK}/alt/config.toml"; init_sensitive_roots; [[ "${TJOR_SENSITIVE_CONFIG_DIR}" == "${WORK}/alt" ]] ); }

# === 1. The sensitive set learns tjor's own roots ==========================
init_sensitive_roots
check "sensitive roots: session root derived from config" test "${TJOR_SENSITIVE_SESSION_ROOT}" = "${STATE}"
check "sensitive roots: config dir derived from XDG_CONFIG_HOME" test "${TJOR_SENSITIVE_CONFIG_DIR}" = "${XDG_CONFIG_HOME}/tjor"
check "sensitive roots: TJOR_USER_CONFIG dirname wins over XDG" alt_cfg_dir
check "session root itself is sensitive" dir_is_sensitive "${STATE}"
check "a dir under the session root is sensitive" dir_is_sensitive "${STATE}/some-session/home"
check "an ancestor of the session root is sensitive" dir_is_sensitive "${WORK}/state"
check "a sibling whose name extends the session root is not sensitive" not_sensitive "${STATE}-other"
check "config dir itself is sensitive" dir_is_sensitive "${XDG_CONFIG_HOME}/tjor"
check "a dir under the config dir is sensitive" dir_is_sensitive "${XDG_CONFIG_HOME}/tjor/profiles"
check "an ordinary repo is not sensitive" not_sensitive "${HOME}/proj"

# === 2. The workspace gate (launch path) ===================================
check "workspace gate: home-rooted dotfiles repo refused from the home dir" refused "${HOME}"
check "workspace gate: refusal names the home dir as a sensitive workspace" grep -qF "refusing to use sensitive host path as the workspace: ${HOME} " "${LAST_OUT}"
check "workspace gate: non-repo subdir of a home-rooted repo refused" refused "${HOME}/notes"
check "workspace gate: git-climb refusal names cwd, toplevel and git dir" grep -qF "${HOME}/notes is not a repository; git resolved the workspace to ${HOME} via ${HOME}/.git" "${LAST_OUT}"
check "workspace gate: git-climb refusal names the remedy" grep -qF "launch from a repository (or pass --unsafe-dir)" "${LAST_OUT}"
check "workspace gate: no state dir created after a refusal" state_root_empty
check "workspace gate: session root refused as the workspace" refused "${STATE}"
check "workspace gate: ancestor of the session root refused as the workspace" refused "${WORK}/state"
mkdir -p "${STATE}/fake-session/home"
check "workspace gate: dir under the session root refused as the workspace" refused "${STATE}/fake-session/home"
rm -rf "${STATE}/fake-session"
check "workspace gate: config dir refused as the workspace" refused "${XDG_CONFIG_HOME}/tjor"
mkdir -p "${XDG_CONFIG_HOME}/tjor/profiles"
check "workspace gate: dir under the config dir refused as the workspace" refused "${XDG_CONFIG_HOME}/tjor/profiles"
check "workspace gate: still no state dir after every refusal" state_root_empty
check "workspace gate: refusals never reached docker" never_reached_docker

# === 3. The override: loud only when it actually overrides =================
check "workspace gate: --unsafe-dir launches the home-rooted workspace" launch_unsafe "${HOME}"
check "workspace gate: --unsafe-dir warns, naming the exposed workspace" grep -qF -e "--unsafe-dir: mounting sensitive host path ${HOME} as the workspace" "${LAST_OUT}"
check "workspace gate: ordinary repo launches with no gate output" launch_from "${HOME}/proj"
check "workspace gate: ordinary repo launch prints no refusal or override text" no_gate_text
check "workspace gate: --unsafe-dir on an ordinary repo stays silent" launch_unsafe "${HOME}/proj"
check "workspace gate: no override warning when nothing was overridden" no_gate_text

# === 4. Lifecycle commands never see the gate ==============================
check "lifecycle path: resolve without the launch marker skips the gate" lifecycle_resolve "${HOME}"
check "lifecycle path: no refusal or override text" no_gate_text

# === 5. The extra-dir gates share the rule (and the loud override) =========
rm -f "${WORK}/docker_reached"
check "extra-dir gate: session root refused via --dir" refused_run "${HOME}/proj" --dir "${STATE}" -- true
check "extra-dir gate: --dir refusal names the sensitive path" grep -qF "refusing to mount sensitive host path into the agent: ${STATE} " "${LAST_OUT}"
check "extra-dir gate: session root refused via --dir-ro" refused_run "${HOME}/proj" --dir-ro "${STATE}" -- true
check "extra-dir gate: --dir-ro refusal states the read-only exposure" grep -qF "even read-only, this exposes its contents" "${LAST_OUT}"
check "extra-dir gate: refusals never reached docker" never_reached_docker
no_broker_minted() { local d; for d in "${STATE}"/proj-*/broker/broker.json; do [[ -e "${d}" ]] && return 1; done; return 0; }
check "extra-dir gate: a refused --dir minted no credential material" no_broker_minted
run_from "${HOME}/proj" --dir "${STATE}" --unsafe-dir -- true || true   # continues past the gate into the (shimmed) docker path
broker_minted_after_pass() { local d; for d in "${STATE}"/proj-*/broker/broker.json; do [[ -e "${d}" ]] && return 0; done; return 1; }
check "extra-dir gate: a launch that passes every gate does mint (control)" broker_minted_after_pass
check "extra-dir gate: --unsafe-dir warns on an actually-overridden --dir" grep -qF -e "--unsafe-dir: mounting sensitive host path ${STATE} READ-WRITE" "${LAST_OUT}"
run_from "${HOME}/proj" --dir "${HOME}/proj2" -- true || true
check "extra-dir gate: no override warning for an ordinary --dir" no_gate_text

# === 6. core.worktree redirect (#76 reproduction, kept as a regression test) =
# A session always has its workspace repo writable, so it can plant
# core.worktree; git then reports the planted path as the toplevel from
# anywhere inside the repo. The launcher finds the repository on its own (the
# nearest .git above the launch dir) and refuses git's toplevel when it
# disagrees — on the launch path, on lifecycle paths, and in every other
# host-side consumer (attach, repo_root behind trust/init/policy).
mkdir -p "${HOME}/wt/sub"; git -C "${HOME}/wt" init -q
no_state_for() { local d; for d in "${STATE}/$1-"*; do [[ -e "${d}" ]] && return 1; done; return 0; }
lifecycle_refused() { ! ( cd "$1" && resolve_session opencode "" "" ) >/dev/null 2>"${LAST_OUT}"; }
git -C "${HOME}/wt" config core.worktree "${HOME}/proj2"
check "core.worktree: redirect toward a harmless directory is refused" refused "${HOME}/wt/sub"
check "core.worktree: refusal names the launch dir and the reported work tree" grep -qF "work tree of ${HOME}/wt/sub as ${HOME}/proj2" "${LAST_OUT}"
check "core.worktree: refusal names the setting and its config file" grep -qF "core.worktree = '${HOME}/proj2' in ${HOME}/wt/.git/config" "${LAST_OUT}"
check "core.worktree: no state dir for the redirected path" no_state_for proj2
check "core.worktree: lifecycle resolution refuses the redirect too" lifecycle_refused "${HOME}/wt/sub"
rm -f "${WORK}/docker_reached"   # section 5's override runs reached the shim by design; attach must not
attach_refused() { ! ( cd "$1" && cmd_attach foo ) >/dev/null 2>"${LAST_OUT}"; }
repo_root_refused() { ! ( cd "$1" && repo_root ) >/dev/null 2>"${LAST_OUT}"; }
check "core.worktree: attach's short-name qualification refuses the redirect" attach_refused "${HOME}/wt/sub"
check "core.worktree: attach refusal never reached docker" never_reached_docker
check "core.worktree: repo_root (trust/init/policy) refuses the redirect" repo_root_refused "${HOME}/wt/sub"
mkdir -p "${HOME}/all"; mv "${HOME}/wt" "${HOME}/all/wt"
git -C "${HOME}/all/wt" config core.worktree "${HOME}/all"
check "core.worktree: redirect toward an ancestor holding other repos is refused" refused "${HOME}/all/wt/sub"
check "core.worktree: ancestor refusal names the nearest repository" grep -qF "nearest repository above the launch directory is ${HOME}/all/wt" "${LAST_OUT}"
mv "${HOME}/all/wt" "${HOME}/wt"
git -C "${HOME}/wt" config core.worktree "${HOME}"
check "core.worktree: redirect toward the home directory is refused as a redirect" refused "${HOME}/wt/sub"
check "core.worktree: home redirect names core.worktree, not the not-a-repository wording" bash -c "grep -q 'core.worktree' '${LAST_OUT}' && ! grep -q 'is not a repository' '${LAST_OUT}'"
git -C "${HOME}/wt" config --unset core.worktree
git -C "${HOME}/wt" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m init
git -C "${HOME}/wt" worktree add -q "${HOME}/wt-linked" >/dev/null 2>&1
check "core.worktree: a linked worktree launches (containment holds)" launch_from "${HOME}/wt-linked"
check "core.worktree: a subdirectory launch is unchanged" launch_from "${HOME}/wt/sub"

# === 7. Help text names the workspace ======================================
check "help text names the workspace gate" bash -c "'${ROOT}/bin/tjor' help | grep -qF 'sensitive paths refused as the workspace or as --dir/--dir-ro unless --unsafe-dir'"

echo
echo "workspace-gate: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
