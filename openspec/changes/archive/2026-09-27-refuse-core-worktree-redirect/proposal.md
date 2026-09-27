# Proposal

## Why

#76 asked whether a cage-written `core.worktree` can redirect where the **next host-side launch** resolves the workspace. Reproduced, on plain git and through tjor's own resolver: with `core.worktree = <path>` in a repo's `.git/config`, `git rev-parse --show-toplevel` run anywhere inside that repo answers `<path>`. A session always has its workspace repo mounted writable, so it can plant that line. On the operator's next `tjor run` from the same repo, tjor took `<path>` as the workspace **silently** when `<path>` was not in the sensitive set — a different directory (a project the session never had, or a parent holding every repo the operator owns) mounted writable and git-trusted as a tree, under a session id derived from *that* path. A redirect to `$HOME` is caught by the #64 gate, but with the wrong words ("… is not a repository"), and `down`/`status`/`reset` under any redirect act on the wrong session.

Git exposes the honest signal: for every legitimate resolution — a plain repo, a subdirectory, a linked worktree, a symlinked spelling (both sides physical) — the launch directory lies **inside** the reported toplevel. Only a redirect breaks that containment (`--is-inside-work-tree` also turns false).

## What Changes

- **The resolved workspace must be the repository found above the launch directory.** The launcher walks up from the physical launch directory to the nearest `.git` entry on its own and requires git's reported toplevel to be exactly that directory. Containment alone was tried first and rejected by the regression test: a redirect to an ancestor (the folder holding every repo, or `$HOME`) still contains the launch directory. A mismatch is refused, naming the reported work tree, the launch directory, the repository found and — when set — the `core.worktree` value and its config file, with the remedy (`git config --unset core.worktree`, or launch from the real work tree). No override flag: there is no legitimate reason for tjor to run from a repo whose work tree is elsewhere.
- **Applies to launch and lifecycle resolution alike.** A redirect must never make `down`, `status`, `reset` or `denials` act on another session; the fully-qualified session id remains usable from any other directory.
- **The #64 refusal keeps its precise wording.** With containment checked first, a redirect toward a sensitive path is reported as a redirect, not as a git climb; the climb message still covers the honest case (launching from a non-repository directory under a sensitive toplevel).
- **The reproduction is a permanent regression test**, as #76's acceptance requires: the `workspace-gate` suite gains a section that plants `core.worktree` toward a harmless directory and toward `$HOME`, asserts both refusals and the message, and asserts a linked worktree and a subdirectory launch still work. One boundary-matrix row.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `session-launch`: a new requirement — *The resolved workspace must contain the launch directory* — with scenarios for the harmless-path redirect, the sensitive-path redirect, the linked worktree, the subdirectory launch, and the lifecycle command.

## Impact

- **Code**: `bin/tjor` `resolve_session` — containment check right after the toplevel is resolved, before the #64 gate, on every resolution path.
- **Tests**: `tests/integration/workspace_gate_test.sh` — a `core.worktree` section (daemon-free, `unit` job); `python/gen_boundary_matrix.py` REGISTRY entries; `docs/boundary-matrix.md` regenerated.
- **Docs**: CHANGELOG `[Unreleased]` (Security: #76 confirmed and fixed); README one sentence next to the sensitive-path paragraph.
- **Behavior change**: launching or running lifecycle commands from inside a repository whose `core.worktree` points outside itself is refused. Legitimate git usage is unaffected: worktrees, submodules, subdirectories and symlinked paths all satisfy containment.
- **Related**: #72 (detect cage-written git metadata that runs on the host) covers the broader class; this change closes the one route that steered tjor's own workspace resolution.
