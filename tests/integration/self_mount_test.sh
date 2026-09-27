#!/usr/bin/env bash
# Launcher integrity (#67), no docker required: the self-mount guard, `tjor
# self-install`, the source-tree marker, the tjor.source-sha image label, the
# install root in the sensitive set, and the doctor report. Sources bin/tjor
# (source-guard) with THIS checkout as TJOR_ROOT — the guard's own subject —
# under a throwaway $HOME (a git repo `proj`, a custom session.root, a custom
# install root) and a docker shim that records every argv and fails, so any
# refusal that reaches docker is itself a failure and any build that runs is
# inspectable. The `check "…"` names are literal: they feed the boundary
# matrix (python/gen_boundary_matrix.py) as the launcher-side `self-mount`
# suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

# Scratch under the REAL home's ~/.tjor/tmp (a macOS mktemp path is a
# sensitive /private/var/... — see workspace_gate_test.sh); physical spelling.
WORK="${HOME}/.tjor/tmp/selfmount-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
cleanup() { chmod -R u+w "${WORK}" 2>/dev/null || true; rm -rf "${WORK}"; }
trap cleanup EXIT

# docker shim: record argv, fail. Reaching it on a refusal path = failure;
# reaching it on a build path = the argv we assert the label on.
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
cat >"${MOCKBIN}/docker" <<SHIM
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${WORK}/docker_argv"
exit 1
SHIM
chmod +x "${MOCKBIN}/docker"
export PATH="${MOCKBIN}:${PATH}"

export HOME="${WORK}/home"; mkdir -p "${HOME}/proj" "${HOME}/proj2"
git -C "${HOME}/proj" init -q
git -C "${HOME}/proj2" init -q
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
STATE="${WORK}/state/sessions"; mkdir -p "${STATE}"
printf '[session]\nroot = "%s"\n' "${STATE}" > "${XDG_CONFIG_HOME}/tjor/config.toml"
export TJOR_INSTALL_ROOT="${WORK}/install"
unset TJOR_USER_CONFIG TJOR_UNSAFE_DIR TJOR_ALLOW_SELF_MOUNT

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

LAST_OUT="${WORK}/last.out"
run_from()    { ( cd "$1" && shift && cmd_run "$@" ) >/dev/null 2>"${LAST_OUT}"; }
refused_run() { ! run_from "$@"; }
launch_from() { ( cd "$1" && resolve_session opencode "" "" launch ) >/dev/null 2>"${LAST_OUT}"; }
refused()     { ! launch_from "$1"; }
not_overlap() { ! self_mount_overlaps "$1"; }
not_sensitive() { ! dir_is_sensitive "$1"; }
never_reached_docker() { [[ ! -e "${WORK}/docker_argv" ]]; }
no_self_text() { ! grep -q -E 'running tjor tree|self-mount' "${LAST_OUT}"; }
argv_has() { grep -qF -e "$1" "${WORK}/docker_argv"; }
argv_lacks() { ! grep -q -E "$1" "${WORK}/docker_argv"; }
HEAD_SHA="$(git -C "${ROOT}" rev-parse HEAD)"
EXPECT_SHA="${HEAD_SHA}"; [[ -n "$(git -C "${ROOT}" status --porcelain)" ]] && EXPECT_SHA="${HEAD_SHA}-dirty"

# === 1. The overlap rule ====================================================
check "self-mount rule: the checkout itself overlaps" self_mount_overlaps "${ROOT}"
check "self-mount rule: a dir inside the checkout overlaps" self_mount_overlaps "${ROOT}/images"
check "self-mount rule: a parent of the checkout overlaps" self_mount_overlaps "$(dirname "${ROOT}")"
check "self-mount rule: a sibling whose name extends the checkout does not overlap" not_overlap "${ROOT}-other"
check "self-mount rule: an ordinary repo does not overlap" not_overlap "${HOME}/proj"

# === 2. The guard on the launch path ========================================
check "self-mount guard: the checkout as the workspace is refused" refused_run "${ROOT}" -- true
check "self-mount guard: refusal names the tree and the writable root" grep -qF "refusing to launch: the running tjor tree ${ROOT} would be mounted WRITABLE via ${ROOT}" "${LAST_OUT}"
check "self-mount guard: refusal names the three remedies" bash -c "grep -qF 'tjor self-install' '${LAST_OUT}' && grep -qF -- '--dir-ro' '${LAST_OUT}' && grep -qF -- '--allow-self-mount' '${LAST_OUT}'"
check "self-mount guard: a dir inside the checkout via --dir is refused" refused_run "${HOME}/proj" --dir "${ROOT}/images" -- true
check "self-mount guard: a parent of the checkout via --dir is refused" refused_run "${HOME}/proj" --dir "$(dirname "${ROOT}")" -- true
check "self-mount guard: refusals never reached docker" never_reached_docker
run_from "${HOME}/proj" -- true || true
check "self-mount guard: a disjoint workspace prints no self-mount text" no_self_text
rm -f "${WORK}/docker_argv"
run_from "${HOME}/proj" --dir-ro "${ROOT}" -- true || true
check "self-mount guard: read-only self-mount is allowed with a notice" grep -qF "note: the running tjor tree ${ROOT} is mounted read-only via ${ROOT}" "${LAST_OUT}"
check "self-mount guard: read-only self-mount is not refused" bash -c "! grep -q 'refusing to launch' '${LAST_OUT}'"
rm -f "${WORK}/docker_argv"
run_from "${ROOT}" --allow-self-mount -- true || true
check "self-mount guard: --allow-self-mount proceeds with a loud warning" grep -qF -e "--allow-self-mount: the running tjor tree ${ROOT} is mounted WRITABLE via ${ROOT}" "${LAST_OUT}"
check "image label: a checkout build carries tjor.source-sha=HEAD (dirty-aware)" argv_has "--label tjor.source-sha=${EXPECT_SHA}"
rm -f "${WORK}/docker_argv"

# === 3. self-install ========================================================
INST="${TJOR_INSTALL_ROOT}/${HEAD_SHA}"
si_out="${WORK}/si.out"
install_head() { cmd_self_install >/dev/null 2>"${si_out}"; }
check "self-install: installs the committed HEAD tree" install_head
check "self-install: tree contains the launcher, compose, config, python, images, VERSION" bash -c "test -x '${INST}/bin/tjor' && test -f '${INST}/compose.yaml' && test -d '${INST}/config' && test -d '${INST}/python' && test -d '${INST}/images' && test -f '${INST}/VERSION'"
check "self-install: marker holds the sha" bash -c "[ \"\$(cat '${INST}/.tjor-source-sha')\" = '${HEAD_SHA}' ]"
check "self-install: nothing under the tree is writable" bash -c "[ -z \"\$(find '${INST}' -perm -200 | head -1)\" ]"
check "self-install: current points at the sha" bash -c "[ \"\$(readlink '${TJOR_INSTALL_ROOT}/current')\" = '${HEAD_SHA}' ]"
check "self-install: output names the launcher path" grep -qF "point launchers at: ${TJOR_INSTALL_ROOT}/current/bin/tjor" "${si_out}"
check "self-install: output says uncommitted changes are excluded" grep -qF "uncommitted changes" "${si_out}"
cmd_self_install >/dev/null 2>"${si_out}" || true
check "self-install: re-installing the same sha is idempotent" grep -qF "already installed" "${si_out}"
bogus_ref_fails() { ! ( cmd_self_install --ref "no-such-ref-$$" ); }
check "self-install: a bogus ref fails" bogus_ref_fails
installed_is_source() { ( TJOR_ROOT="${INST}"; is_source_tree ); }
installed_sha()       { ( TJOR_ROOT="${INST}"; [[ "$(source_sha)" == "${HEAD_SHA}" ]] ); }
installed_not_checkout() { ! ( TJOR_ROOT="${INST}"; cmd_self_install ); }
check "self-install: the installed tree is a source tree" installed_is_source
check "self-install: source_sha of the installed tree is the marker" installed_sha
check "self-install: self-install from an installed tree is refused" installed_not_checkout
( TJOR_ROOT="${INST}"; resolve_agent_image opencode ) >/dev/null 2>&1 || true
check "self-install: the installed tree builds locally, never pulls" bash -c "grep -q '^build ' '${WORK}/docker_argv' && ! grep -q -E '^(pull|image pull)' '${WORK}/docker_argv'"
check "image label: an installed-tree build carries the marker sha" argv_has "--label tjor.source-sha=${HEAD_SHA}"
rm -f "${WORK}/docker_argv"

# === 4. The install root is sensitive =======================================
init_sensitive_roots
check "sensitive roots: install root derived from TJOR_INSTALL_ROOT" test "${TJOR_SENSITIVE_INSTALL_ROOT}" = "${TJOR_INSTALL_ROOT}"
check "install root itself is sensitive" dir_is_sensitive "${TJOR_INSTALL_ROOT}"
check "an installed tree under the install root is sensitive" dir_is_sensitive "${INST}"
check "an ancestor of the install root is sensitive" dir_is_sensitive "${WORK}"
check "a sibling whose name extends the install root is not sensitive" not_sensitive "${TJOR_INSTALL_ROOT}-other"
check "install root refused via --dir" refused_run "${HOME}/proj" --dir "${TJOR_INSTALL_ROOT}" -- true
check "install root --dir refusal is the sensitive-path error" grep -qF "refusing to mount sensitive host path into the agent: ${TJOR_INSTALL_ROOT} " "${LAST_OUT}"
check "a workspace inside an installed tree is refused" refused "${INST}/python"
check "install-root refusals never reached docker" never_reached_docker

# === 5. Doctor ==============================================================
doc_out="${WORK}/doctor.out"
( cd "${ROOT}" && cmd_doctor ) >"${doc_out}" 2>&1 || true
check "doctor: inside the checkout names a mutable git checkout" grep -qF "tjor root:     ${ROOT} (git checkout — MUTABLE)" "${doc_out}"
check "doctor: inside the checkout warns that a launch from here is refused" grep -qF "would mount this checkout WRITABLE" "${doc_out}"
doctor_installed() { ( export TJOR_ROOT="${INST}"; cd "${HOME}/proj" && cmd_doctor ); }
doctor_installed >"${doc_out}" 2>&1 || true
check "doctor: from an installed tree names the sha, read-only" grep -qF "(self-installed ${HEAD_SHA}, read-only)" "${doc_out}"
check "doctor: from an installed tree has no self-mount warning" bash -c "! grep -q 'would mount this checkout' '${doc_out}'"
doctor_outside_repo() { ( cd "${WORK}" && cmd_doctor ) >/dev/null 2>&1; }
check "doctor: succeeds outside any repository" doctor_outside_repo

# === 6. Help text ===========================================================
help_names_both() { usage | grep -qF -- '--allow-self-mount' && usage | grep -qF 'self-install [--ref'; }
check "help text names --allow-self-mount and self-install" help_names_both

echo
echo "self-mount: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
