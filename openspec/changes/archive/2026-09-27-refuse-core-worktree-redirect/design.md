# Design

## Context

See proposal.md — Why. Grounding (observed at v0.20.1; the ancestor-redirect finding came from the regression test written for this change):

- `resolve_session` (`bin/tjor`) sets `ws="$(git rev-parse --show-toplevel)"` and `in_repo=1`, else falls back to `pwd -P`. The #64 gate follows on the launch path, then `session_base_id "${ws}"` derives the session id, and the state directory is created at the end. Lifecycle commands call `resolve_session` without the `launch` marker and use the same `ws`.
- Reproduction on this machine: with `core.worktree` set, `--show-toplevel` from `repo/sub` prints the configured path; `--absolute-git-dir` still prints `repo/.git`; `--is-inside-work-tree` prints `false`; `--show-prefix` prints nothing. Through the sourced resolver, a redirect to `other-project` was accepted (`workspace=…/other-project`, `session=other-project-…`); a redirect to `$HOME` was refused by the #64 gate with the git-climb wording; the lifecycle path resolved `home-…`.
- `tests/integration/workspace_gate_test.sh` already builds the throwaway layout (`$HOME` repo, `proj`, custom session root, docker shim) and feeds the boundary matrix as the `workspace-gate` suite.

## Goals / Non-Goals

**Goals:**
- Never adopt a workspace that does not contain the launch directory; say why in git's own terms.
- Keep every legitimate git layout working: subdirectories, linked worktrees, submodules, symlinked paths.
- Land the reproduction as a permanent regression test (#76 acceptance).

**Non-Goals:**
- Detecting or preventing other cage-written git metadata (hooks, `core.hooksPath`, `core.fsmonitor`) — #71/#72.
- Re-implementing git discovery ("find the nearest `.git` ourselves", as #76 suggested) — containment against git's own answer is simpler and covers the same case.

## Decisions

1. **A second discovery, exactly as #76 proposed — containment turned out insufficient.** The first cut required only that the reported toplevel *contain* the launch directory. The regression test caught the gap: a redirect to an **ancestor** (the directory holding every repo, or `$HOME`) still contains the launch directory and would have been accepted or mis-reported. So the launcher walks up from `pwd -P` to the nearest `.git` entry (`nearest_git_root`) and requires git's toplevel to equal it. Every honest layout agrees: a plain repo (`.git` dir), a linked worktree or submodule (`.git` file at the worktree root, which is also git's toplevel), a nested repo (the inner `.git` wins on both sides), a symlinked spelling (both physical). *Alternative rejected:* `--is-inside-work-tree = false` — it is `true` for an ancestor redirect too.
2. **Checked right after the toplevel is resolved, before the #64 gate, on every resolution path.** Before the gate so a redirect toward `$HOME` is reported as a redirect. On lifecycle paths too: acting on the session derived from the redirected path is a wrong-target teardown or reset. The fully-qualified `--session <id>` from another directory stays the escape hatch (lifecycle commands honor it verbatim).
3. **No override.** `--unsafe-dir` is about sensitivity of a chosen path; this is about the integrity of the choice. A repository with `core.worktree` elsewhere (a detached-git-dir layout) is not a tjor workspace by construction — the operator launches from the real work tree instead.
4. **The message names the mechanism.** `git config --get core.worktree` and `--absolute-git-dir` are read only on the failure path; the error names the launch directory, the reported work tree, the setting and the file, and the two remedies. If `core.worktree` is unset yet containment fails (a `GIT_WORK_TREE` env or `git -C` exotic), the message omits the setting clause.
5. **Regression test in the existing `workspace-gate` suite.** A new section plants `core.worktree` on a fresh repo: redirect to `proj2` (harmless) refused with the setting named; redirect to `$HOME` refused with the containment wording and without the climb wording; a linked worktree launches; `repo/sub` launches; the lifecycle path refuses under a redirect; no state dir after refusals. One rendered matrix row: *A core.worktree redirect of the workspace is refused*.

## Risks / Trade-offs

- [Detached-git-dir layouts (`core.worktree` pointing outside the repo dir) are refused] → intended; the remedy is to launch from the real work tree. Called out in CHANGELOG.
- [Lifecycle commands refuse under a redirect, so `tjor down` from the tampered repo needs the qualified id from elsewhere] → documented in the error; safer than tearing down another session.
- [`GIT_WORK_TREE` in the operator's environment would trip the check] → rare; the message says what git reported and why it was refused.

## Migration Plan

Additive refusal, patch release. Rollback is a revert.

## Open Questions

None.
