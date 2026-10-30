# Design

## Context

See proposal.md for motivation. What shapes the approach (observed unless marked):

- `cmd_run` builds `agent_cmd` as either `"$@"` after `--` or the bare harness name, and hands it to `run_agent`, which passes it to `compose run … agent "$@"`; the entrypoint `exec`s it after the privilege drop and the sandbox wrap. Nothing between the launcher and the harness interprets the argv as a shell string.
- Harness flags, read from the pinned images' `--help` (opencode 1.18.28, Claude Code 2.1.260, Copilot CLI 1.0.83): opencode `--prompt <text>` and `-c/--continue` on its default (TUI) command; Claude Code `[prompt]` as the trailing positional and `-c/--continue`; Copilot CLI `-i, --interactive <prompt>` ("start interactive mode and automatically execute this prompt") and `--continue` ("resume the most recent session"). Copilot's `-p/--prompt` is its non-interactive mode and is not used.
- The session home persists under the state directory (`${TJOR_SESSION_DIR}/home`); `tjor_state.py` already names opencode's conversation store (`home/.local/share/opencode/storage`) as the `sessions` tier. Claude Code keeps transcripts under `home/.claude/projects/<encoded cwd>/`. Copilot CLI's store under `home/.copilot` is confirmed from a real session home in implementation (task 1.3) and recorded in the spec.
- Profiles are directories of definition subdirectories; staging copies only allow-listed subdirectories (`tjor_profile.ALLOWED`), so a top-level `profile.toml` is never staged today either (observed: no top-level file is).
- `[task]` is user-config only and a security table (ADR 0013, #69); `tjor_cfg.check` validates keys against the packaged defaults.
- The relaunch of a stopped session recreates the agent container from the current command line (#78), so a builder that runs on every launch is what resume needs.

## Goals / Non-Goals

**Goals:**
- One builder, in the launcher, for the harness command line: config args, profile args, the task prompt, the continue flag; delivered per harness; printed at launch.
- The explicit `-- cmd` path untouched.

**Non-Goals:**
- Any knowledge of what the agent should read first (a `SESSION-RESUME-*.md` convention): that stays in profile instructions, as the issue says.
- Resuming a *specific* conversation (`--session <id>`, `--resume <id>`): the harness's "most recent" is the contract; per-task sessions make it the task's.
- Prompts from a repository config: `[task]` is user-only (ADR 0013); a repository uses its instruction files.

## Decisions

### D1. One builder function, `build_agent_cmd`, with a testable seam

`build_agent_cmd <harness> <profile-dir-or-empty>` prints the argv one element per line (NUL and newline are refused in every element, so lines are a faithful encoding) and the launcher reads it into `agent_cmd`; the docker-free test calls it directly. Inputs: `cfg harness.<name>.args` (JSON list), the profile's `profile.toml` `[harness.<name>].args` when present, `cfg task.prompt`, `cfg task.resume`, `TJOR_TASK_ID`, `TJOR_TASK_DIR`, and the conversation probe. Order: harness, args, `--continue` when resuming, then the prompt delivery. Rationale: one place to read, print and test; the per-harness differences are a small table inside it.

### D2. Args: config, then profile, verbatim

`[harness.<name>] args = [...]` in `config/tjor.toml` (empty lists by default) is read through `cfg` as JSON; `profile.toml` is parsed by `python3 tjor_profile.py launch-args <dir> <harness>` (a small subcommand: reads the file with `tomllib`, validates the shape `{"harness": {<name>: {"args": [str...]}}}` with no unknown keys, prints the list as JSON or exits non-zero naming the key). The profile's list, when the file holds a table for the harness, replaces the config's. Every element is validated (string, no NUL, no newline) before use. Alternative: merge config and profile lists; rejected, a profile that wants to *remove* an argument could not.

### D3. The prompt: two placeholders, rendered without a shell, one argv element

Rendering is a literal substitution of `{task}` and `{task_dir}` after validating that the template's braces are exactly those (a regex over `{[^}]*}` occurrences, every match in the allowed set; a lone `{` or `}` refuses too). `{task_dir}` with `TJOR_TASK_DIR` empty refuses. No `printf`/`eval`: the rendered text goes into the argv array as one element. Delivery table: opencode → `--prompt <text>`; claude → `<text>` last; copilot → `-i <text>`. Without `--task` the prompt is skipped entirely (the template cannot render `{task}` and a task prompt without a task is meaningless). Rationale: the issue's design; the placeholders are values #69 already validated (grammar, physical path).

### D4. Resume: host-side detection on the session home, per harness

`harness_conversation_exists <harness> <home>`: opencode → a non-empty `home/.local/share/opencode/storage/session` directory (the store the `sessions` tier already names; the exact subpath confirmed in implementation against a real home, like Copilot's); claude → any `*.jsonl` under `home/.claude/projects`; copilot → the confirmed store under `home/.copilot`. The probe never follows a symbolic link (the home is agent-writable: `find -type d` on the real path only, `-maxdepth` bounded) and reads nothing. With `resume = "auto"` and a hit: `--continue`, no prompt. Rationale: the launcher owns the state directory and knows the harness; the harness's own "most recent" is what `--continue` does, so tjor only decides *whether* to ask for it. Alternative: always pass `--continue` and let the harness fall back; rejected, Claude Code and Copilot error out on `--continue` with nothing to continue, and the prompt would be lost.

### D5. `[harness]` and `[task]` as security tables; `[task]` stays user-only

`harness` joins `SECURITY_TABLES` (a misspelled `arg` would silently launch without the argument the operator counts on). `[task].prompt`/`resume` are keys of the user-only table: ADR 0013 made the *table* user-only, and a launch prompt chosen by a repository is the kind of steering that belongs in its instruction files. `[harness.<name>].args` is ordinary config (user and trusted repository): a trusted repository already shapes the session (policy, instructions), and args run inside the cage. The profile file is host-side and operator-selected. Stated in the README.

### D6. What the launcher prints

One line: `tjor: harness command: opencode --agent bob --continue` or `… + prompt (142 characters)`, every element through `safeprint`. An explicit `-- cmd` prints nothing new (today's behaviour). Rationale: the operator sees what tjor added without the prompt text flooding the terminal.

### D7. Proof

- `tests/integration/harness_launch_test.sh` (docker-free, sourcing `bin/tjor`): the builder for all three harnesses: bare, args from config, args from a profile winning, another harness's args ignored, malformed entries refused, the prompt rendered and delivered per harness, unknown placeholder refused, `{task_dir}` without a notes directory refused, no task → no prompt, resume auto with and without a conversation per harness (seeded stores under a throwaway home), never, an invalid `resume` value refused, another harness's conversation not counted, a symlinked store not followed, the launch line, `-- cmd` overriding everything (through `cmd_run` to the docker shim: the recorded `compose run … agent <cmd>` arguments). Registered in the boundary matrix as `harness-launch`.
- `python/tests/test_cfg_and_corefile.py`: `[harness]` typo aborts; defaults; `test_profile.py`: `launch-args` parsing, unknown key refused, file never staged.
- Live (`lifecycle_test.sh`, opencode): a `[task] prompt` launch's container `Cmd` holds `opencode --prompt "Task t1 …"`; after seeding the session home's opencode store and relaunching under `resume = "auto"`, `Cmd` holds `--continue` and no `--prompt`. Claude Code and Copilot are covered by the builder test and the recorded `--help` facts, not live (the live jobs build the opencode image only); stated.

## Risks / Trade-offs

- [The prompt is a process argument] → visible in `docker inspect` and `ps`; stated; it is a starting message, not a secret.
- [A harness changes its flags in a future pin] → the builder's table is per harness and the pins are config; the live case catches opencode, the others rely on the help-text facts recorded here. The version bump checklist gains a line.
- [Copilot's store path unknown at planning time] → confirmed in implementation from a real home before the spec text is final (task 1.3); until confirmed, `resume = "auto"` under copilot refuses with "not yet supported" rather than guessing.
- [`--continue` picks the harness's most recent conversation, which under a shared (non per-task) session may be another task's] → stated; per-task sessions are the recommended pairing.
