# Proposal

## Why

The harness command line is built in one of two ways today: `tjor run` starts the bare harness (`opencode`, `claude`, `copilot`), or an explicit `-- cmd` replaces it entirely (#73). Launcher scripts that want a task-aware start (a first message naming the task and its notes directory, or continuing yesterday's conversation on relaunch) have to hand-build that command after `--`, splicing a prompt into a shell string and guessing when to pass the harness's continue flag. That splicing is fragile, differs per harness (opencode `--prompt`, Claude Code a positional argument, Copilot CLI `-i`), and sits outside tjor's own knowledge of the session (which harness, whether the session home already holds a conversation, what `--task` resolved). With #69 merged, `--task <id>` has a directory and a session of its own; the launch should be able to use them.

## What Changes

- **tjor owns the harness command line when configuration asks it to.** A per-harness `args` list (`[harness.opencode] args = ["--agent", "bob"]`, likewise `claude` and `copilot`), from the user or trusted repository config, or from an optional `profile.toml` in a selected profile directory (the profile wins), is passed to the harness verbatim, one argv element per entry, never through a shell. An explicit `-- cmd` on the command line keeps today's meaning exactly: it replaces everything, and no args, prompt or resume flag is added.
- **A task prompt.** `[task] prompt = "Task {task}. Notes are in {task_dir}. …"` renders with exactly two placeholders, `{task}` and `{task_dir}` (both already validated by #69; any other brace refuses the launch, and `{task_dir}` without a configured notes directory refuses too), and is delivered as one argv element in the harness's own way: opencode `--prompt <text>`, Claude Code the positional prompt, Copilot CLI `-i <text>`. It is sent only on a launch with `--task` and only when a fresh conversation starts. The rendered prompt is an argument of the harness process (visible to anyone who can inspect the container); nothing else about it is secret.
- **Conversation resume.** `[task] resume = "auto"` (default `never`) adds the harness's continue flag (`--continue` on all three) when the session home already holds a conversation for that harness, and then sends no prompt. Detection is host-side, on the session's state directory, before the container is created, per harness: opencode's session store under `.local/share/opencode/storage`, Claude Code's transcripts under `.claude/projects`, Copilot CLI's session store under `.copilot` (the exact Copilot path is confirmed from a real session home during implementation and recorded in the spec). "Most recent conversation" is the harness's own notion within that session home; with per-task sessions (#69) that is the task's conversation, which is the point.
- **Said at launch.** The launcher prints the command line it built (args and flags verbatim, the prompt by its length), so the operator sees what tjor added.
- **Config shape and provenance.** `[task].prompt` and `[task].resume` join the user-only `[task]` table (ADR 0013: the table as a whole is user-config only; a repository steers the agent through its instruction files, not a launch prompt). `[harness.<name>].args` is ordinary config (user and trusted repository) plus the profile file; `[harness]` and `[task]` are security tables, so a misspelled key aborts rather than silently dropping an argument.
- **Docs and proof.** A `harness-launch` capability spec and problem slide; README "How the harness is started"; the `[task]` and `[harness]` keys in the packaged defaults; a docker-free launcher test of the command-line builder for all three harnesses and every rule (registered in the boundary matrix); one live case (opencode, the only harness image the live jobs build): the container's command line carries the rendered prompt on a fresh launch and `--continue` without a prompt on a relaunch whose home holds a conversation.

Compatibility. Without `[harness.*].args`, a profile `profile.toml`, `[task].prompt` or `[task].resume = "auto"`, the command line is exactly today's. With them, nothing changes for a launch that gives `-- cmd`.

## Capabilities

### New Capabilities
- `harness-launch`: how tjor builds the harness command line: configured args (config and profile), the explicit-command override, the task prompt and its delivery per harness, conversation resume and its detection, and what the launcher says about it.

### Modified Capabilities
- `task-notes`: the `[task]` table gains `prompt` and `resume`; the "unchanged" promise reads "with no `[task]` key set".
- `agent-profiles`: a profile directory may carry `profile.toml` with `[harness.<name>].args`; it is read host-side and never staged.

## Impact

- `bin/tjor`: `cmd_run` (the builder, `build_agent_cmd`; the resume probe; the launch line), `profile_source`/`prepare_profile` (reading `profile.toml`), usage text.
- `python/tjor_cfg.py` (`harness` in the security tables), `config/tjor.toml` (`[task].prompt/resume`, `[harness.<name>].args`), `python/tjor_profile.py` (ignore `profile.toml` in staging, by name).
- New `tests/integration/harness_launch_test.sh` (docker-free; boundary matrix `harness-launch` suite; both CI unit jobs), a live case in `tests/integration/lifecycle_test.sh`, `python/tests/test_cfg_and_corefile.py` cases.
- README, CHANGELOG, `slides/presentations/overview/slides.md` (new problem slide and map entry; two re-pinned slides).
