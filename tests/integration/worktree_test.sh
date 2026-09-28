#!/usr/bin/env bash
# Worktree common-dir mounts (#79, from the #77 reproduction), no docker
# required. Sources bin/tjor and drives the resolver (worktree_common_dir /
# worktree_common_dirs), cmd_run's wiring and plan_git_masks against a
# throwaway $HOME: a linked worktree, a --separate-git-dir checkout, a bare
# repository's worktree, a planted pointer, a dangling pointer, a symlinked
# .git, a worktree whose main repository lies inside tjor's session root.
# Every refusal fires before the launcher's first docker call — a docker
# shim on PATH leaves a trace when reached. The `check "…"` names below are
# literal: they feed the boundary matrix as the `worktree` suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

WORK="${HOME}/.tjor/tmp/worktree-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
trap 'rm -rf "${WORK}"' EXIT
export GIT_CEILING_DIRECTORIES="${WORK}"
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
cat >"${MOCKBIN}/docker" <<SHIM
#!/usr/bin/env bash
echo "docker reached: \$*" >> "${WORK}/docker_reached"
exit 1
SHIM
chmod +x "${MOCKBIN}/docker"
export PATH="${MOCKBIN}:${PATH}"
export HOME="${WORK}/home"; mkdir -p "${HOME}"
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
STATE="${WORK}/state/sessions"; mkdir -p "${STATE}"
printf '[session]\nroot = "%s"\n' "${STATE}" > "${XDG_CONFIG_HOME}/tjor/config.toml"
unset TJOR_USER_CONFIG TJOR_UNSAFE_DIR
commit() { git -C "$1" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m base; }

# Layout
git init -q "${HOME}/main"; commit "${HOME}/main"
git -C "${HOME}/main" worktree add -q "${HOME}/wt" -b feat            # linked worktree, main OUTSIDE it
git -C "${HOME}/main" worktree add -q "${HOME}/wt3" -b feat3           # a second worktree of the same repo
git init -q --separate-git-dir "${HOME}/sepgit" "${HOME}/sep"; commit "${HOME}/sep"   # separate git dir, back-linked
git -C "${HOME}/sep" config core.worktree "${HOME}/sep"
git init -q --separate-git-dir "${HOME}/sep2git" "${HOME}/sep2"; commit "${HOME}/sep2"; git -C "${HOME}/sep2" config --unset core.worktree 2>/dev/null || true   # no back-link
git clone -q --bare "${HOME}/main" "${HOME}/bare.git"; git -C "${HOME}/bare.git" worktree add -q "${HOME}/bwt" -b bfeat   # bare common dir
mkdir -p "${HOME}/planted"; printf 'gitdir: %s/main/.git/worktrees/wt\n' "${HOME}" > "${HOME}/planted/.git"   # someone else's private dir
mkdir -p "${HOME}/dangling"; printf 'gitdir: %s/nowhere\n' "${HOME}" > "${HOME}/dangling/.git"
mkdir -p "${HOME}/linkgit"; ln -s "${HOME}/main/.git" "${HOME}/linkgit/.git"
git init -q "${STATE}/smain"; commit "${STATE}/smain"; git -C "${STATE}/smain" worktree add -q "${HOME}/swt" -b sfeat   # main inside the session root
mkdir -p "${HOME}/parent"; git init -q "${HOME}/parent/repo"; commit "${HOME}/parent/repo"; git -C "${HOME}/parent/repo" worktree add -q "${HOME}/parent/wt2" -b p2

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running
LAST_OUT="${WORK}/last.out"
resolves_to() { local got; got="$(worktree_common_dir "$1" 2>"${LAST_OUT}")" && [[ "${got}" == "$2" ]]; }
refused() { ! ( worktree_common_dir "$1" ) >/dev/null 2>"${LAST_OUT}"; }   # subshell: die() exits the caller otherwise
refused_with() { refused "$1" && grep -q -- "$2" "${LAST_OUT}"; }   # $2 = wording the refusal must carry

# === 1. Resolution ==========================================================
check "worktree: a linked worktree resolves to its main repository's common dir" resolves_to "${HOME}/wt" "${HOME}/main/.git"
check "worktree: a .git directory root needs no common dir" resolves_to "${HOME}/main" ""
check "worktree: a separate-git-dir checkout with core.worktree resolves to its git dir" resolves_to "${HOME}/sep" "${HOME}/sepgit"
check "worktree: a bare repository's worktree resolves to the bare common dir" resolves_to "${HOME}/bwt" "${HOME}/bare.git"

# === 2. Refusals: the pointer alone is never trusted ========================
check "worktree: a planted pointer without a back-link is refused" refused "${HOME}/planted"
planted_named() { refused_with "${HOME}/planted" 'links back to' && grep -q "${HOME}/wt/.git" "${LAST_OUT}" && grep -q 'does not belong' "${LAST_OUT}"; }
check "worktree: the planted refusal names the mismatch" planted_named
dangling_named() { refused_with "${HOME}/dangling" 'cannot resolve' && grep -q "gitdir: ${HOME}/nowhere" "${LAST_OUT}"; }
check "worktree: a pointer git cannot resolve is refused, naming the pointer" dangling_named
check "worktree: a separate-git-dir checkout without core.worktree is refused with the fix" refused_with "${HOME}/sep2" "git -C ${HOME}/sep2 config core.worktree ${HOME}/sep2"
check "worktree: a symlinked .git is refused" refused_with "${HOME}/linkgit" 'symbolic link'
check "worktree: a sensitive common dir is refused" refused_with "${HOME}/swt" 'sensitive host path'
unsafe_still_refused() { ! ( export TJOR_UNSAFE_DIR=1; worktree_common_dir "${HOME}/swt" ) >/dev/null 2>"${LAST_OUT}"; grep -q 'no override' "${LAST_OUT}"; }
check "worktree: --unsafe-dir does not override a sensitive common dir" unsafe_still_refused

# === 3. Wiring: the lists the mounts are built from =========================
# shellcheck disable=SC2034  # the globals are read by worktree_common_dirs
lists_after() { # $1 = workspace, $2 = --dir list (comma), $3 = --dir-ro list (comma) → prints "rw:<...>|ro:<...>"
    ( TJOR_WORKSPACE="$1"; IFS=, read -r -a TJOR_EXTRA_DIRS <<<"$2"; IFS=, read -r -a TJOR_EXTRA_DIRS_RO <<<"$3"
      worktree_common_dirs 2>"${LAST_OUT}"; printf 'rw:%s|ro:%s' "${TJOR_EXTRA_DIRS[*]:-}" "${TJOR_EXTRA_DIRS_RO[*]:-}" )
}
check "worktree: a common dir under an existing root adds no mount" test "$(lists_after "${HOME}/parent" "" "")" = "rw:|ro:"
ws_appended() { [[ "$(lists_after "${HOME}/wt" "" "")" == "rw:${HOME}/main/.git|ro:" ]] && grep -q "+ worktree common dir ${HOME}/main/.git (for ${HOME}/wt; mounted writable" "${LAST_OUT}"; }
check "worktree: the workspace's common dir is appended writable and announced" ws_appended
check "worktree: a shared common dir mounts once, writable" test "$(lists_after "${HOME}/wt" "" "${HOME}/wt3")" = "rw:${HOME}/main/.git|ro:${HOME}/wt3"
check "worktree: a read-only worktree's common dir is appended read-only" test "$(lists_after "${HOME}/sep" "" "${HOME}/bwt")" = "rw:${HOME}/sepgit|ro:${HOME}/bwt ${HOME}/bare.git"
ro_parent_warns() { [[ "$(lists_after "${HOME}/wt" "" "${HOME}/main")" == "rw:|ro:${HOME}/main" ]] && grep -q 'READ-ONLY mount root' "${LAST_OUT}"; }
check "worktree: a writable worktree under a read-only root warns and adds nothing" ro_parent_warns

# === 4. cmd_run: the resolver runs before docker ============================
run_from() { ( cd "$1" && cmd_run "${@:2}" ) >/dev/null 2>"${LAST_OUT}" || true; }
rm -f "${WORK}/docker_reached"; run_from "${HOME}/wt"
launch_passed() { grep -q "+ worktree common dir ${HOME}/main/.git" "${LAST_OUT}" && test -e "${WORK}/docker_reached"; }
check "worktree: launch from a worktree passes the resolver (announce, then docker reached)" launch_passed
rm -f "${WORK}/docker_reached"; run_from "${HOME}/planted"
launch_refused() { grep -q 'links back to' "${LAST_OUT}" && test ! -e "${WORK}/docker_reached"; }
check "worktree: launch from a planted pointer is refused before docker" launch_refused

# === 5. Masks: a root that IS a git dir is masked as one ====================
# shellcheck disable=SC2034  # the arrays are read by plan_git_masks through dynamic scoping
plan_masks() { ( safe=("$@"); ro_dirs=""; declare -A masked=() dirmasked=(); mounts=(); empty_src="${WORK}/empty"; mkdir -p "${empty_src}"; TJOR_SESSION_DIR="${STATE}/x"; plan_git_masks; printf '%s\n' "${mounts[@]}" ); }
bare_masked() { local out; out="$(plan_masks "${HOME}/bwt" "${HOME}/bare.git" 2>/dev/null)"; grep -q ":${HOME}/bare.git/hooks:ro" <<<"${out}"; }
check "git hooks: a bare-named git-dir root has its hooks masked" bare_masked
dotgit_root_once() { local out; out="$(plan_masks "${HOME}/wt" "${HOME}/main/.git" 2>/dev/null)"; [[ "$(grep -c ":${HOME}/main/.git/hooks:ro" <<<"${out}")" == 1 ]]; }
check "git hooks: a .git-named common dir root is masked exactly once" dotgit_root_once

echo
echo "worktree: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
