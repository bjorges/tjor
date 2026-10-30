# Tasks

## 1. Configuration, profile file, conversation probe

- [ ] 1.1 `config/tjor.toml`: add `prompt = ""` and `resume = "never"` to `[task]` (commented), and `[harness.opencode]`, `[harness.claude]`, `[harness.copilot]` each with `args = []`; `python/tjor_cfg.py`: `harness` joins `SECURITY_TABLES`. Verify in `python/tests/test_cfg_and_corefile.py`: defaults read back (`task.resume == "never"`, empty lists); `[harness.opencode] arg = [...]` and `[task] resum = "auto"` in the user config abort naming the key; a trusted repo config's `[harness.opencode].args` applies while its `[task].prompt` is dropped with the ADR 0013 warning.
- [ ] 1.2 `python/tjor_profile.py launch-args <dir> <harness>`: parse `<dir>/profile.toml` with `tomllib` (absent → print `null`), accept only `harness.<name>.args` lists of strings, refuse any other key naming it, print the harness's list as JSON. Verify in `python/tests/test_profile.py`: a file with two harness tables returns the right list per harness; an unknown top-level or nested key exits non-zero naming it; a non-string entry refused; staging a profile dir holding `profile.toml` never copies the file.
- [ ] 1.3 `harness_conversation_exists <harness> <home>` in `bin/tjor` per D4; confirm opencode's and Copilot CLI's store subpaths by launching one real session per harness locally, inspecting its home, and recording the paths in the harness-launch spec and this design before the spec text is final (Copilot: if the image cannot be built or the path cannot be confirmed, `resume = "auto"` under copilot refuses with "not yet supported" and the spec says so). Verify in `tests/integration/harness_launch_test.sh`: a seeded opencode store, a claude `*.jsonl` and the confirmed copilot store each count for their harness only; an empty store does not; a store reached through a symbolic link is not followed.

## 2. The builder (bin/tjor)

- [ ] 2.1 `build_agent_cmd <harness> <profile-dir>` per D1–D3: args from config then profile (profile wins), element validation (string, no NUL, no newline), the prompt rendering (`{task}`/`{task_dir}` only, lone braces refused, `{task_dir}` without `TJOR_TASK_DIR` refused, skipped without `TJOR_TASK_ID`), the resume decision (`auto`/`never`, other values refused), the per-harness delivery table, output one element per line. Verify in the launcher test for each harness: bare; config args; profile args winning; another harness's args ignored; a malformed entry refused naming it; prompt delivered (`--prompt`, trailing positional, `-i`) as one element holding spaces and quotes unchanged; `{workspace}` refused; `{task_dir}` without a notes directory refused; no task → no prompt; `auto` with a conversation → `--continue` and no prompt; `auto` without → prompt and no flag; `never` → prompt, no flag; `resume = "sometimes"` refused.
- [ ] 2.2 Wire it into `cmd_run` per D6: when no `-- cmd` is given, `agent_cmd` comes from the builder and the launch prints `tjor: harness command: …` (elements sanitised, the prompt by length); with `-- cmd` nothing changes and nothing new is printed. Verify in the launcher test through `cmd_run` and the docker shim: the recorded `compose run … agent` tail equals the built argv; with `-- opencode --help` it is exactly that and no launch line appears.

## 3. Live proof and the boundary matrix

- [ ] 3.1 `tests/integration/lifecycle_test.sh` (opencode): with a task config (`prompt = "Task {task} starts here."`, `resume = "auto"`), `tjor run --detach --task tp` without a command; `docker inspect -f '{{json .Config.Cmd}}'` holds `opencode`, `--prompt`, `Task tp starts here.`; stop the session, seed `home/.local/share/opencode/storage/session/<x>` in its state dir, relaunch; `Cmd` holds `--continue` and no `--prompt`. Verify: the case passes on a Linux engine (CI `lifecycle` job).
- [ ] 3.2 Register `tests/integration/harness_launch_test.sh` in `python/gen_boundary_matrix.py` as the `harness-launch` suite and in `ci.yml` (both unit jobs); regenerate `docs/boundary-matrix.md`. Verify: `python3 python/gen_boundary_matrix.py --check` and `tests/doc_consistency.sh` pass.

## 4. Documentation, slides, changelog

- [ ] 4.1 README: "How the harness is started" (the bare default, `-- cmd`, `[harness.<name>].args` and `profile.toml`, the task prompt and its placeholders, resume, the launch line, the limits from the spec); the version-bump checklist line (re-check the three harnesses' flags on a pin bump); `CHANGELOG.md` Added entry. Verify: `tests/doc_consistency.sh` passes and the README names every key and flag.
- [ ] 4.2 Slides: a `problem` slide for `harness-launch` tagged with its pin, added to the map's "Operate & prove" group; re-read and re-pin the task-notes and agent-profiles slides. Verify: `tests/slides_consistency.sh` and `cd slides && pnpm check` pass.

## 5. Gates

- [ ] 5.1 Run and report `python -m pytest python/tests -q`, `bash tests/integration/harness_launch_test.sh`, `bash tests/integration/task_notes_test.sh`, `tests/doc_consistency.sh`, `tests/slides_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/harness_launch_test.sh tests/integration/lifecycle_test.sh`, `python3 python/gen_boundary_matrix.py --check`; verify every one is green and the draft PR's CI, the `lifecycle` job included, is green.

## Workflow follow-up

- Archive the change (`/opsx:archive task-aware-launch`), syncing the three spec deltas; re-pin the affected slides if the sync changed a spec file.
