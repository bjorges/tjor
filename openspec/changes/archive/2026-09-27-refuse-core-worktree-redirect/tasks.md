# Tasks

## 1. Launcher: containment check

- [x] 1.1 In `resolve_session`, immediately after `ws` is resolved with `in_repo=1` and before the #64 gate, refuse when `"$(pwd -P)"` is neither `"${ws}"` nor `"${ws}/"*`: read `git rev-parse --absolute-git-dir` and `git config --get core.worktree` on the failure path and `die` naming the launch directory, the reported work tree, the setting (when set) and its config file, and the remedies (design D1–D4). Applies on every resolution path (no `launch` condition). Verify: 2.1 checks; `shellcheck --severity=warning bin/tjor` clean

## 2. Regression test (the #76 reproduction, kept)

- [x] 2.1 `tests/integration/workspace_gate_test.sh`: a `core.worktree` section on a fresh repo under the throwaway `$HOME` — redirect to `proj2` refused naming `core.worktree` and the config file; redirect to `$HOME` refused with the containment wording and not the not-a-repository wording; state root untouched after both; `git worktree add` linked worktree launches; `repo/sub` launches; lifecycle resolve (no marker) refused under a redirect. Verify: `bash tests/integration/workspace_gate_test.sh` passes
- [x] 2.2 `python/gen_boundary_matrix.py`: REGISTRY entries for the new checks — one rendered `session-launch` row *A core.worktree redirect of the workspace is refused*, the rest `boundary=False`; regenerate `docs/boundary-matrix.md`. Verify: `python3 python/gen_boundary_matrix.py --check`; `tests/doc_consistency.sh`

## 3. Docs

- [x] 3.1 README: one sentence after the sensitive-path paragraph — the reported work tree must contain the launch directory, so a planted `core.worktree` cannot redirect a launch. Verify: `tests/doc_consistency.sh`
- [x] 3.2 CHANGELOG `[Unreleased]` — Security: #76 reproduced and closed (what git does, what tjor did, the containment rule, the lifecycle scope, the no-override stance, the detached-git-dir caveat). Verify: entry present, references #76 and #72

## 4. Verification

- [x] 4.1 Local gate: `bash tests/integration/workspace_gate_test.sh`, `bash tests/integration/self_mount_test.sh`, `uvx --python 3.14 --with 'mitmproxy==12.1.2' pytest python/tests -q`, `tests/doc_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/*.sh`, `npx --yes @fission-ai/openspec@latest validate refuse-core-worktree-redirect`. Verify: all green
- [x] 4.2 End-to-end through the real launcher on the live engine (**observed 2026-09-27 on colima**: with `core.worktree` planted toward a sibling, `tjor run` from `repo/sub` was refused naming the reported work tree, the repository found and the setting, and no state directory was created; planted toward an ancestor, `tjor status` was refused the same way; after `git config --unset core.worktree`, `tjor run -- true` launched with the repo as workspace and `tjor down` cleaned up): plant `core.worktree` in a throwaway repo, `tjor run` refused with the message; unset it, `tjor run -- true` launches; `tjor down`. Record the observations in tasks.md. Verify: recorded
