# Tasks

## 1. Config surface

- [x] 1.1 `config/tjor.toml` `[landlock]`: add `mask_git_hooks = true` and `protect_git_config = false` with comments stating what each does, the cost of the pin, and the `core.hooksPath` residual. Verify: `python3 python/tjor_cfg.py check` passes; a user config setting both keys passes validation

## 2. Launcher: git metadata masks

- [x] 2.1 In `run_agent`, after the `mask_dirs` block and before the dotenv masks, discover git directories under each writable root (`.git` dirs and `.git` files → common dir via `git rev-parse --path-format=absolute --git-common-dir`), skipping read-only roots and anything inside an already-masked directory; when `mask_git_hooks` is not `false`, create a missing `hooks` dir on the host, mask `<gitdir>/hooks` with the empty source `:ro`, register in `masked`/`dirmasked`, announce `+ dir mask <path> (git hooks)` via safeprint (design D1–D3). Verify: `shellcheck --severity=warning bin/tjor` clean; A4 launch-1 checks
- [x] 2.2 When `protect_git_config` is `true`, for each discovered git dir bind `<gitdir>/config` over itself `:ro` (if the file exists), register in `masked`, announce `+ config pin <path> (protect_git_config)` (design D4). Verify: A4 launch-3 checks

## 3. Live test (landlock suite, any engine)

- [x] 3.1 `tests/integration/landlock_test.sh` section A4: build the layout (host `pre-commit` writing a marker, nested repo, linked worktree under the same root); launch 1 with defaults + probe: announcements for the three hooks dirs, `.git/hooks` lists empty, `touch` there refused, `git commit` succeeds and the marker is absent, nested and common-dir hooks list empty; launch 2 with `mask_git_hooks = false`: no announcement, hook visible; launch 3 with `protect_git_config = true`: `git config x.y z` and `git remote add` fail, `git commit` succeeds, `git config --list` works, host file unchanged. `check "…"` names literal. Verify: `bash tests/integration/landlock_test.sh` A4 passes on colima; `shellcheck` clean
- [x] 3.2 `python/gen_boundary_matrix.py`: REGISTRY entries for the new check names — rendered rows: hooks dir lists empty, hooks dir unwritable, host hook does not fire, nested/common hooks masked, config pin refuses writes; the rest `boundary=False`; regenerate `docs/boundary-matrix.md`. Verify: `--check` clean; `tests/doc_consistency.sh`

## 4. Docs

- [x] 4.1 README kernel-sandbox section: two bullets (hooks mask, config pin) with the honest limits and the breakage list; the `[landlock]` config block gains both keys. Verify: `tests/doc_consistency.sh`; text reads correctly
- [x] 4.2 CHANGELOG `[Unreleased]` — Security, **BREAKING**: the hooks mask (default on, what it breaks, the opt-out), the opt-in pin with its cost list, the residuals, #71/#72/#10 references. Verify: entry present
- [x] 4.3 At release: a comment on #10 linking its "targeted LSM denies (git hooks dir)" candidate to #71 and this change. Verify: comment posted (release step)

## 5. Verification

- [x] 5.1 Local gate (**verified breakage for the pin, live on colima**: `git config x.y z` refused, `git remote add` refused, `git commit` succeeds, `git config --list` works, the host file is byte-identical afterwards; `push -u`, `branch --set-upstream-to`, `worktree add -b` with tracking and `gh pr checkout` fail by the same mechanism — every one writes config by lock-and-rename — and are stated as such, not as observed). Local gate: `bash tests/integration/landlock_test.sh` (A2–A4 on colima), `bash tests/integration/workspace_gate_test.sh`, `bash tests/integration/self_mount_test.sh`, `uvx --python 3.14 --with 'mitmproxy==12.1.2' pytest python/tests -q`, `tests/doc_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/*.sh`, `npx --yes @fission-ai/openspec@latest validate mask-git-hooks-and-config-pin`. Verify: all green; record the verified breakage list for the pin in tasks.md
