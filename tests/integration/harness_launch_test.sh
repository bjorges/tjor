#!/usr/bin/env bash
# Task-aware harness launch (#73, spec: harness-launch), no docker required.
# Sources bin/tjor for its functions (source-guard) and drives
# resolve_session / agent_cmd_select / build_agent_cmd / cmd_run under a
# throwaway host layout — a code repo, a notes root, a custom session.root,
# a custom XDG config dir — asserting: the harness name is one of three; an
# explicit command replaces everything; [harness.<name>] args come from the
# user config only and pass verbatim, uninspected beyond the exact same-launch
# collision rule; the task prompt renders from two placeholders with brace
# escapes and is delivered in the one form each harness reads as data; resume
# is decided from tjor's own launch record (absent, matching, other task,
# other harness, --no-resume, unreadable), never from the harness's store;
# the record's parent is never agent-writable; and every refusal creates
# nothing. A docker shim on PATH records every call and FAILS it: reaching
# docker where a refusal must already have happened is itself a failure. The
# `check "…"` names below are literal: they feed the boundary matrix
# (python/gen_boundary_matrix.py) as the launcher-side `harness-launch` suite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

WORK="${HOME}/.tjor/tmp/harnesslaunch-$$"; mkdir -p "${WORK}"; WORK="$(cd "${WORK}" && pwd -P)"
trap 'rm -rf "${WORK:?}"' EXIT
export GIT_CEILING_DIRECTORIES="${WORK}"

# The docker shim: records every call and fails it.
MOCKBIN="${WORK}/bin"; mkdir -p "${MOCKBIN}"
cat >"${MOCKBIN}/docker" <<SHIM
#!/usr/bin/env bash
printf '%s\\n' "docker \$*" >> "${WORK}/docker_log"
exit 1
SHIM
chmod +x "${MOCKBIN}/docker"
export PATH="${MOCKBIN}:${PATH}"

export HOME="${WORK}/home"
mkdir -p "${HOME}/proj" "${HOME}/scratch/tasks" "${HOME}/data"
git -C "${HOME}/proj" init -q
export XDG_CONFIG_HOME="${WORK}/xdg"; mkdir -p "${XDG_CONFIG_HOME}/tjor"
export TJOR_TRUST_STORE="${WORK}/trusted.toml"
STATE="${WORK}/state/sessions"; mkdir -p "${STATE}"
NOTES="${HOME}/scratch/tasks"
write_cfg() { # $1 = extra tables (may be empty); the session root is always ours
    printf '[session]\nroot = "%s"\n%s\n' "${STATE}" "$1" > "${XDG_CONFIG_HOME}/tjor/config.toml"
}
PROMPT_CFG=$'[task]\nprompt = "Task {task} begins."\nresume = "auto"'
write_cfg "${PROMPT_CFG}"
unset TJOR_USER_CONFIG TJOR_UNSAFE_DIR TJOR_REPO_ROOT

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

LAST_OUT="${WORK}/last.out"; LAST_CMD="${WORK}/last.cmd"; LAST_NOTE="${WORK}/last.note"; LAST_SHOW="${WORK}/last.show"; LAST_REC="${WORK}/last.rec"
hash8() { if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8; else printf %s "$1" | shasum -a 256 | cut -c1-8; fi; }
BASE="proj-$(hash8 "${HOME}/proj")"
SDIR="${STATE}/${BASE}"
# The builder, as cmd_run reaches it: $1 harness, $2 task id, $3 "1" for
# --no-resume, then rw:<path> writable extras; the explicit command, if any,
# after "--". Writes the NUL-separated command, the note, the launch line and
# the record flag.
build_from() {
    local harness="$1" task="$2" nr="$3"; shift 3
    local -a extras=() explicit=()
    local -a extras_ro=()
    while [[ $# -gt 0 ]]; do case "$1" in rw:*) extras+=("${1#rw:}") ;; ro:*) extras_ro+=("${1#ro:}") ;; --) shift; explicit=("$@"); break ;; esac; shift; done
    ( cd "${HOME}/proj" && resolve_session "${harness}" "${task}" "" launch >/dev/null
      mkdir -p "${TJOR_SESSION_ROOT}"; TJOR_LOCK_ROOT="$(cd "${TJOR_SESSION_ROOT}" && pwd -P)"; export TJOR_LOCK_ROOT
      TJOR_EXTRA_DIRS=(); TJOR_EXTRA_DIRS_RO=()
      local e; for e in ${extras[@]+"${extras[@]}"}; do TJOR_EXTRA_DIRS+=("${e}"); done
      for e in ${extras_ro[@]+"${extras_ro[@]}"}; do TJOR_EXTRA_DIRS_RO+=("${e}"); done
      agent_cmd_select "${harness}" "${nr}" ${explicit[@]+"${explicit[@]}"} \
        && agent_cmd_print > "${LAST_CMD}" && printf '%s' "${AGENT_CMD_NOTE}" > "${LAST_NOTE}" \
        && printf '%s' "${AGENT_CMD_SHOW}" > "${LAST_SHOW}" && printf '%s' "${AGENT_CMD_RECORD}" > "${LAST_REC}" ) >/dev/null 2>"${LAST_OUT}"
}
build_refused() { ! build_from "$@"; }
cmd_is()   { cmp -s <(printf '%s\0' "$@") "${LAST_CMD}"; }
note_has() { grep -qF -- "$1" "${LAST_NOTE}"; }
show_is()  { [[ "$(cat "${LAST_SHOW}")" == "$1" ]]; }
show_has() { grep -qF -- "$1" "${LAST_SHOW}"; }
show_lacks() { ! grep -qF -- "$1" "${LAST_SHOW}"; }
rec_flag() { [[ "$(cat "${LAST_REC}")" == "$1" ]]; }
out_has()  { grep -qF -- "$1" "${LAST_OUT}"; }
# cmd_run from the repo with the given flags; stderr → LAST_OUT (the full
# launch path: every refusal here must happen before anything is created).
run_from()    { ( cd "${HOME}/proj" && cmd_run "$@" ) >/dev/null 2>"${LAST_OUT}"; }
refused_run() { ! run_from "$@"; }
no_session_state() { local d; for d in "${STATE}/${BASE}"*/; do [[ -e "${d}" ]] && return 1; done; return 0; }
no_state_under() { local d; for d in "$1"/*/; do [[ -e "${d}" ]] && return 1; done; return 0; }   # the lock dir (.locks) may exist
never_reached_docker() { [[ ! -e "${WORK}/docker_log" ]]; }
reset_docker_log() { rm -f "${WORK:?}/docker_log"; }
absent() { [[ ! -e "$1" ]]; }
seed_record() { # $1 harness, $2 task → the record in the shared session's state dir
    mkdir -p "${SDIR}"; python3 "${ROOT}/python/tjor_state.py" conversation-write "${SDIR}" --harness="$1" --task="$2"
}
clear_record() { rm -rf "${SDIR:?}"; }
snapshot() { ( cd "$1" && find . -print0 | sort -z | xargs -0 ls -ld --time-style=+%s 2>/dev/null || find . -print0 | sort -z | xargs -0 ls -ldT ) > "$2" 2>/dev/null; cat "${SDIR}/conversation.json" >> "$2" 2>/dev/null || true; }
unchanged() { snapshot "${SDIR}" "${WORK}/snap.after"; cmp -s "${WORK}/snap.before" "${WORK}/snap.after"; }

# === 1. The harness name, the explicit command, nothing without [task] ======
check "harness launch: --harness outside the three names is refused" refused_run --harness foo
check "harness launch: the refusal names the three harnesses" out_has "must be one of opencode, claude or copilot"
check "harness launch: an unknown harness created no session state" no_session_state
check "harness launch: an unknown harness never reached docker" never_reached_docker
check "harness launch: an explicit command replaces everything" build_from opencode a "" -- opencode --help
check "harness launch: the explicit command is passed as given" cmd_is opencode --help
check "harness launch: an explicit command writes no record" rec_flag ""
check "harness launch: the explicit command's note says nothing was added" note_has "explicit command, as given"
write_cfg ""
check "harness launch: without [task] the command is the bare harness" build_from opencode a ""
check "harness launch: the bare harness, nothing added" cmd_is opencode
check "harness launch: without [task] no record is written" rec_flag ""
check "harness launch: without [task] the note says fresh, no prompt" note_has "fresh, no prompt"
write_cfg "${PROMPT_CFG}"
check "harness launch: without --task a configured prompt is not sent" build_from claude "" ""
check "harness launch: the prompt-less command is the bare harness" cmd_is claude
check "harness launch: the record flag stays empty without a task" rec_flag ""

# === 2. Configured arguments: user config only, verbatim, uninspected =======
write_cfg $'[harness.opencode]\nargs = ["--agent", "bob", "a b", "-x"]'
check "harness launch: args pass verbatim, one argv element each, in order" build_from opencode "" ""
check "harness launch: the argv is harness then args" cmd_is opencode --agent bob "a b" -x
check "harness launch: the launch line shows the args" show_is "opencode --agent bob a b -x"
write_cfg $'[harness.claude]\nargs = ["--model", "opus"]\n[task]\nprompt = "Task {task} begins."'
check "harness launch: args precede what the launcher adds" build_from claude a ""
check "harness launch: claude gets args, then -- and the prompt" cmd_is claude --model opus -- "Task a begins."
check "harness launch: the launch line shows the prompt by length only" show_is "claude --model opus -- <prompt: 14 bytes>"
check "harness launch: the prompt text is not in the launch line" show_lacks "Task a begins"
write_cfg $'[harness.opencode]\nargs = ["a\\nb"]'
check "harness launch: an args entry with a newline is refused on the launch path" refused_run --task a
check "harness launch: the refusal names the entry and the rule" out_has "entry 1 holds a newline"
check "harness launch: the newline refusal created no session state" no_session_state
check "harness launch: the newline refusal never reached docker" never_reached_docker
write_cfg $'[harness.opencode]\nargs = [1]'
check "harness launch: a non-string entry is refused" build_refused opencode "" ""
write_cfg $'[harness.opencode]\nargs = ["--"]'
check "harness launch: a bare -- entry is refused" build_refused opencode "" ""
write_cfg $'[harness.opencode]\nargs = [""]'
check "harness launch: an empty entry is refused" build_refused opencode "" ""
write_cfg $'[harness.opencode]\nargs = ["--dangerously-skip-permissions", "--resume", "abc", "mcp", "-ic"]'
check "harness launch: args are not inspected beyond the collision rule" build_from opencode "" ""
check "harness launch: permission and conversation flags pass as the operator's own" cmd_is opencode --dangerously-skip-permissions --resume abc mcp -ic
write_cfg $'[harness.opencode]\nargs = ["--continue"]\n[task]\nresume = "auto"'
check "harness launch: an operator's --continue passes while tjor adds none" build_from opencode a ""
check "harness launch: that command carries the operator's flag once" cmd_is opencode --continue
seed_record opencode a
check "harness launch: an operator's --continue collides when tjor is adding it" build_refused opencode a ""
check "harness launch: the collision names the entry and task.resume" out_has "tjor is adding --continue"
clear_record
write_cfg $'[harness.opencode]\nargs = ["--prompt=x y"]\n[task]\nprompt = "Task {task} begins."'
check "harness launch: an operator's prompt flag collides when tjor is delivering the prompt" build_refused opencode a ""
check "harness launch: the prompt collision names task.prompt" out_has "delivering task.prompt"
check "harness launch: the same entry passes without --task (no prompt is being added)" build_from opencode "" ""
check "harness launch: the operator's prompt flag is then passed as given" cmd_is opencode "--prompt=x y"
mkdir -p "${HOME}/proj/.tjor"
printf '[harness.opencode]\nargs = ["--auto"]\n' > "${HOME}/proj/.tjor/config.toml"
python3 "${ROOT}/python/tjor_trust.py" approve "${HOME}/proj/.tjor/config.toml" >/dev/null
write_cfg $'[harness.opencode]\nargs = ["--agent", "bob"]'
check "harness launch: a TRUSTED repo config cannot set harness arguments" build_from opencode "" ""
check "harness launch: the user config's arguments are used instead" cmd_is opencode --agent bob
check "harness launch: the repo config's [harness] table is reported as user-config only" out_has "[harness]"
check "harness launch: the report names ADR 0014" out_has "ADR 0014"
rm -rf "${HOME:?}/proj/.tjor"
write_cfg $'[harness.claude]\narg = ["--model", "opus"]'
check "harness launch: a typo under a harness table aborts the launch" refused_run --task a
check "harness launch: the typo refusal names the key" out_has "harness.claude.arg"
check "harness launch: the typo refusal created nothing" no_session_state
write_cfg $'[harness.cluade]\nargs = ["--model", "opus"]'
check "harness launch: a misspelled nested harness table aborts the launch" refused_run --task a
check "harness launch: the nested typo refusal names the table" out_has "harness.cluade"
check "harness launch: refusals so far never reached docker" never_reached_docker

# === 3. The task prompt =======================================================
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks/{task}"\nprompt = "Task {task}. Notes: {task_dir}."'
check "harness launch: both placeholders render from the resolved task" build_from opencode a ""
check "harness launch: opencode gets the attached --prompt= form" cmd_is opencode "--prompt=Task a. Notes: ${NOTES}/a."
check "harness launch: rendering created no notes directory" absent "${NOTES}/a"
write_cfg "[task]
prompt = 'Reply as {{\"task\": \"{task}\"}}'"
check "harness launch: doubled braces are literal braces" build_from opencode a ""
check "harness launch: the rendered prompt holds the literal braces" cmd_is opencode '--prompt=Reply as {"task": "a"}'
write_cfg $'[task]\nprompt = "Task {taks} begins."'
check "harness launch: an unknown placeholder is refused on the launch path" refused_run --task a
check "harness launch: the placeholder refusal names the offending text" out_has "{taks}"
check "harness launch: the placeholder refusal created nothing" no_session_state
write_cfg $'[task]\nprompt = "Task { begins."'
check "harness launch: a stray brace is refused" build_refused opencode a ""
write_cfg $'[task]\nprompt = "Task {task} in {task_dir}."'
check "harness launch: {task_dir} without a notes directory is refused" build_refused opencode a ""
check "harness launch: that refusal names both keys" out_has "task.notes_dir"
write_cfg $'[task]\nprompt = "{task}"'
check "harness launch: a one-word prompt is refused" build_refused opencode mcp ""
check "harness launch: the one-word refusal explains the Claude subcommand reason" out_has "subcommand"
write_cfg "${PROMPT_CFG}"
check "harness launch: a label-only dash-leading id is delivered as data" build_from opencode -x ""
check "harness launch: the dash-leading id arrives inside the attached form" cmd_is opencode "--prompt=Task -x begins."
write_cfg $'[task]\nprompt = "Task {task}\\nline two\\n"'
check "harness launch: a multi-line prompt is one argv element" build_from opencode a ""
check "harness launch: the newlines, trailing one included, survive" cmd_is opencode $'--prompt=Task a\nline two\n'
write_cfg "${PROMPT_CFG}"
check "harness launch: claude gets -- then the positional prompt" build_from claude a ""
check "harness launch: the claude command" cmd_is claude -- "Task a begins."
check "harness launch: copilot gets the attached --interactive= form" build_from copilot a ""
check "harness launch: the copilot command" cmd_is copilot "--interactive=Task a begins."
write_cfg $'[harness.claude]\nargs = ["--add-dir", "/data"]\n[task]\nprompt = "Task {task} begins."'
check "harness launch: a variadic option in args is ended by -- before the prompt" build_from claude a ""
check "harness launch: the variadic command" cmd_is claude --add-dir /data -- "Task a begins."

# === 4. Resume from the launch record =========================================
write_cfg "${PROMPT_CFG}"
clear_record
check "harness launch: first launch under auto is fresh with the prompt" build_from opencode a ""
check "harness launch: the first-launch command carries the prompt, no --continue" cmd_is opencode "--prompt=Task a begins."
check "harness launch: the record is to be written once the container exists" rec_flag 1
check "harness launch: the builder itself created no state directory" absent "${SDIR}"
seed_record opencode a
check "harness launch: a record for this harness and task continues" build_from opencode a ""
check "harness launch: the relaunch command is --continue without a prompt" cmd_is opencode --continue
check "harness launch: the note names the recorded task" note_has "for task a"
check "harness launch: the note says it is tjor's decision" note_has "tjor's decision"
check "harness launch: another task in the same session is fresh" build_from opencode b ""
check "harness launch: the other task gets the prompt, not --continue" cmd_is opencode "--prompt=Task b begins."
check "harness launch: another harness in the same session is fresh" build_from claude a ""
check "harness launch: the other harness gets the prompt" cmd_is claude -- "Task a begins."
check "harness launch: --no-resume forces a fresh conversation" build_from opencode a 1
check "harness launch: the forced-fresh command carries the prompt" cmd_is opencode "--prompt=Task a begins."
write_cfg $'[task]\nprompt = "Task {task} begins."\nresume = "never"'
check "harness launch: resume = never ignores the record" build_from opencode a ""
check "harness launch: never sends the prompt every time" cmd_is opencode "--prompt=Task a begins."
check "harness launch: never still writes the record" rec_flag 1
write_cfg $'[task]\nresume = "auto"'
check "harness launch: resume alone, no prompt: a record still decides" build_from opencode a ""
check "harness launch: resume alone continues the recorded conversation" cmd_is opencode --continue
clear_record
check "harness launch: resume alone with no record is fresh and silent" build_from opencode a ""
check "harness launch: resume alone, fresh: the bare harness" cmd_is opencode
check "harness launch: resume alone still writes the record" rec_flag 1
write_cfg $'[task]\nprompt = "Task {task} begins."\nresume = "always"'
check "harness launch: an invalid task.resume is refused on the launch path" refused_run --task a
check "harness launch: the resume refusal names the two values" out_has 'must be "never" or "auto"'
check "harness launch: the resume refusal created nothing" no_session_state
write_cfg "${PROMPT_CFG}"
seed_record opencode a; printf '{broken' > "${SDIR}/conversation.json"; snapshot "${SDIR}" "${WORK}/snap.before"
check "harness launch: a corrupt record refuses the launch" refused_run --task a
check "harness launch: the corrupt-record refusal names the file" out_has "conversation.json cannot be read"
check "harness launch: the corrupt-record refusal names the remedy" out_has "tjor reset sessions --session"
check "harness launch: the existing state directory and record are byte-identical afterwards" unchanged
check "harness launch: the corrupt record never reached docker" never_reached_docker
rm -f "${SDIR:?}/conversation.json"; ln -s /etc/hostname "${SDIR}/conversation.json"
check "harness launch: a symbolic link where the record should be refuses" build_refused opencode a ""
check "harness launch: the link refusal says the link is never followed" out_has "never followed"
rm -f "${SDIR:?}/conversation.json"; mkfifo "${SDIR}/conversation.json"
check "harness launch: a FIFO where the record should be refuses" build_refused opencode a ""
rm -f "${SDIR:?}/conversation.json"; head -c 5000 /dev/zero | tr '\0' 'x' > "${SDIR}/conversation.json"
check "harness launch: an oversize record refuses" build_refused opencode a ""
rm -f "${SDIR:?}/conversation.json"
check "harness launch: an absent record is the only no-conversation" build_from opencode a ""
check "harness launch: with the record gone the launch is fresh with the prompt" cmd_is opencode "--prompt=Task a begins."
clear_record

# === 5. The record is never agent-writable ====================================
write_cfg "${PROMPT_CFG}"
check "harness launch: a writable --dir over the session root refuses the launch" build_refused opencode a "" rw:"${WORK}/state"
check "harness launch: the coverage refusal names the root and the record" out_has "would cover the session's state directory"
check "harness launch: the coverage refusal names conversation.json" out_has "conversation.json"
check "harness launch: a writable root equal to the session root refuses" build_refused opencode a "" rw:"${STATE}"
check "harness launch: a writable sibling of the session root is fine" build_from opencode a "" rw:"${HOME}/data"
check "harness launch: the coverage refusal on the launch path refuses --unsafe-dir over the session root" refused_run --unsafe-dir --dir "${WORK}/state" --task a
check "harness launch: the coverage refusal on the launch path created nothing" no_session_state
check "harness launch: that refusal never reached docker" never_reached_docker
check "harness launch: a read-only root over the session root is allowed" build_from opencode a "" ro:"${WORK}/state"
check "harness launch: the read-only case still delivers the prompt" cmd_is opencode "--prompt=Task a begins."
write_cfg ""
check "harness launch: the same roots with [task] at its defaults are not judged" build_from opencode a "" rw:"${WORK}/state"
check "harness launch: the unjudged launch is the bare harness" cmd_is opencode
write_cfg "${PROMPT_CFG}"
check "harness launch: an explicit command with a covering root is not judged either" build_from opencode a "" rw:"${WORK}/state" -- opencode --help
# The notes directory as an intended root: a template over the session root.
ALT_ROOT="${WORK}/notes/a/sessions"; mkdir -p "${ALT_ROOT}"
printf '[session]\nroot = "%s"\n[task]\nnotes_dir = "%s/notes/{task}"\nresume = "auto"\n' "${ALT_ROOT}" "${WORK}" > "${XDG_CONFIG_HOME}/tjor/config.toml"
check "harness launch: the notes directory over the session root refuses before it is mounted" refused_run --unsafe-dir --task a
check "harness launch: that refusal names the notes directory as the covering root" out_has "the writable root ${WORK}/notes/a would cover"
check "harness launch: no session state under the covered root" no_state_under "${ALT_ROOT}"
check "harness launch: the notes-over-root refusal never reached docker" never_reached_docker
write_cfg "${PROMPT_CFG}"

# === 6. Refusals create nothing: the fresh-task sweep ======================
write_cfg $'[task]\nnotes_dir = "~/scratch/tasks/{task}"\nprompt = "Task {taks}"'
check "harness launch: a refused launch with a notes template creates no notes directory" refused_run --task zz
check "harness launch: the notes directory for zz is absent" absent "${NOTES}/zz"
check "harness launch: no session state for the refused task" no_session_state
check "harness launch: nothing reached docker in the whole suite" never_reached_docker

# === 7. Help text =============================================================
check "harness launch: help text names --no-resume" bash -c "'${ROOT}/bin/tjor' help | grep -qF -- '--no-resume'"
check "harness launch: help text says an explicit command is passed as given" bash -c "'${ROOT}/bin/tjor' help | grep -qF 'passed as given'"

echo "----"
echo "harness-launch: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
