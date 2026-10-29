# Design

## Context

See proposal.md — Why. What exists today, and shapes the approach:

- A session's state root is `<session.root>/<session-id>` (`resolve_session` in `bin/tjor`, default `~/.tjor/sessions`). The launcher creates `home/` there and later writes `policy.toml`, `Corefile`, `proxy-ca/`, `ca.pem`, `broker/`, `profile/`, `mask-empty/`, `gitcheck/`, and the `denials.log`/`logvolume.log`/`secretscan.log` files. Nothing records the workspace, harness or task the directory belongs to; only the container labels do, and they are gone once `gc` or `down` has run.
- `cmd_reset` owns the only definition of the `cache`, `sessions`, `creds` and `all` tiers (a bash `case`), refuses a running session unless `--force` (TOCTOU: a live agent can swap a directory for a symlink between the check and the `rm`), and passes every target through `ancestors_are_real_dirs` (charter L26: `rm -rf` follows a symlink in the path prefix).
- `cmd_gc` and `cmd_ls` discover sessions from container labels only, by design (never by name parsing). A session's "running" state is "any container with `tjor.session=<id>` in state running".
- Git tamper detection keeps the baseline and a pending marker at `<state>/gitcheck/` — a session that was never checked after launch still holds unreviewed evidence; `tjor ls` surfaces it via `gitcheck_pending_report`.
- The launcher already requires python3 and calls small helpers under `python/` (`tjor_cfg.py`, `tjor_gitcheck.py`, `tjor_safeprint.py`, …) with newline- or JSON-shaped output; each has pytest coverage. GNU and BSD `stat`/`find` differ in flags, so the repo keeps filesystem logic in Python when it has to run on both macOS and Linux.
- The lifecycle integration suite runs live on the Linux engine in CI and is not a boundary-matrix probe suite, so new checks there need no registry entry.

## Goals / Non-Goals

**Goals:**
- An operator can see every state directory, what it belongs to, how stale it is, and whether it holds credentials, without reading `~/.tjor/sessions` by hand.
- Deleting state stays explicit, dry-runnable, refuses anything in use, and goes through the same symlink guard `reset` uses.
- One definition of the state tiers, so `reset`, `ls --state` and `prune` cannot disagree about what a credential path is.
- No change to `gc`, `down`, the cage, the proxy or the images.

**Non-Goals:**
- Revoking brokered credentials from prune. Revocation is the proxy's teardown job (`down`/`gc`); a session with no containers has either been revoked already or lost its topology outside tjor. Prune forgets, exactly as `reset creds` does today, and the docs say so.
- Automatic or scheduled pruning, or a retention policy in config. The gc invariant ("never deletes state") stays the only implicit cleanup.
- Pruning anything outside `session.root` (the `~/.tjor/tmp` scratch of conformance runs, the install tree, user config).
- A migration that backfills metadata for legacy directories. They read as unknown; the next launch of that session writes the file.

## Decisions

**D1. A Python helper, `python/tjor_state.py`, owns the tier definitions and the inventory; bash owns the docker checks and the deletion.**
Subcommands: `tier <name>` (the tier's paths, newline-separated, relative to a state directory; `all` is the directory itself), `inventory <root> --json` (one record per entry: id, is-directory, metadata or null, last activity epoch, credential paths present, size is deliberately not computed), `meta-write <dir> --workspace … --harness … --profile … --task …` (read-modify-write with a temp file and `os.replace`; preserves `created`, bumps `launches`), and `duration <text>` (→ seconds, accepting `Nd`, `Nh`, `Nm`, `Ns`).
Why: the lstat walk, the JSON, and duration parsing are where a bash-only version would be either non-portable (`stat -c` vs `stat -f`) or wrong; the helper is unit-testable with `tmp_path`. Deletion and the running check stay in bash because `ancestors_are_real_dirs`, `resolve_session` and the label queries already live there and are the audited code.
Alternative: all-bash with `find -newer`/`stat`. Rejected for portability and testability. Alternative: everything in Python including `rm`. Rejected: it would duplicate the symlink guard the lifecycle suite already exercises.

**D2. `cmd_reset` reads its tier paths from the helper.**
The bash `case` becomes `mapfile -t paths < <(python3 tjor_state.py tier "${tier}" "${TJOR_SESSION_DIR}")`. The refusal, dry-run and guard logic is unchanged, and the existing reset checks in the lifecycle suite (tier contents, symlink leaf, intermediate symlink refusal) guard the refactor.

**D3. "Running" means any container of the session, agent or sidecar, and docker being unreachable is a refusal.**
Prune refuses if `docker ps --filter label=tjor.session=<id> --filter status=running` returns anything; `ls --state` shows `yes`/`no`, or `?` when docker cannot be queried, and prune then refuses every session (fail closed, as the `--session` resolver does when it cannot disambiguate). No `--force` for the running refusal: `reset --force` exists to accept the live-swap race for a session the operator is deliberately resetting; prune is bulk deletion and the correct move is `tjor down`.

**D4. Last activity is the newest `lstat` mtime over the state directory and its contents to a depth of three, never following symlinks, with the recorded last-launch time as a floor.**
Why: legacy directories have no metadata, and `home/` holds the harness history whose mtime is the honest signal. Depth three covers `home/.local/share/<harness>/…` without walking caches; `os.walk(followlinks=False)` plus `os.lstat` means a planted link never pulls in an outside tree's timestamps or a walk through it.
Alternative: metadata only. Rejected: says nothing for legacy directories, which are the ones that need pruning.

**D5. Selectors are mandatory and `--session` resolves like `reset`'s.**
A bare `tjor prune` is usage, exit non-zero. `--older-than` compares the cutoff with D4's last activity. Each `--session` value goes through `resolve_session` (short name qualified against the current workspace; a fully-qualified id of another workspace honored verbatim; the same idempotent rules as `down`/`reset`), so the ids `ls --state` prints paste back in. The two selectors combine as a union.

**D6. A pending git-check marker refuses unless `--force`.**
`<state>/gitcheck/pending` existing means the baseline was never reconciled: deleting the directory destroys the evidence of cage-written git metadata the operator has not looked at. The refusal names `tjor git-check --session <id>` (and `--ack`) as the way out; `--force` is the explicit "I accept losing it". Charter: degrade loudly, never silently discard a finding.

**D7. Metadata is written by `cmd_run` after every refusal and the broker mint, right before `ensure_topology`.**
A refused launch therefore never creates or touches metadata, and a relaunch updates it before the agent starts. The file is `meta.json` with `schema: 1`, `session`, `workspace`, `harness`, `profile` (`{"name": …}` or `{"dir": …}` or null), `task` (or null), `created`, `last_launch`, `launches`. It is not mounted into the cage and holds no secret. `tjor ls --state` and `prune` read it; nothing else depends on it, so legacy directories cost nothing.

**D8. Deletion order and guard.**
Whole-directory prune: `ancestors_are_real_dirs "${root}" "${dir}"` (the root itself must not be a symlink; the leaf may be, and `rm -rf` on a leaf symlink removes the link), then `rm -rf`. `--creds-only`: for each tier path, `ancestors_are_real_dirs "${dir}" "${path}"` exactly as `reset` does. A refused path is reported with `loud` and the run continues; the exit status is non-zero if anything was refused, so a script notices.

**D9. Output.**
`ls --state` prints a table: `SESSION  RUNNING  LAST-ACTIVE  CREDS  WORKSPACE`, sorted by session id, with `?`/`unknown` where a fact is unavailable, followed by one line per non-directory entry. `ls` without the flag is byte-for-byte unchanged. Prune prints one line per session with the verdict (`would remove` / `removed` / `refused: …`) and the credential flags, so a dry run is a complete preview.

## Risks / Trade-offs

- [TOCTOU between the running check and `rm`, for a session that starts between them] → the window is the same one `reset` accepts under `--force`; prune narrows it by checking immediately before each session's deletion rather than once up front, and a session that starts in that window recreates what it needs in the state root on launch (the launcher `mkdir -p`s and re-mints).
- [A shallow walk under-reports activity for a harness that writes deep in `home/`] → the depth bound is a constant in the helper; the harness directories tjor already knows (`.local/share/opencode/storage`, `.config/gh`) are within depth three, and the metadata floor means a recent launch is never mistaken for stale.
- [`session.root` configured as a symlink] → `ancestors_are_real_dirs` refuses the root itself; prune then refuses everything, loudly, and says why. Correct, if surprising; documented.
- [Huge session roots make `ls --state` slow] → no sizes are computed and the walk is bounded; a thousand directories at depth three is still sub-second.
- [Operators expect prune to revoke] → the output says "forgotten, not revoked" when a broker file is removed, and the README states that revocation happens at `down`/`gc`.

## Migration Plan

None required. Legacy directories show as unknown until their session is launched again. Rollback is removing the two commands; `meta.json` is inert to older launchers.
