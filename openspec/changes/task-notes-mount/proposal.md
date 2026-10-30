# Proposal

## Why

`--task <id>` is a label today: `TJOR_TASK_ID` in the cage, a `tjor.task` container label and a term in the proxy config hash (#69). It has no filesystem effect. Task-oriented work keeps its notes and hand-off files in a per-task directory, usually inside one larger notes repository (`~/scratch/tasks/<id>/`), and the only way to give the agent that directory today is to launch from it, which makes git discovery climb to the notes repository's root and mount the **whole notes repository**, writable, as the workspace: every other task's files are exposed, and the real code repository is no longer the workspace, so its trusted `.tjor/policy.toml` and `.tjor/config.toml` are not read and the harness's `AGENTS.md` and skill discovery look in the wrong tree. The alternative, `--dir ~/scratch/tasks/<id>`, works but has to be typed on every launch and gives the session no per-task identity, so two tasks in one repository share one session.

## What Changes

- **A per-task notes directory, opt-in by config.** A new `[task]` section (`notes_dir = "~/scratch/tasks/{task}"`, `create`, `session_per_task`) makes `--task <id>` resolve a notes directory from the template and mount it **writable through the existing extra-dir path**, so it inherits the sensitive-path gate, the VM-share check, the mixed-writability and self-mount rules, git trust as a tree, the launch-time mask discovery and the git-check baseline. Workspace resolution is unchanged: the workspace is still the repository found above the launch directory. `TJOR_TASK_DIR` names the directory inside the cage; it never joins the `x-agent-*` wire schema.
- **The task id is a path now, so it is checked like one.** When a notes directory is configured, the id may not start with a dot (`.`, `..` and `.hidden` are refused); the resolved directory's physical path must lie under the template's fixed prefix (a symlink escaping it is refused); the directory is created component by component under the prefix, each level checked to be a real directory before the next is made, and never created when `create = false`.
- **Refusals that keep the notes repository out of the cage.** A launch is refused when the workspace equals the notes root (the template's fixed prefix) or is an ancestor of it: that is exactly the "launched from inside the notes repo" case the feature exists to prevent, and there is no override. `--workspace <dir>` launches with that directory as the launch directory from anywhere else, under every existing rule.
- **One session per task.** With `session_per_task = true`, a launch with `--task <id>` derives the short session name `<session-or-harness>.<id>` (lower-cased, built by the launcher and never re-parsed as a `--session` value; over 32 characters it becomes the first 23 characters, a dot and 8 hex characters of its hash). Two tasks in one repository get two sessions; the same task twice meets the existing running-session guard. `tjor attach --task <id>` picks the running agent carrying that `tjor.task` label, and the lifecycle commands accept `--task <id>` alongside `--session`, resolving to the per-task session.
- **Repo-less tasks.** `--notes-workspace` (with `--task` and a configured `notes_dir`) makes the notes directory the workspace **exactly**: no git discovery runs for it, so the notes repository above it is never the workspace, and nothing above the directory is mounted.
- **A loud warning for credential-shaped files.** At launch the notes directory is scanned (bounded) for file names that look like credentials (`token`, `*.pem`, `*.key`, `id_*`) and for the secret shapes the egress tripwire already knows; matches are named in a warning before the agent starts. A warning, not a refusal: the directory is the operator's own.
- **Docs and proof.** A `task-notes` capability spec and problem slide; README "Task notes"; the `[task]` keys in the packaged defaults; a docker-free launcher test driving `resolve_session`/`cmd_run` under a throwaway layout (mount list, refusals, naming, unchanged behaviour without config), a pytest suite for the resolver, the name derivation and the scanner, and one live case in the multi-repo test (the directory is mounted writable at its host path and `TJOR_TASK_DIR` is set).

Compatibility. Without a `[task]` section nothing changes: `--task` stays a label with today's grammar, `--session` derivation, `attach` and the lifecycle commands behave as before. With `notes_dir` set, a task id starting with a dot is refused (it was accepted as a label).

## Capabilities

### New Capabilities
- `task-notes`: the per-task notes directory: configuration, id and path validation, creation, the writable mount and its inherited guards, `TJOR_TASK_DIR`, the notes-root refusal, the repo-less workspace mode, the credential-shaped-file warning.

### Modified Capabilities
- `session-launch`: named session derivation gains the per-task composite name; a new requirement for `--workspace <dir>`.
- `session-lifecycle`: reattachment and session references accept `--task <id>`.
- `session-identity`: `TJOR_TASK_DIR` is cage-only, never on the wire.

## Impact

- `bin/tjor`: `cmd_run` (`--workspace`, `--notes-workspace`, the notes-dir resolution appended to the writable extra dirs), `resolve_session` (task-id grammar, composite short name, the notes-root refusal), `cmd_attach` and the lifecycle commands (`--task`), usage text.
- New `python/tjor_task.py` (template resolution and creation, composite name, credential-shaped scan) and `python/tests/test_task.py`.
- `compose.yaml` (`TJOR_TASK_DIR` in the agent environment); `config/tjor.toml` (`[task]` defaults, so the config shape check accepts the keys).
- `tests/integration/task_notes_test.sh` (docker-free, registered in `python/gen_boundary_matrix.py`), one case in `tests/integration/multirepo_test.sh`, `ci.yml` (the new test in the unit job).
- README, CHANGELOG, `slides/presentations/overview/slides.md` (new problem slide and map entry; four re-pinned slides).
