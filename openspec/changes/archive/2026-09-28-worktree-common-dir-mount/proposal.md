# Proposal

## Why

A linked `git worktree` used as the workspace (or as a `--dir`) cannot run git inside the cage: its `.git` is a *file* pointing at `<main>/.git/worktrees/<name>`, a path outside every mount root, and git treats a `.git` file whose target is missing as a hard error for every command — so even the entrypoint's `git config --system` dies and the session exits 128 before the harness starts (reproduced in #77, filed as #79). Worktree-per-task is the natural unit for agent work; today it is silently unusable.

## What Changes

- At launch, every mount root whose `.git` is a file (a linked worktree, or a `--separate-git-dir` checkout) gets its git directory resolved and **validated by git's own linkage** — the common directory must be a git directory and must point back at this root — and mounted alongside the root at the same host path with the root's writability, unless it already lies under a mount root. A pointer git cannot resolve, a linkage that does not point back, a symlinked `.git`, or a sensitive target refuses the launch with the reason; nothing is ever mounted on the strength of the pointer alone.
- The mounted common directory is a mount root in every existing sense: the #71 hooks mask (and opt-in config pin) covers it — including a bare-named common directory — the kernel tier grants it, git trust registers it, the mixed-writability rule judges it, and the git-check baseline treats it as a root without walking a git directory for nested repositories.
- The launch announces each common-directory mount with the worktree it serves.

## Capabilities

### New Capabilities
<!-- none: this extends how mount roots are formed -->

### Modified Capabilities
- `session-launch`: a new requirement — a linked worktree's common git directory is mounted alongside it, validated, announced, refused when the linkage or target is unsafe.
- `kernel-sandbox`: the hooks-mask requirement covers a worktree's common directory mounted this way and a mount root that is itself a git directory.
- `git-tamper-detection`: the baseline requirement states that a root which is itself a git directory is not walked (its metadata is recorded through the worktree that links to it).

## Impact

- `bin/tjor`: a `worktree_common_dirs` resolver in `cmd_run` (before the overlap and self-mount rules) that appends validated common directories to the `--dir`/`--dir-ro` lists; `plan_git_masks` masks a root that is itself a git directory.
- `python/tjor_gitcheck.py`: `discover` skips a root that is a git directory.
- Tests: a daemon-free launcher suite (`tests/integration/worktree_test.sh`, CI unit job, boundary matrix `worktree` suite); a live section in the landlock suite (git status/log/commit from a worktree workspace; the common directory's hooks masked); a unit test for the discover rule.
- Docs: README multi-repo section, CHANGELOG, the three specs.
