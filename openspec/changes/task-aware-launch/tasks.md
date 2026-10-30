# Tasks

## 1. Configuration and trust

- [ ] 1.1 `config/tjor.toml`: add `[harness.opencode]`, `[harness.claude]`, `[harness.copilot]` each with `args = []` and a comment stating user-config only and verbatim passing; add `prompt = ""` and `resume = "never"` to `[task]` with the placeholder and escape rules in the comment. `python/tjor_cfg.py`: `harness` joins `SECURITY_TABLES` and `USER_ONLY_TABLES`; generalise the drop warning to name ADR 0013/0014. Tests in `python/tests/test_config_ergonomics.py`: a trusted repo config's `[harness]` is dropped with the warning and reported by the check; an unknown key under `[harness.claude]` refuses.
- [ ] 1.2 `docs/decisions/0014-repo-config-never-shapes-the-harness-launch.md`: context (what a repo-set `args` could do, the managed-config precedent), decision (user-only, security table, the general rule), consequences, alternatives (honour from a trusted repo; a flag denylist; reserve only the prompt and resume flags).

## 2. Helpers

- [ ] 2.1 `python/tjor_launch.py`: `args --harness <name> [--adding continue|prompt]…` (JSON list on stdin → NUL-separated entries; rules and the exact collision set from D2, exit 2 naming position and rule) and `render --template T --task ID [--task-dir DIR]` (D3: escapes, two placeholders, refusals naming the offending text, NUL, 65536-byte bound, one-word rule; prints the rendered prompt and nothing else). `python/tests/test_launch.py` covering every rule and both exit paths.
- [ ] 2.2 `python/tjor_state.py`: `conversation-read DIR` and `conversation-write DIR --harness H --task T` (D5: absent → empty exit 0; present but wrong → exit 2; atomic write via mkstemp in DIR); extend `TIERS["sessions"]` with `conversation.json`, the three opencode database files and `home/.copilot/session-state`; usage text. `python/tests/test_state.py`: round trip, absent vs unreadable vs wrong shape, the tier list exactly, `reset sessions --dry-run` listing the record.

## 3. Launcher

- [ ] 3.1 `bin/tjor`: `cmd_run` parses `--no-resume` and refuses `--harness` outside the three names before `resolve_session`; `build_agent_cmd` and `agent_cmd_print` per D1–D5 and D7, called after the profile gate and before the first write; the explicit-command branch (with or without `--`) untouched and skipping the builder; the launch line per D8 before `run_agent`; `run_agent` writes the record after the container exists and before the lock release, only when the builder decided a prompt or `resume = "auto"` applied; usage text for `--no-resume` and the owned command line.
- [ ] 3.2 `tests/integration/harness_launch_test.sh` (docker-free, docker shim that records and fails any call): per harness and per case the NUL-separated command from `agent_cmd_print`; every refusal from D10 with "no state directory, shim never called" asserted; the record decision table (absent, matching, other task, other harness, `--no-resume`, corrupt). Register the suite in `python/gen_boundary_matrix.py` (`HARNESS_LAUNCH`, capability `harness-launch`, `CAPABILITY_ORDER`), regenerate `docs/boundary-matrix.md`, add the suite to the `unit` and `unit-min-python` jobs in `.github/workflows/ci.yml`.

## 4. Image

- [ ] 4.1 `images/agent/Dockerfile`: after each harness install, run its `--help` and fail the build unless it lists the flags tjor uses (opencode `--prompt`, `--continue`; claude `--continue`, `[prompt]`; copilot `--interactive`, `--continue`), naming the harness and the flag in the failure.

## 5. Live proof

- [ ] 5.1 `tests/integration/lifecycle_test.sh`: a section under opencode with a user config (`[task] prompt`, `resume = "auto"`, `[harness.opencode] args = ["--print-logs"]`): fresh launch → `docker inspect` `Cmd` is `[opencode, --print-logs, --prompt=<rendered>]` and `conversation.json` exists; relaunch → `Cmd` is `[opencode, --print-logs, --continue]`; `--no-resume` → the prompt again; `tjor reset sessions --dry-run` lists the record; after `tjor reset sessions` the next launch is fresh; an explicit `-- opencode --help` leaves the record untouched.

## 6. Documentation

- [ ] 6.1 `README.md`: a "**Task-aware launch**" paragraph after "**Task notes**" (owned command line, `[harness.<name>] args` user-only with the ADR, the prompt template and its delivery forms, `resume` and `--no-resume`, the launch line) and the limits from the spec's "Limits are stated" scenario, plus the reset-tier sentence for Claude transcripts. `CHANGELOG.md` under `## [Unreleased]`: the feature, the `--harness` refusal, the sessions tier extension, the image-build flag check.
- [ ] 6.2 Slides: one new slide in "Operate & prove" (`specs: [harness-launch@<pin>]`, `adrs: ['0014']`) explaining the problem and the mechanism with the limits; re-pin the task-notes slide and the session-lifecycle slide after re-reading them; add the slide to the map's group; `tests/slides_consistency.sh` and `cd slides && pnpm check` green.

## 7. Gates

- [ ] 7.1 `python -m pytest python/tests -q`, `tests/doc_consistency.sh`, `tests/slides_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/harness_launch_test.sh tests/integration/lifecycle_test.sh`, `python3 python/gen_boundary_matrix.py --check`, `bash tests/integration/harness_launch_test.sh`, the state and workspace-gate launcher tests, a local build of `tjor-agent-opencode:local` to exercise 4.1, and the lifecycle live section on the local engine (CI is the verdict for the environmental failures recorded in the project notes).
- [ ] 7.2 Archive: sync the three deltas into the main specs (new `harness-launch` with its Purpose), move the change under `openspec/changes/archive/`, re-pin the slides, `openspec validate --specs` clean.
