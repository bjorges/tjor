# Design

## Context

Verified against the pinned images (`tjor-agent-*:local`, `--network none`, `--help` and small probes), 2026-10-30:

- **opencode 1.18.28** (yargs): top-level `--prompt [string]`, `-c/--continue`, `-s/--session <id>`. Sessions live in SQLite: a real session home holds `home/.local/share/opencode/opencode.db`, `opencode.db-wal`, `opencode.db-shm`, `snapshot/`, `log/` and no `storage/` directory; `opencode db` is a subcommand. The sessions tier of `tjor_state.py` names `storage` and `log` only.
- **Claude Code 2.1.260** (commander): `[prompt]` positional, `-c/--continue` ("the most recent conversation in the current directory"), `-r/--resume [id]`, `--session-id <uuid>`, `--add-dir <directories...>` variadic. Probes: `claude -p --add-dir /tmp hello` reports no prompt (the variadic swallowed `hello`); `claude -p --add-dir /tmp -- hello` delivers it; `claude -p -- --version` treats `--version` as the prompt; **`claude -- mcp` opens the `mcp` subcommand**, so `--` does not stop subcommand dispatch of a bare first operand. Transcripts: `home/.claude/projects/<cwd with every non-alphanumeric as ->/<uuid>.jsonl`, beside `memory/` in the same per-project directory.
- **Copilot CLI 1.0.83** (commander): `-i/--interactive <prompt>`, `--continue`, `-r/--resume[=value]`, `--session-id <id>`; `-p/--prompt` is non-interactive and not used. Session store: `home/.copilot/session-state` (the package source names it; a real session home was not available).
- The command reaches the container as argv: `cmd_run` builds `agent_cmd` and `run_agent` passes it to `compose run -d … agent "$@"`; the entrypoint `exec`s it. No shell, no environment variable carries it.
- `cmd_run` order today: options, `resolve_session`, lock, extra dirs, notes directory, profile gate, **first write** (`mkdir home`), profile stage, `prepare_broker` (mint), gateway, secret scan, image, collision guard, metadata, `ensure_topology`, command, `run_agent`.
- The state directory's root is not mounted anywhere: compose binds `home`, `ca.pem`, `policy.toml`, `proxy-ca`, the log files, `Corefile` and `conformance-tls` individually.

## Goals / Non-Goals

Goals: an owned command line from the operator's own config; a task prompt that is data on every harness; resume without reading harness internals; refusals before any state; the record and the stores under one reset tier; drift caught at the pin. Non-goals: profile-carried arguments (deferred, see the proposal); interpreting `args`; any knowledge of what the agent should read on start (profile instructions own that, per the issue).

## Decisions

### D1. One builder, a bash array, a NUL-separated test seam

`build_agent_cmd <harness>` is a bash function in `bin/tjor` that fills the global array `AGENT_CMD` and the string `AGENT_CMD_NOTE` ("fresh, prompt sent" / "fresh, no prompt" / "continuing the conversation recorded <time> for task <id>"). `cmd_run` calls it right after `profile_source` succeeds and before `mkdir -p "${TJOR_SESSION_DIR}/home"`; the explicit-command branch (`$# -gt 0`, with or without `--`, unchanged `*) break`) sets `AGENT_CMD=("$@")` and skips the builder entirely. `agent_cmd_print` writes the array NUL-separated for the docker-free test, which sources the launcher's functions as `task_notes_test.sh` does. No newline framing anywhere, so a multi-line prompt is one element like any other.

### D2. Arguments: user config, validated by a helper, never inspected beyond the collision rule

`cfg harness.<name>.args --default '[]'` yields JSON; `python3 python/tjor_launch.py args --harness <name> [--adding continue] [--adding prompt]` reads it on stdin, validates (list; each a `str`; no NUL, no newline; ≤ 65536 bytes; not `--`) and prints the entries NUL-separated (`mapfile -d ''`), exit 2 with a message naming the position and rule otherwise. The collision rule is exact: with `--adding continue`, an entry equal to `--continue` or `-c` refuses; with `--adding prompt`, an entry equal to `--prompt`, starting with `--prompt=`, equal to `-i` or `--interactive`, or starting with `--interactive=` refuses, per harness. Nothing else is looked at: tjor does not know the harnesses' flag sets and says so. `harness` joins `USER_ONLY_TABLES` and `SECURITY_TABLES` in `tjor_cfg.py`; the drop warning is generalised ("user-config only; ADR 0013/0014").

### D3. Prompt rendering in Python, captured with a sentinel

`python3 python/tjor_launch.py render --template T --task ID [--task-dir DIR]` scans the template left to right: `{{` → `{`, `}}` → `}`, `{task}` → id, `{task_dir}` → DIR (refused when absent), any other `{` or `}` refuses naming the offending text; the result must hold no NUL, be ≤ 65536 bytes, and contain at least one whitespace and one non-whitespace character (the one-word rule from the Claude finding, applied to every harness so a template behaves alike). bash captures it as `p="$(python3 … && printf x)" || die; p="${p%x}"`, which keeps trailing newlines and the helper's exit status. The template is validated only when it is used (a launch with `--task` and `prompt` set), as `notes_dir` is today. The id grammar is unchanged by `prompt`: the delivery forms make a dash-leading label inert.

### D4. Delivery table

| harness | arguments | prompt (fresh) | continue |
|---|---|---|---|
| opencode | `args…` | `--prompt=<p>` | `--continue` |
| claude | `args…` | `-- <p>` | `--continue` |
| copilot | `args…` | `--interactive=<p>` | `--continue` |

Order: harness, `args…`, continue flag, prompt. The attached forms rely on documented parser behaviour (yargs and commander read everything after the first `=` as the value); the TUIs need a terminal, so the live test checks what tjor passes (`docker inspect … .Config.Cmd`), not the harness's parse. Claude Code's `--` is verified above. `-c` is not used because Copilot CLI has no short form.

### D5. The launch record

`conversation.json` at `${TJOR_SESSION_DIR}/conversation.json`: `{"schema": 1, "harness": "claude", "task": "a", "started": <epoch>}`. `python3 python/tjor_state.py conversation-read DIR` prints `harness<US>task<US>started` or nothing when the file is absent (exit 0) and exits 2 when it exists but is unreadable or not this shape (the launch refuses; absence is the only "no conversation"). `conversation-write DIR --harness H --task T` writes atomically (mkstemp in DIR, `os.replace`), like `meta.json`. Written in `run_agent` after `compose run` returned the container id and before `session_lock_release`, only when the builder ran with `--task` and `prompt` set or `resume = "auto"`. Read in the builder under the lock (taken right after `resolve_session`). Decision: `auto` and record (harness, task) equal (this harness, this task) and no `--no-resume` → continue; else fresh. `TIERS["sessions"]` gains `conversation.json`, `home/.local/share/opencode/opencode.db`, `…-wal`, `…-shm`, `home/.copilot/session-state` (the existing `storage` and `log` entries stay for older homes). `home/.claude/projects` is deliberately not added (memory lives there); the README states it.

### D6. Trust and provenance

`[harness]` is user-only for the reason ADR 0013 gives for `[task]`: approval reviews content, not consequence, and the consequence of repo-set harness flags is a steered agent (a prompt flag) or a relaxed harness (`--auto`, `--dangerously-skip-permissions`, `--allow-all-tools`) in every clone, which tjor elsewhere treats as meaningful (the root-owned managed opencode config, the `.opencode` mask). ADR 0014 records it and extends the general rule: no key a repository can set shapes the harness launch. The structural cage is unchanged either way; this is about not handing the repository the harness's own controls.

### D7. Ordering in `cmd_run`

options (`--no-resume` added; `--harness` checked against the three names before `resolve_session`) → `resolve_session` → lock → extra dirs → notes directory → profile gate → **`build_agent_cmd`** (reads config, renders the prompt, reads the record) → first write → profile stage → mint → … → `ensure_topology` → launch line → `run_agent` → container exists → record write → lock release. A refusal in the builder therefore leaves no directory, credential or sidecar, and the `session-launch` "lifecycle commands create no session state" rule holds: the builder reads, never writes.

### D8. The launch line

`tjor: harness command: claude --model opus -- <prompt: 142 bytes>` then `tjor: conversation: fresh, prompt sent` or `tjor: conversation: continuing the one recorded 2026-10-29 14:02 for task a`. The prompt never reaches the terminal (it may be long and hold anything the template holds); `args` are printed through the sanitizer.

### D9. Flag drift at the pin

The Dockerfile's harness stage runs, after each install, `<cli> --help` and greps for the flags tjor uses: opencode `--prompt` and `--continue`; claude `--continue` and `[prompt]`; copilot `--interactive` and `--continue`. A miss fails the build naming the harness and the flag. A Renovate bump that renames a flag is caught where the pin changes, not at an operator's launch.

### D10. Proof

- `python/tests/test_launch.py`: `args` rules and collisions; `render` placeholders, escapes, refusals, bounds, the one-word rule.
- `python/tests/test_state.py`: the record round trip, absent vs unreadable, the extended tier list.
- `python/tests/test_config_ergonomics.py`: a trusted repo cannot set `[harness]`; an unknown key under it refuses.
- `tests/integration/harness_launch_test.sh` (docker-free; a docker shim that fails if invoked): per harness the built command for args / prompt / continue / `--no-resume` / explicit command with and without `--`; refusals (unknown harness, bad entries, collisions, bad template, `{task_dir}` without notes, invalid `resume`, corrupt record) and, for each, that no state directory appeared and the shim was never called. Registered in `gen_boundary_matrix.py` and run by both CI unit jobs.
- Live, in `lifecycle_test.sh` under opencode: fresh launch → `Cmd` is `[opencode --prompt=…]` and the record exists; relaunch → `[opencode --continue]`; `--no-resume` → the prompt again; `tjor reset sessions --dry-run` lists the record; after the reset the next launch is fresh.

## Risks / Trade-offs

- **Attached-form parsing is documented, not executed here.** The TUIs need a terminal; the live test checks tjor's side. Mitigation: D9 catches a flag disappearing; a parse change is a residual stated in the README.
- **A record without a conversation.** The harness crashed before its first message, or the operator cleared its store: `--continue` then meets nothing (Claude Code 2.1.260 exits with an error in print mode; the others were not exercised). Remedy and residual stated: `--no-resume`, `tjor reset sessions`.
- **Shared session home.** Without `session_per_task` the record is per session and `--continue` reaches only the most recent conversation; stated.
- **`--help` grep.** Formatting changes could fail a build spuriously; the check names what it looked for, and the fix is a one-line edit at the same pin bump.
- **Copilot store path** comes from the package source, not an observed home; the tier entry is harmless when absent, and the live proof is under opencode.

## Migration

None. Defaults are empty `args`, empty `prompt`, `resume = "never"`; no record is written unless a prompt or `auto` is configured; an explicit command is untouched. The only visible change without configuration is that `--harness <unknown>` now refuses instead of launching opencode.
