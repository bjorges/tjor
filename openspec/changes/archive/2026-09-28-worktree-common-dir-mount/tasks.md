# Tasks

## 1. Launcher: resolve, validate, mount

- [x] 1.1 Add `worktree_common_dirs` to `bin/tjor`: for the workspace, each `--dir` and each `--dir-ro` whose `.git` is a file (symlink → refuse), resolve `--git-common-dir`/`--git-dir`, validate git-dir shape + back-pointer (or `core.worktree`), refuse sensitive targets with no override, skip targets under an existing root (warn when under a read-only root for a writable worktree), dedupe (writable wins), append to `TJOR_EXTRA_DIRS`/`TJOR_EXTRA_DIRS_RO`, announce. Verify: `bash -n`, shellcheck clean.
- [x] 1.2 Wire it in `cmd_run` after the `--dir-ro` loop and before the mixed-writability rule, so the overlap rule, self-mount guard, mounts, `TJOR_SAFE_DIRS`, masks and baseline all see the new roots. Verify: the launcher test's refusals fire before the docker shim.
- [x] 1.3 `plan_git_masks`: treat a root that is itself a git directory (`HEAD`, `objects`, `refs`) as a git dir to mask/pin, then continue with `.git` discovery beneath roots. Verify: launcher test masks a bare-named common dir's hooks.

## 2. Baseline

- [x] 2.1 `tjor_gitcheck.discover`: skip a root that is a git directory (documented). Verify: unit test — a git-dir root yields no repo entry and no walk; the worktree entry still records the common dir's config/hooks/worktrees.

## 3. Tests

- [x] 3.1 `tests/integration/worktree_test.sh` (daemon-free, sources `bin/tjor`, docker shim): linked worktree → common dir appended writable + announced; `--dir-ro` worktree → read-only; common dir under an existing root → nothing added; shared common dir → once, writable; planted pointer without back-link → refused (names mismatch, never reached docker); unresolvable pointer → refused with the pointer named; symlinked `.git` → refused; sensitive target → refused without `--unsafe-dir` override; separate-git-dir checkout → accepted; `plan_git_masks` masks a bare-named git-dir root. Add to the CI unit job and to `gen_boundary_matrix.py` as the `worktree` suite; regenerate `docs/boundary-matrix.md`.
- [x] 3.2 Live (landlock suite, new section): launch from a worktree whose main repo lies outside the workspace; in-cage `git status`, `git log`, `git commit` succeed; the launch announced the common dir mount and its hooks mask; the main repo's `pre-commit` hook does not fire; `tjor down` clean. Verify: suite passes on colima.
- [x] 3.3 Existing suites stay green: pytest, gitcheck, workspace-gate, self-mount, shellcheck, doc lint.

## 4. Docs

- [x] 4.1 README multi-repo section: worktrees paragraph (what is mounted, validated how, what is refused, the exposure). Config comment for `mask_git_hooks` mentions the common dir. Verify: `tests/doc_consistency.sh`.
- [x] 4.2 CHANGELOG `[Unreleased]` — Added entry referencing #77/#79.
- [x] 4.3 Sync the three delta specs at archive; `openspec validate --specs`.

## 5. Observations (live, colima, Landlock ABI 4)

- [x] 5.1 Before: `tjor run` from a linked worktree → agent container exit 128, `fatal: not a git repository: …/main/.git/worktrees/feature` at the entrypoint's first `git config --system`, no harness. After: launch announces `+ worktree common dir …/main/.git (for …/feature; mounted writable …)` and `+ dir mask …/main/.git/hooks (git hooks)`; in-cage `git status`, `git log`, `git commit` succeed; the commit lands in the main repository; the main repository's `pre-commit` hook does not fire; `git rev-parse --git-common-dir` in-cage returns the host path. Suites: worktree 20/20, landlock 67/67 (58 + 9), gitcheck 44/44, workspace-gate 60/60, self-mount 45/45, pytest 502.
- [x] 5.2 `git init --separate-git-dir` leaves `core.worktree` unset (verified), so that layout is accepted only with the explicit back-link; the refusal names the one-line fix.
