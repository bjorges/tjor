# Proposal

## Why

A writable repo mount exposes `<repo>/.git/hooks/` and `<repo>/.git/config`. A hook the cage writes, or a config key it poisons (`core.hooksPath`, `core.fsmonitor`, filter drivers), runs code in the operator's **host** git the next time an ordinary git command touches that repo — outside every tjor boundary. This is true today for every writable mount, starting with the workspace itself (#71). #76 closed the one config key that steered tjor's own resolution; the hooks directory is the classic, no-config-needed route, and it is structurally maskable with machinery tjor already has: the read-only empty bind that `mask_dirs` uses for `.opencode`.

## What Changes

- **`[landlock] mask_git_hooks = true`, on by default.** At launch, for every git directory discovered under a **writable** mount root — the workspace repo, each `--dir` repo, repos nested under a mounted parent, and a linked worktree's common git directory when it lies under a writable root — `<gitdir>/hooks` is bind-mounted over with a read-only empty directory. In-cage, the hooks directory lists empty, nothing can be created in it, and it cannot be removed or replaced; git runs no hooks from it. A repo whose `hooks` directory is absent gets an empty one created on the host first so the mask has a mountpoint. Each mask is announced escape-sanitized. **BREAKING, by design:** hooks installed on the host (pre-commit, lefthook, husky) stop firing on in-cage commits; `mask_git_hooks = false` restores the old behavior.
- **`[landlock] protect_git_config = false`, opt-in.** When enabled, each discovered `<gitdir>/config` (the common directory's for a worktree) is pinned read-only with a single-file bind of the real file over itself. Reads work; every write fails, because git replaces the file by rename and a mountpoint cannot be renamed over. This is the only *preventive* control here against `core.hooksPath` / `core.fsmonitor` / filter redirection. **Cost, stated:** `git config`, `git remote add`, `push -u`, `branch --set-upstream-to`, `worktree add -b` with tracking and `gh pr checkout` fail in-cage; `commit`, `push` without `-u`, `fetch`, `status`, `log`, `diff` work. The exact list is verified live and recorded.
- **Honest limits, documented not implied.** With hooks masked alone, `core.hooksPath` bypasses the mask; the config pin is what closes that, at the cost above. Neither control stops a re-pointed worktree `.git` file, a retargeted `commondir`, or a nested `.git/` planted inside the working tree — #72 covers those, as detection. Sibling repos under one writable parent are not isolated from each other. Masking is a launch-time snapshot: a repo created mid-session is not masked.
- **Coverage.** The `landlock` suite gains a section: hooks listing empty and unwritable in the workspace, a nested repo and a worktree's common dir; a host-installed hook does not fire on an in-cage commit; `mask_git_hooks = false` leaves it in place; with the pin, `git config` and `remote add` fail while `commit` succeeds. Boundary-matrix rows follow.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `kernel-sandbox`: two new requirements — *Git hook directories are masked at launch* and *Operator can pin git config read-only* — alongside the existing dotenv and directory masks. No existing requirement changes; the mixed-writability rule in `session-launch` is untouched because these are mask-class mounts (read-only binds inside a writable tree), the same class the dotenv masks already use, and the design says so.

## Impact

- **Code**: `bin/tjor` `run_agent` — a git-metadata masking block between the `mask_dirs` masks and the dotenv masks (same `masked`/`dirmasked` bookkeeping, same `empty_src`); `config/tjor.toml` — the two keys with comments (the defaults file is the config schema, so this is also what makes them valid).
- **Tests**: `tests/integration/landlock_test.sh` — section A4 (launcher-side masking, runs on any engine); `python/gen_boundary_matrix.py` REGISTRY entries; `docs/boundary-matrix.md` regenerated.
- **Docs**: README kernel-sandbox section (two bullets, the config block, the honest limits); CHANGELOG `[Unreleased]` (Security, **BREAKING** for host-installed hooks); a comment on #10 linking its "targeted LSM denies (git hooks dir)" candidate here.
- **Behavior change**: default on for the hooks mask; opt-in for the pin.
- **Out of scope**: detection of other cage-written git metadata (#72); shrinking the pin's breakage with system-level git defaults (`branch.autoSetupMerge`, `push.autoSetupRemote`) — noted as a follow-up once the breakage is measured against a real profile.
