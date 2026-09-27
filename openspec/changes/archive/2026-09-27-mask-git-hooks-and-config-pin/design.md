# Design

## Context

See proposal.md — Why, and the delta spec. Grounding (observed at v0.20.4, `bin/tjor` `run_agent`):

- The mask block builds `mounts+=(--volume …)` from three sources in order: `mask_dirs` (read-only **empty dir** `${TJOR_SESSION_DIR}/mask-empty` bound over each target, `dirmasked[]`), automatic dotenv masks and `deny_paths` (read-only `/dev/null` bound over each file, `masked[]`). Directory masks go first so a file mask is never queued inside an already-masked directory (Docker cannot create a mountpoint inside a read-only empty mount). The dotenv `find` prunes `.git`.
- `safe[]` holds every mount root; `ro_dirs` the read-only subset. Announcements go through `safeprint` (paths come from untrusted repos).
- The mask source is recreated per launch under the session state dir (VM-shared), mounted `:ro`.
- Git's config write is lock-and-rename: `config.lock` is created next to `config`, then `rename(2)`'d over it. A bind mount over `config` makes it a mountpoint; rename over a mountpoint fails with `EBUSY`, so every write path git has fails while reads are untouched. Hooks are resolved from `<gitdir>/hooks` unless `core.hooksPath` says otherwise; an empty hooks directory runs nothing.
- `tests/integration/landlock_test.sh` section A3 is the pattern: launch with `mode = "off"` and a probe `sh -c` that writes findings into the repo, read them back, assert; no Landlock support needed for mask checks. `python/gen_boundary_matrix.py` parses its `check "…"` names.
- `config/tjor.toml` is the config schema: unknown keys under `[landlock]` abort the launch, so the two new keys must be in the defaults file.

## Goals / Non-Goals

**Goals:**
- Close the no-config hook route structurally, on every runtime, by default.
- Offer the preventive control for config-based redirection as an explicit, documented trade-off.
- Reuse the existing mask machinery and bookkeeping; no new mount kind beyond what dotenv masks already establish.

**Non-Goals:**
- Detecting cage-written metadata that survives these controls (#72).
- Isolating sibling repos under one writable parent.
- Shrinking the pin's breakage with system git defaults (follow-up, after measuring).

## Decisions

1. **Discovery walks writable roots for `.git` entries; read-only roots are skipped.** For each root in `safe[]` not in `ro_dirs`: `find <root> \( -type d -o -type f \) -name .git` (the existing masks prune `.git`; this one targets it). A `.git` **directory** is its own git dir; a `.git` **file** is a worktree pointer, resolved with `git -C <dir> rev-parse --path-format=absolute --git-common-dir`, and its common directory is masked only if it lies under a writable root (else it is unreachable in-cage anyway). Read-only roots are already unwritable container-wide. *Alternative rejected:* masking only the workspace's `.git/hooks` — nested repos under a `--dir` parent are exactly the case #71 names.
2. **Create a missing `hooks` directory on the host before masking.** A mask needs a mountpoint; without one the agent could `mkdir .git/hooks` and plant a hook. An empty `hooks` directory is inert to git. It is the one host-side write this change makes, announced as such.
3. **Same bookkeeping, same ordering.** The git block runs after `mask_dirs` (a hooks dir inside an already-masked directory is skipped: already empty, and unmountable-into) and before the dotenv masks. Hooks masks register in `dirmasked[]`; config pins in `masked[]`. Same empty source, same `:ro`.
4. **The config pin binds the real file over itself.** `--volume <gitdir>/config:<gitdir>/config:ro`. Reads see the real content; git's rename-over-mountpoint fails; `config.lock` litter is cleaned by git itself on failure. *Alternative rejected:* `/dev/null` over `config` — git would read an empty config, losing remotes and the worktree's identity; `mask_dirs`-style empty dir — not a file.
5. **Defaults: hooks mask on, pin off.** The hooks mask breaks only host-installed hook frameworks in-cage, which a cage should not be running anyway (they execute repo-supplied code). The pin breaks routine git ergonomics; #71's open decision (default-on for untrusted-content profiles) stays open until breakage is measured against a real profile — recorded in the proposal as out of scope.
6. **Coverage in the `landlock` suite, section A4.** Repo with a host `pre-commit` that writes a marker, a nested repo, and a linked worktree under the same root. Launch 1 (defaults): announcements for three hooks dirs; probe: listing empty, `touch` refused, commit succeeds, marker absent; nested and common-dir hooks listed empty. Launch 2 (`mask_git_hooks = false`): no announcement, listing shows the hook. Launch 3 (`protect_git_config = true`): `git config` and `remote add` fail, `commit` succeeds, `git config --list` works, file content unchanged on the host. Matrix rows for the guarantees.

## Risks / Trade-offs

- [Host hook frameworks silently stop running in-cage] → BREAKING, called out in CHANGELOG and README; `mask_git_hooks = false` restores them.
- [A mountpoint under `.git`] → git tolerates it; the dotenv and `mask_dirs` masks already put mountpoints inside repos. `git gc`/`repack` do not touch `hooks`.
- [The pin breaks `push -u` and friends] → opt-in, cost listed verbatim; the operator chooses.
- [Repos created mid-session are unmasked] → the same launch-snapshot residual every mask has; stated.
- [`core.hooksPath` bypass without the pin] → stated in the requirement and README; #72 is the detection companion.

## Migration Plan

Additive; minor bump (breaking for in-cage hook frameworks, pre-1.0). Rollback is a revert; `mask_git_hooks = false` is the runtime opt-out.

## Open Questions

None that change the specs or tasks. Whether the pin should default on for untrusted-content profiles is #71's stated open decision and stays with the maintainer until measured.
