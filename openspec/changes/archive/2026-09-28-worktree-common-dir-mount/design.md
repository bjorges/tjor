# Design

## Context

See proposal.md — Why. Mount roots are assembled in `cmd_run` (workspace, `--dir`, `--dir-ro`), then judged by the mixed-writability rule and the self-mount guard, then `run_agent` mounts them at their host paths, publishes them to the cage as `TJOR_SAFE_DIRS`/`TJOR_RO_DIRS` (git trust and the kernel tier's grants derive from that list), plans the launch-time masks over them (`plan_git_masks`, `mask_dirs`, dotenv) and records the git-check baseline over the writable ones. Host path == container path for every repo mount, so a `.git` file's absolute `gitdir:` pointer is valid in-cage once its target is mounted. `git rev-parse --git-common-dir`/`--git-dir` read config and run nothing configured (no hook, pager, fsmonitor, credential or ssh command on that path) — the same reasoning `plan_git_masks` already relies on. `workspace_toplevel` already accepts a linked worktree as the workspace (containment holds), so the launcher side proceeds today; only the cage is broken.

## Goals / Non-Goals

**Goals:**
- A linked worktree (and a `--separate-git-dir` checkout) works as the workspace or as a `--dir`/`--dir-ro` with no new flag.
- Nothing is mounted on the strength of a `.git` file alone: git's own linkage must confirm the target belongs to this root.
- The common directory inherits every guarantee a mount root has; no parallel code path.

**Non-Goals:**
- Mounting the main repository's *working tree* (only its git directory is needed; the operator can `--dir` the main checkout).
- A new mount class or flag; a config knob to disable the mount (an operator who does not want it launches from the main repository).
- Making git work for a `--dir-ro` parent that holds worktrees whose common dir lies elsewhere beyond what the rule above gives.

## Decisions

- **D1 — Resolve in `cmd_run`, feed the existing lists.** A resolver runs after the `--dir`/`--dir-ro` gates and before the overlap rule, appends each accepted common directory to `TJOR_EXTRA_DIRS` (or `TJOR_EXTRA_DIRS_RO`), and everything downstream — overlap rule, self-mount guard (a worktree of the tjor checkout itself is refused as a writable self-mount, correctly), `run_agent` mounts, `TJOR_SAFE_DIRS`, masks, baseline — sees an ordinary root. Alternative: a separate "common dir" mount class with its own handling in each consumer — more code, more places to miss.
- **D2 — Git's linkage is the authority, not the pointer.** Accept only when `--git-common-dir` resolves to a git directory (`HEAD`, `objects`, `refs`) AND the private dir's `gitdir` file names this root's `.git` (linked worktree) or the git dir's `core.worktree` names this root (separate git dir). A planted `.git` file saying `gitdir: ~/.ssh` or `gitdir: /other/private/repo/.git` fails both (git refuses the first outright; the second has no back-pointer to this root) and refuses the launch. Alternative considered: path containment (target under some ancestor) — a planted pointer to a sibling repo would pass.
- **D3 — Sensitive target: refuse, no override.** `dir_is_sensitive` on the resolved common directory refuses with no `--unsafe-dir` downgrade: the operator did not name this path, git's pointer did.
- **D4 — Writability follows the worktree; shared common dirs mount once, writable if any sharer is.** Two worktrees of one repository given `--dir` and `--dir-ro` would otherwise trip "given via both" on the common dir. A writable worktree whose common dir lies under a read-only root gets no extra mount and a warning that commits will fail there (the operator chose the read-only parent).
- **D5 — Masks cover a root that is a git directory.** `plan_git_masks` finds `.git` entries *under* roots; a common directory root named `.git` is found (find tests the starting point) but a bare `repo.git` is not, so the planner first treats any root holding `HEAD`, `objects` and `refs` as a git directory and masks its hooks (pins its config when opted in).
- **D6 — The baseline does not walk a git directory.** `discover` skips a root that is a git directory: walking `objects/` is cost without signal, and the worktree entry already records the common directory's config, hooks and `worktrees/*` pointers through the `.git` file.
- **D7 — Refuse at launch, never fail in-cage.** Every rejection (unresolvable pointer, no back-link, symlinked `.git`, sensitive target) is a `die` before any container starts, naming the pointer, the resolved path and the fix (`git worktree repair`, launch from the main repository, replace the link).

## Risks / Trade-offs

- Mounting `<main>/.git` writable exposes the whole repository's history, refs and config to the agent — what a worktree of that repository already implies, and what the operator asked for by launching there; the announce line says so. Other worktrees' private dirs under `<main>/.git/worktrees/*` are writable too; the baseline records their pointers and reports changes.
- The main repository's *hooks* are masked only because the common dir is now a writable root — `mask_git_hooks = false` restores them, as documented.
- `git rev-parse` runs host git in the worktree before the session: config-driven execution is not reachable on that path (same as the existing plan_git_masks call); a corrupt config makes it fail, which refuses the launch with git's error.
- A `--dir-ro` worktree mounts its common dir read-only: `git status` works (index refresh failing is non-fatal); commits fail, as for any read-only root.
