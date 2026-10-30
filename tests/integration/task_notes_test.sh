#!/usr/bin/env bash
# Task notes (#69, spec: task-notes), no docker required. Sources bin/tjor
# for its functions (source-guard) and drives resolve_session / cmd_run /
# task_notes_prepare / task_notes_probe / cmd_attach under a throwaway host
# layout — a code repo, a NOTES repo holding the per-task directories, a
# custom session.root, a custom XDG config dir — asserting: the notes
# directory resolves from the user config only, with no side effect, and is
# created on the launch path after the sensitive gate and under the lock;
# the task id grammar once it names a directory or a session; the notes
# repository can never be the workspace (by identity, no override); the
# derived per-task session name round-trips through the lifecycle resolver
# and the ids it would misread are refused; coverage by a writable root;
# the advisory credential scan; the probe-file share check's contract; and
# that nothing changes without a [task] table. A docker shim on PATH records
# every call and answers per a mode file; reaching it where a refusal must
# already have happened is itself a failure. The `check "…"` names below are
# literal: they feed the boundary matrix (python/gen_boundary_matrix.py) as
# the launcher-side `task-notes` suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

# Scratch under the REAL home (a macOS mktemp dir resolves to /private/var,
# which the sensitive-path gate refuses); physical spelling; git discovery
# capped at the scratch dir.
WORK="${HOME}/.tjor/tmp/tasknotes-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
trap 'rm -rf "${WORK:?}"' EXIT
export GIT_CEILING_DIRECTORIES="${WORK}"

# The docker shim: records every call; `ps` answers per the mode file
# (absent → fail loudly), `run` answers the probe per the same file.
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
cat >"${MOCKBIN}/docker" <<SHIM
#!/usr/bin/env bash
printf '%s\\n' "docker \$*" >> "${WORK}/docker_log"
mode="\$(cat "${WORK}/shim_mode" 2>/dev/null || echo fail)"
case "\$1" in
  ps)  case "\${mode}" in
         rows) cat "${WORK}/shim_rows" ;;
         ps-id) echo abc123def456 ;;
         fail) exit 1 ;;
         *) : ;;
       esac; exit 0 ;;
  run) [[ "\${mode}" == probe-seen ]] && exit 0; exit 1 ;;
esac
exit 1
SHIM
chmod +x "${MOCKBIN}/docker"
# An fzf shim: the picker must never wait on a terminal here; "nothing
# selected" is the non-interactive outcome of offering the picker.
printf '#!/usr/bin/env bash\ncat >/dev/null; exit 130\n' > "${MOCKBIN}/fzf"; chmod +x "${MOCKBIN}/fzf"
export PATH="${MOCKBIN}:${PATH}"
shim_mode() { printf '%s' "$1" > "${WORK}/shim_mode"; }
shim_mode fail

export HOME="${WORK}/home"
mkdir -p "${HOME}/proj" "${HOME}/proj2" "${HOME}/scratch/tasks" "${HOME}/.ssh"
git -C "${HOME}/proj" init -q
git -C "${HOME}/proj2" init -q
git -C "${HOME}/scratch" init -q          # the NOTES repository, holding tasks/<id>
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
export TJOR_TRUST_STORE="${WORK}/trusted.toml"
STATE="${WORK}/state/sessions"; mkdir -p "${STATE}"
NOTES="${HOME}/scratch/tasks"
CFG_DEFAULT=$'[task]\nnotes_dir = "~/scratch/tasks/{task}"\ncreate = true\nsession_per_task = true'
write_cfg() { # $1 = the [task] table (may be empty)
    printf '[session]\nroot = "%s"\n%s\n' "${STATE}" "$1" > "${XDG_CONFIG_HOME}/tjor/config.toml"
}
write_cfg "${CFG_DEFAULT}"
unset TJOR_USER_CONFIG TJOR_UNSAFE_DIR TJOR_REPO_ROOT

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

LAST_OUT="${WORK}/last.out"; LAST_VAL="${WORK}/last.val"
hash8() { if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8; else printf %s "$1" | shasum -a 256 | cut -c1-8; fi; }
BASE="proj-$(hash8 "${HOME}/proj")"
# resolve_session on the LAUNCH path: $1 dir, $2 task, $3 session name → LAST_VAL = id|task|dir
launch_from() { ( cd "$1" && resolve_session opencode "${2:-}" "${3:-}" launch && printf '%s|%s|%s' "${TJOR_SESSION_ID}" "${TJOR_TASK_ID}" "${TJOR_TASK_DIR}" > "${LAST_VAL}" ) >/dev/null 2>"${LAST_OUT}"; }
refused()     { ! launch_from "$@"; }
launch_val()  { launch_from "$1" "$2" "$3" && val_is "$4"; }
# lifecycle resolution (no task, no launch marker): $1 dir, $2 session value → LAST_VAL = id|dir
lifecycle()   { ( cd "$1" && resolve_session opencode "" "${2:-}" && printf '%s|%s' "${TJOR_SESSION_ID}" "${TJOR_TASK_DIR}" > "${LAST_VAL}" ) >/dev/null 2>"${LAST_OUT}"; }
lifecycle_refused() { ! lifecycle "$@"; }
lifecycle_val() { lifecycle "$1" "$2" && val_is "$3"; }
val_is()      { [[ "$(cat "${LAST_VAL}")" == "$1" ]]; }
out_has()     { grep -qF -- "$1" "${LAST_OUT}"; }
out_lacks()   { ! grep -qF -- "$1" "${LAST_OUT}"; }
# cmd_run from a directory with the given flags; stderr → LAST_OUT.
run_from()    { ( cd "$1" && shift && cmd_run "$@" ) >/dev/null 2>"${LAST_OUT}"; }
refused_run() { ! run_from "$@"; }
# task_notes_prepare after a launch-path resolution with given extra roots:
# $1 dir, $2 task, then "rw:<path>" / "ro:<path>" entries → LAST_VAL = the writable extras
prepare_from() {
    local dir="$1" task="$2"; shift 2
    ( cd "${dir}" && resolve_session opencode "${task}" "" launch >/dev/null
      TJOR_EXTRA_DIRS=(); TJOR_EXTRA_DIRS_RO=()
      local e; for e in "$@"; do case "${e}" in rw:*) TJOR_EXTRA_DIRS+=("${e#rw:}") ;; ro:*) TJOR_EXTRA_DIRS_RO+=("${e#ro:}") ;; esac; done
      task_notes_prepare && printf '%s' "${TJOR_EXTRA_DIRS[*]:-}" > "${LAST_VAL}" ) >/dev/null 2>"${LAST_OUT}"
}
prepare_refused() { ! prepare_from "$@"; }
prepare_val() { local dir="$1" task="$2" want="$3"; shift 3; prepare_from "${dir}" "${task}" "$@" && val_is "${want}"; }
state_root_empty() { [[ -z "$(ls -A "${STATE}" 2>/dev/null)" ]]; }
no_session_state() { local d; for d in "${STATE}/${BASE}"*/; do [[ -e "${d}" ]] && return 1; done; return 0; }   # the root and its lock may exist; no session dir
never_reached_docker() { [[ ! -e "${WORK}/docker_log" ]]; }
reset_docker_log() { rm -f "${WORK:?}/docker_log"; }
docker_log_has() { grep -qF -- "$1" "${WORK}/docker_log"; }
real_dir() { [[ -d "$1" && ! -L "$1" ]]; }
absent() { [[ ! -e "$1" ]]; }

# === 1. Resolution: user config, no side effect, the grammar =================
check "task notes: --task resolves the directory from the template, with no side effect" launch_val "${HOME}/proj" a "" "${BASE}-a|a|${NOTES}/a"
check "task notes: resolution created no directory" absent "${NOTES}/a"
check "task notes: the launch names the per-task session and how to address it" out_has "session a for task a (address it with --session a)"
check "task notes: no state dir is created by resolution" state_root_empty
check "task notes: an upper-case id is refused once it names a directory" refused "${HOME}/proj" JIRA-1
check "task notes: the refusal names the grammar" out_has "must match [a-z0-9][a-z0-9_-]{0,31}"
check "task notes: a dot-leading id is refused" refused "${HOME}/proj" .notes
check "task notes: '..' as a task id is refused" refused "${HOME}/proj" ..
check "task notes: a 33-character id is refused" refused "${HOME}/proj" "$(printf 'a%.0s' $(seq 1 33))"
check "task notes: a dotted id is refused" refused "${HOME}/proj" a.b
check "task notes: no directory was created by any refusal" test -z "$(ls -A "${NOTES}")"
check "task notes: refusals never reached docker" never_reached_docker

# === 2. The notes repository never becomes the workspace ====================
mkdir -p "${NOTES}/a"
check "task notes: launching from inside the notes repository is refused" refused "${NOTES}/a" a
check "task notes: the refusal names the workspace and the notes root" out_has "the workspace ${HOME}/scratch is the notes root ${NOTES} or contains it"
check "task notes: the refusal points at launching from the code repository" out_has "launch from the code repository"
check "task notes: launching from the notes repository root is refused" refused "${HOME}/scratch" a
check "task notes: no state dir after the notes-root refusals" state_root_empty
mkdir -p "${NOTES}/a/repo"; git -C "${NOTES}/a/repo" init -q
check "task notes: a workspace below the notes root is not an ancestor and launches" launch_from "${NOTES}/a/repo" a
rm -rf "${NOTES:?}/a"
ln -s "${HOME}/scratch" "${HOME}/alias"
check "task notes: another spelling of the notes repository (a link) is refused by identity" refused "${HOME}/alias" a
# The helper answers "not contained" with exit 3, never 1: a helper that dies
# before answering (an import failure, a crash outside its main) exits 1 with
# Python's own code, and both callers — the notes-root check at resolution
# and the coverage check in prepare — must read that as "cannot tell" and
# refuse. A sabotaged tree answers everything for real except the one
# `contains` call whose path SABOTAGE_ON names, where it dies.
SABOTAGE="${WORK}/sabotage"; mkdir -p "${SABOTAGE}"
for entry in "${ROOT}"/* "${ROOT}"/.[!.]*; do [[ -e "${entry}" && "$(basename "${entry}")" != python ]] && ln -s "${entry}" "${SABOTAGE}/"; done
cp -R "${ROOT}/python" "${SABOTAGE}/python"
cat > "${SABOTAGE}/python/tjor_task.py" <<PY
import os, sys
if sys.argv[1:2] == ["contains"] and sys.argv[3:4] == [os.environ.get("SABOTAGE_ON")]:
    sys.exit(1)          # a crash before any answer: Python's own exit code, no message
os.execv(sys.executable, [sys.executable, "${ROOT}/python/tjor_task.py", *sys.argv[1:]])
PY
REAL_ROOT="${TJOR_ROOT}"; TJOR_ROOT="${SABOTAGE}"
export SABOTAGE_ON="${NOTES}"
check "task notes: a notes-root check whose helper dies with exit 1 refuses the launch" refused "${HOME}/proj" a
check "task notes: the dead-helper refusal says it cannot tell, not that the workspace is clear" out_has "cannot establish whether the workspace ${HOME}/proj contains the notes root"
check "task notes: the dead-helper refusal at resolution created no notes directory" absent "${NOTES}/a"
export SABOTAGE_ON="${NOTES}/a"
check "task notes: a coverage check whose helper dies with exit 1 refuses the launch" prepare_refused "${HOME}/proj" a
check "task notes: the dead-helper coverage refusal says it cannot tell, not that the root is clear" out_has "cannot establish whether ${HOME}/proj covers ${NOTES}/a"
unset SABOTAGE_ON; TJOR_ROOT="${REAL_ROOT}"; rm -rf "${SABOTAGE:?}"
check "task notes: with the real helper the same resolution passes" launch_from "${HOME}/proj" a
rm -rf "${NOTES:?}/a"   # prepare creates the directory before its coverage check; the sections below expect none
rm -f "${HOME:?}/alias"

# === 3. Round trip: the derived name and what the resolver would misread ====
check "task notes: --task <base id> is refused (it reads as the default session)" refused "${HOME}/proj" "${BASE}"
check "task notes: --task <base id>-x is refused (it reads as a qualified id)" refused "${HOME}/proj" "${BASE}-x"
check "task notes: the round-trip refusal names tjor down --session" out_has "tjor down --session"
mkdir -p "${STATE}/bug-12345678"
check "task notes: a qualified-looking id naming an existing session's state dir is refused" refused "${HOME}/proj" bug-12345678
check "task notes: that refusal never asked docker (the state dir decided)" never_reached_docker
rm -rf "${STATE:?}/bug-12345678"
shim_mode ps-id
check "task notes: a qualified-looking id naming a labelled container is refused" refused "${HOME}/proj" bug-12345678
check "task notes: the container lookup went through docker ps" docker_log_has "docker ps -aq --filter label=tjor.session=bug-12345678"
shim_mode fail; reset_docker_log
check "task notes: a qualified-looking id with Docker unreachable is refused, not guessed" refused "${HOME}/proj" bug-12345678
check "task notes: the unreachable-engine refusal says so" out_has "Docker is unreachable"
shim_mode ps-empty
check "task notes: a qualified-looking id no session uses launches" launch_val "${HOME}/proj" bug-12345678 "" "${BASE}-bug-12345678|bug-12345678|${NOTES}/bug-12345678"
reset_docker_log
check "task notes: a plain id never consults docker" launch_from "${HOME}/proj" plain-one
check "task notes: no docker call for the plain id" never_reached_docker
check "task notes: the lifecycle resolver reads the derived name back as the same session" lifecycle_val "${HOME}/proj" bug-12345678 "${BASE}-bug-12345678|"
check "task notes: the resolver's qualified-looking notice is printed for it" out_has "looks like a fully-qualified session id, but no such session exists"
mkdir -p "${STATE}/${BASE}-bug-12345678" "${STATE}/bug-12345678"      # a foreign session with that full id appears LATER
check "task notes: a collision that appears later is refused as ambiguous" lifecycle_refused "${HOME}/proj" bug-12345678
check "task notes: the ambiguity refusal says so" out_has "is ambiguous"
check "task notes: the ambiguity refusal names this workspace's full id" out_has "${BASE}-bug-12345678"
rm -rf "${STATE:?}/${BASE}-bug-12345678"
check "task notes: with only the foreign session present the full id is used verbatim" lifecycle_val "${HOME}/proj" bug-12345678 "bug-12345678|"
rm -rf "${STATE:?}/bug-12345678"
check "task notes: --session names the session and --task stays the label and directory" launch_val "${HOME}/proj" a rev "${BASE}-rev|a|${NOTES}/a"
shim_mode fail; reset_docker_log

# === 4. Nothing changes without a [task] table; session_per_task alone ======
write_cfg ""
check "task notes: without [task] a label-only id keeps the old grammar" launch_val "${HOME}/proj" JIRA-1 "" "${BASE}|JIRA-1|"
check "task notes: without [task] a dot-leading label is still accepted" launch_val "${HOME}/proj" .x "" "${BASE}|.x|"
write_cfg $'[task]\nsession_per_task = true'
check "task notes: session_per_task alone applies the grammar and derives the name, mounts nothing" launch_val "${HOME}/proj" a "" "${BASE}-a|a|"
check "task notes: session_per_task alone still refuses an upper-case id" refused "${HOME}/proj" JIRA-1
write_cfg "${CFG_DEFAULT}"

# === 5. Configuration provenance (ADR 0013) through the launcher ============
mkdir -p "${HOME}/proj/.tjor"
printf '[task]\nnotes_dir = "~/Documents/{task}"\n' > "${HOME}/proj/.tjor/config.toml"
python3 "${ROOT}/python/tjor_trust.py" approve "${HOME}/proj/.tjor/config.toml" >/dev/null
check "task notes: a TRUSTED repo config cannot move the notes directory" launch_val "${HOME}/proj" a "" "${BASE}-a|a|${NOTES}/a"
check "task notes: the repo config's [task] table is reported as ignored" out_has "user-config only"
rm -rf "${HOME:?}/proj/.tjor"

# === 6. The template =========================================================
write_cfg $'[task]\nnotes_dir = "scratch/tasks/{task}"'
check "task notes: a relative template is refused" refused "${HOME}/proj" a
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks"'
check "task notes: a template without the placeholder is refused" refused "${HOME}/proj" a
write_cfg $'[task]\nnotes_dir = "~/scratch/{task}/{task}"'
check "task notes: a template with the placeholder twice is refused" refused "${HOME}/proj" a
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks/{task}/../x"'
check "task notes: a template with a dot-dot component is refused" refused "${HOME}/proj" a
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks/{task}/"'
check "task notes: a template with a trailing separator is refused" refused "${HOME}/proj" a
write_cfg $'[task]\nnotes_dir = "~/scratch/nope/{task}"'
check "task notes: a template whose root does not exist is refused" refused "${HOME}/proj" a
check "task notes: the root is never created by tjor" absent "${HOME}/scratch/nope"
check "task notes: a malformed template leaves no directory" test -z "$(ls -A "${NOTES}")"
write_cfg "${CFG_DEFAULT}"

# === 7. The launch path: gate, create, coverage, mount, scan ================
write_cfg $'[task]\nnotes_dir = "~/.ssh/{task}"'
check "task notes: a sensitive template is refused by the --dir gate before anything is created" refused_run "${HOME}/proj" --task a -- true
check "task notes: the gate refusal names the sensitive path" out_has "refusing to mount sensitive host path into the agent: ${HOME}/.ssh/a "
check "task notes: the gate refusal created nothing" absent "${HOME}/.ssh/a"
check "task notes: the gate refusal left no session state dir" no_session_state
write_cfg "${CFG_DEFAULT}"
check "task notes: prepare creates the directory and appends it to the writable extras once" prepare_val "${HOME}/proj" a "${NOTES}/a"
check "task notes: the created directory is real" real_dir "${NOTES}/a"
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks/{task}/notes"'
check "task notes: the directory is created component by component below the root" prepare_val "${HOME}/proj" b "${NOTES}/b/notes"
check "task notes: both components are real directories" real_dir "${NOTES}/b/notes"
write_cfg "${CFG_DEFAULT}"
check "task notes: an equal --dir is not appended twice" prepare_val "${HOME}/proj" a "${NOTES}/a" rw:"${NOTES}/a"
check "task notes: a directory covered by a --dir root is mounted with it, not again" prepare_val "${HOME}/proj" a "${HOME}/scratch" rw:"${HOME}/scratch"
check "task notes: the covered case says which root covers it" out_has "lie under the writable root ${HOME}/scratch"
write_cfg $'[task]\nnotes_dir = "~/proj/notes/{task}"'
mkdir -p "${HOME}/proj/notes"
check "task notes: a notes root inside the workspace is the notes-root refusal (the code repo would be the notes repo)" refused "${HOME}/proj" c
check "task notes: that refusal names the workspace as containing the notes root" out_has "is the notes root ${HOME}/proj/notes or contains it"
rm -rf "${HOME:?}/proj/notes"
write_cfg "${CFG_DEFAULT}"
check "task notes: the same path via --dir-ro is a writability conflict" prepare_refused "${HOME}/proj" a ro:"${NOTES}/a"
check "task notes: the conflict names --dir-ro" out_has "also given via --dir-ro"
ln -s "${HOME}/proj2" "${NOTES}/linked"
check "task notes: a symbolic link at the task directory is refused" prepare_refused "${HOME}/proj" linked
check "task notes: the link refusal names it" out_has "${NOTES}/linked is a symbolic link"
check "task notes: nothing was created through the link" absent "${HOME}/proj2/notes"
rm -f "${NOTES:?}/linked"
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks/{task}"\ncreate = false'
check "task notes: create = false refuses a missing directory" prepare_refused "${HOME}/proj" missing
check "task notes: the create=false refusal names task.create" out_has "task.create is false"
check "task notes: create = false accepts an existing directory" prepare_val "${HOME}/proj" a "${NOTES}/a"
write_cfg "${CFG_DEFAULT}"
check "task notes: lifecycle resolution creates nothing" lifecycle "${HOME}/proj" zz
check "task notes: no directory after a lifecycle resolution" absent "${NOTES}/zz"
printf 'x' > "${NOTES}/a/deploy.pem"; printf 'token: ghp_%s\n' "$(printf 'a%.0s' $(seq 1 36))" > "${NOTES}/a/notes.md"
check "task notes: credential-shaped files produce a loud warning and the launch continues" prepare_from "${HOME}/proj" a
check "task notes: the warning counts the findings" out_has "credential-shaped file(s)"
check "task notes: the warning names the key file" out_has "deploy.pem"
check "task notes: the warning names the file whose content looks like a token" out_has "notes.md"
mkfifo "${NOTES}/a/pipe.key"
check "task notes: a FIFO does not block the scan" prepare_from "${HOME}/proj" a
check "task notes: the scan says it was partial and names the FIFO" out_has "pipe.key"
check "task notes: the partial notice is loud" out_has "PARTIAL"
rm -f "${NOTES:?}/a/pipe.key" "${NOTES:?}/a/deploy.pem" "${NOTES:?}/a/notes.md"

# === 8. The probe-file share check (run_agent) =============================
probe_with() { # $1 = shim mode → runs task_notes_probe on tasks/a; stderr → LAST_OUT
    shim_mode "$1"; reset_docker_log
    ( export TJOR_PROXY_IMAGE="proxy:test"; task_notes_probe "${NOTES}/a" ) >/dev/null 2>"${LAST_OUT}"
}
probe_refused() { ! probe_with "$1"; }
no_probe_left() { [[ -z "$(find "${NOTES}/a" -name '.tjor-share-probe-*' -print -quit)" ]]; }
probe_line() { grep '^docker run ' "${WORK}/docker_log" | tail -1; }
check "task notes: a probe the container does not see refuses the launch" probe_refused probe-unseen
check "task notes: the share refusal names the directory" out_has "${NOTES}/a is not shared with the Docker VM"
check "task notes: the share refusal names the remedy" out_has "shared paths"
check "task notes: the probe file is removed after a refusal" no_probe_left
check "task notes: a probe the container sees passes" probe_with probe-seen
check "task notes: the probe file is removed after a pass" no_probe_left
check "task notes: the probe container has no network" grep -qF -- '--network none' <<<"$(probe_line)"
check "task notes: the probe container runs a plain shell entrypoint" grep -qF -- '--entrypoint /bin/sh ' <<<"$(probe_line)"
check "task notes: the probe runs on the pinned proxy image" grep -qF -- ' proxy:test -c ' <<<"$(probe_line)"
check "task notes: the probe binds the notes directory read-only" grep -qF -- "--mount type=bind,src=${NOTES}/a,dst=/check,readonly" <<<"$(probe_line)"
probe_flags() { probe_line | sed 's/ proxy:test -c .*$//'; }   # the docker options only, before the image
check "task notes: the probe binds nothing else" bash -c "[[ \$(grep -o -- '--mount' <<<\"\$1\" | wc -l) -eq 1 ]] && ! grep -qE -- '--volume|(^| )-v ' <<<\"\$1\"" _ "$(probe_flags)"
check "task notes: the probe passes no environment and no socket" bash -c "! grep -qE -- '(^| )-e |--env|docker.sock' <<<\"\$1\"" _ "$(probe_flags)"
check "task notes: the probe name is a trailing argument, never inside the shell string" grep -qE -- '-c test -e "/check/\$1" sh \.tjor-share-probe-[0-9a-f]{16}$' <<<"$(probe_line)"
shim_mode fail; reset_docker_log

# === 9. attach --task ========================================================
printf 'c1\x1f%s-a\x1f%s/proj\x1fa\nc2\x1f%s-b\x1f%s/proj\x1fb\n' "${BASE}" "${HOME}" "${BASE}" "${HOME}" > "${WORK}/shim_rows"
shim_mode rows
attach_dry() { ( cd "${HOME}/proj" && TJOR_ATTACH_DRY=1 cmd_attach "$@" ) >"${LAST_VAL}" 2>"${LAST_OUT}" </dev/null; }
attach_refused() { ! attach_dry "$@"; }
check "task notes: attach --task picks the agent carrying that task label" attach_dry --task b
check "task notes: attach --task resolved the right container" val_is "${BASE}-b c2"
check "task notes: attach --task with no such agent exits non-zero" attach_refused --task zzz
check "task notes: attach --task with no such agent says so" out_has "no running agent for task zzz"
printf 'c1\x1f%s-a\x1f%s/proj\x1fa\nc3\x1fother-deadbeef-a\x1f%s/proj2\x1fa\n' "${BASE}" "${HOME}" "${HOME}" > "${WORK}/shim_rows"
check "task notes: the same task id in two repositories offers the picker" attach_refused --task a
check "task notes: the picker, declined, selects nothing" out_has "nothing selected"
check "task notes: attach --task without a value is a usage error" attach_refused --task
check "task notes: the usage error says the value is needed" out_has "needs a value"
check "task notes: attach with a session and --task is a usage error" attach_refused foo --task b
check "task notes: the usage error says not both" out_has "not both"
shim_mode fail

# === 10. Help text ===========================================================
check "task notes: help text names the per-task notes directory" bash -c "'${ROOT}/bin/tjor' help | grep -qF 'per-task notes directory'"
check "task notes: help text names attach --task" bash -c "'${ROOT}/bin/tjor' help | grep -qF 'attach [session | --task <id>]'"

echo "----"
echo "task-notes: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
