# Design

## Context

See proposal.md for the motivation. What shapes the approach (observed in the code unless marked):

- Every writable extra root passes one pipeline in `cmd_run`: physical-path resolution, `gate_sensitive_path --dir`, dedupe against the workspace, the worktree common-dir rule, the mixed-writability refusal, the self-mount guard; `run_agent` then verifies the bind source, mounts it at its host path, registers git trust as a tree, runs mask discovery and the git-check baseline over it, and hands it to the kernel sandbox allowlist. A root appended to `TJOR_EXTRA_DIRS` after the `--dir` loop gets all of that.
- `resolve_session` is called by the launch AND by `down`, `status`, `denials`, `reset`, `prune` and `git-check`, under a no-side-effects contract (#68); every lifecycle caller passes the harness `opencode` literally. The session root is read once, before `TJOR_REPO_ROOT` is exported, precisely so a trusted repository config cannot answer differently (`session_root_init`).
- `tjor_cfg.effective()` layers defaults, user config and a trusted repository config; `check()` warns on unknown keys except under `SECURITY_TABLES`, where it aborts.
- `verify_bind_source` returns early on an empty directory (nothing to compare).
- The session id is `<repo>-<hash8>[-<short>]`; `TJOR_PROJECT = tjor-<id>` becomes the Compose project name. The short-name grammar allows dots; Compose project names do not (review): a pre-existing edge for `--session a.b`, not widened here because task ids are dot-free.
- `GIT_CEILING_DIRECTORIES` stops discovery only above the listed directory, not at it (review, verified by the reviewers).
- Identity headers are a fixed table in `tjor_identity.py` (`x-agent-task-id` already carries the id); unknown `x-agent-*` headers are stripped toward every host.

## Goals / Non-Goals

**Goals:**
- One opt-in setting, in the user's own config, turns `--task <id>` into a mounted, writable notes directory with a per-task session, without widening what the cage can reach beyond that one directory.
- Every path-safety rule the launcher already has applies to the notes directory by construction; the checks this change adds are inode-based and descriptor-relative, not string-based.
- The notes repository above the directory can never become the workspace by accident.

**Non-Goals (deferred, with the review's reasons):**
- `--workspace <dir>`: changing directory before argument parsing re-bases every relative `--dir`, `--dir-ro` and `--profile-dir`, and the lifecycle commands would need the flag too. The operator's `cd` does the same today.
- `--notes-workspace`: a second workspace mode touching config provenance, the harness cwd, git environment, session identity and lifecycle lookup; `GIT_CEILING_DIRECTORIES` set to the directory itself does not stop discovery, and a worktree common dir could still be mounted from above. The notes mount stands on its own; a repo-less task launches without `--task`, exactly as today.
- `--task <id>` on the lifecycle commands: they do not know the harness, and with the short name equal to the id, `--session <id>` is the same keystrokes without guessing.
- Anything the harness does with the directory (#73); sharing notes between hosts; per-task secrets.

## Decisions

### D1. Resolution, creation, identity checks and the scan live in one Python helper

`python/tjor_task.py`, called by the launcher: `resolve --template T --task ID` (no side effect: validates the template and the id, prints the directory's intended path, the physical prefix and the relative part below it, exit 1 with a reason otherwise); `create --prefix P --relative R` (the descriptor-relative walk of D4); `contains A B` (inode ancestry of D5); `scan DIR` (D9). Unit-tested in `python/tests/test_task.py`. Rationale: `openat`-style traversal, `fstat`-based identity and a bounded scan belong in Python with tests, and the launcher already shells out to helpers this way. Alternative: bash; rejected for exactly the edge cases the review listed.

### D2. The template and its fixed prefix

`task.notes_dir` must be absolute after expanding a leading `~` and hold `{task}` exactly once (no other brace). The fixed prefix is the path up to, not including, the first component holding `{task}`; it must already exist as a real directory and tjor never creates it. Rationale: creating the operator's notes root silently is how a typo becomes a new tree.

### D3. The task id becomes a plain lower-case name when it is a path

With `notes_dir` configured the id must match `^[a-z0-9][a-z0-9_-]{0,31}$`. No dot: `.`, `..` and hidden names are impossible, and the derived session name never contains one (Compose project names reject dots). No upper case: one spelling per directory whether the filesystem folds case or not; the id is also lower-case on the wire and in labels as today. At most 32 characters: the id is the session's short name as-is, so there is no truncation and no two ids map to one name (review item 4). Without `notes_dir` the old grammar stays (the compatibility promise is literal). Alternative: keep the old grammar and lower-case for the session only; rejected because `A` and `a` would be two directories and one session.

### D4. Creation is launch-only, after the gate and the lock, and descriptor-relative

`resolve_session` only resolves (D1 `resolve`) and exports `TJOR_TASK_DIR`; it creates nothing, so lifecycle commands keep their no-side-effects contract. In `cmd_run`, after `gate_sensitive_path --dir` has accepted the intended path and `session_lock_acquire` holds the lock, `create` walks from the prefix: open the prefix (`O_DIRECTORY`), then for each relative component `openat(parent_fd, name, O_DIRECTORY|O_NOFOLLOW)`; on `ENOENT` and `create = true`, `mkdirat(parent_fd, name)` then open the same way; `ELOOP`/`ENOTDIR` refuse naming the component; `fstat` of the final descriptor gives its identity. The final directory's identity, not its path string, is what later checks use. Residual, stated in the README: the engine receives the bind source as a path, so a component swapped between the walk and the container start is outside what the launcher can see (the same window every mount has today). Alternative: `lstat`/`mkdir`/`realpath` by path; rejected as raceable by a swapped component (review item 9).

### D5. The notes-root refusal is by filesystem identity and has no override

`contains WORKSPACE PREFIX` walks the prefix's parent chain by `(st_dev, st_ino)` and reports whether any ancestor (or the prefix itself) is the workspace; a match refuses the launch naming both paths. `--unsafe-dir` does not cover it: that flag means "mount this sensitive path anyway", this refusal means "you are about to mount every task", and the remedy is to launch from the code repository. Alternative: string comparison of physical paths; rejected because macOS folds case and normalises Unicode in path names, so two spellings of one directory compare unequal and the refusal fails open (review item 8).

### D6. The mount is covered-aware and the share check uses the root when the directory is empty

In `cmd_run`, after the `--dir` loop: if `contains` says the workspace or a `--dir` root is the directory or an ancestor of it, the directory is already mounted writable and is not appended (one mount, one scan, one grant); otherwise it is appended to `TJOR_EXTRA_DIRS` with `gate_sensitive_path --dir`. A directory under a read-only root is refused by the existing writable-under-read-only rule. In `run_agent`, when the notes directory is empty, `verify_bind_source` runs on the notes root instead, which holds at least the directory; an unshared path is refused naming the root (review item 5). Alternative: a probe file written into the notes directory; rejected (writing into the operator's directory to test it).

### D7. `[task]` is user-config only and a security table

`tjor_cfg.effective()` drops the `task` table from the repository layer before merging and `check()` warns, naming the file, when a trusted repository config carries one; `task` joins `SECURITY_TABLES`, so an unknown key under it aborts. Rationale: no configuration key creates a writable host mount today, and a repository must not be able to choose one even after approval (review item 2); a feature that is silently off because of a typo is the failure class `SECURITY_TABLES` exists for. The repo-config-trust spec and its slide state this.

### D8. One session per task is the task id itself

With `session_per_task = true` and `--task <id>`: `resolve_session` sets the short name to the id after the `--session` canonicalisation block (never through it: `a-12345678` would otherwise be looked up as a foreign qualified id) and derives `sid = <base>-<id>`. `--session` with `--task` is a usage error. The launch prints the id as the session name. Every lifecycle command then addresses it as `--session <id>` from the workspace, and `tjor ls` shows the `tjor.task` label. Rationale: injective by construction, no harness prefix to guess, no truncation (review items 1 and 4). Alternative: `<session>.<id>` composites; rejected as not injective and as costing the lifecycle commands a harness they do not know.

### D9. The scan is bounded, link-free and honest about partial results

`scan DIR`: walk at most 8 levels and 5000 entries, skip `.git`, never follow links, open candidates with `O_NOFOLLOW|O_NONBLOCK` and keep only `S_ISREG` descriptors (a FIFO is skipped, not read); name a file whose basename, split on `.`, `_` and `-`, has a segment in {`token`, `tokens`, `credential`, `credentials`, `secret`, `secrets`, `password`, `netrc`, `npmrc`, `kubeconfig`}, ends in `.pem`, `.key`, `.p12` or `.pfx`, or starts with `id_` (so `tokenizer.md` is not a match); read regular files up to 256 KiB each and 16 MiB in total through `tjor_secrets.kinds_present`. The launcher prints a loud warning listing at most 10 findings (sanitised) and a count; when a bound was reached or a file could not be opened the warning says the scan was partial. It runs on the launch path after the gates and before the agent, within the bounds above. Alternative: refuse; rejected (the operator's own directory). Alternative: scan off the launch path; rejected for now, the bound keeps the cost small and the warning is most useful before the agent starts.

### D10. `tjor attach --task <id>` filters on the label

`cmd_attach` gains argument parsing (`--task <id>`, else the positional session as today); the candidate rows, which carry the `tjor.task` label, are filtered on it instead of on the session id; single match, picker and none are unchanged. The label is global, so the same id in two repositories offers the picker.

### D11. The default configuration keeps the feature off

`config/tjor.toml` gains `[task]` with `notes_dir = ""`, `create = true`, `session_per_task = false`, commented. Empty `notes_dir` skips every new behaviour, which is how the "unchanged without configuration" scenarios are met.

### D12. Proof

- `python/tests/test_task.py`: template validation; the grammar; `create` (per-component creation, a link at a component, a file at a component, prefix never created, `create = false`); `contains` (ancestor, self, sibling, a differently-spelled path to the same directory where the filesystem folds case, detected at test time); the scan (names, content, bounds reported, a FIFO and a link skipped).
- `python/tests/test_cfg_and_corefile.py`: the repository layer's `[task]` is dropped with a warning; an unknown key under `[task]` in the user config aborts.
- `tests/integration/task_notes_test.sh` (docker-free, modelled on `workspace_gate_test.sh`): the mount list, the covered case, the refusals (notes root as workspace, bad ids, bad template, sensitive template with nothing created, link below the prefix), `--session` with `--task`, lifecycle resolution creating nothing, the warning, and the unchanged path without `[task]`; registered in the boundary matrix as the launcher-side `task-notes` suite.
- Live: one case in `multirepo_test.sh` (mounted writable at its host path, `TJOR_TASK_DIR` set, the repository still the workspace, the session named by the task id) and one in `lifecycle_test.sh` (two task sessions up at once, `down --session a` leaves `b` running, Compose project names distinct).

## Risks / Trade-offs

- [The directory is writable and git-trusted as a tree, like any `--dir`; nested repositories, links and secrets written there reach the host notes repository] → stated as residuals in the README; the operator chose a per-task directory, not the notes root.
- [Every session launched with the same task id shares the directory] → stated; it is the feature.
- [The bind source is a path for the engine] → stated; the launcher's checks are by descriptor and identity, the window after them is the same every mount has.
- [`[a-z0-9][a-z0-9_-]{0,31}` refuses ids an operator already uses as labels, such as `JIRA-123`] → only once `notes_dir` is configured, with a message naming the grammar; the label-only grammar is unchanged.
- [The scan has false positives] → advisory only; findings are named so the operator can judge.
- [A notes directory inside the workspace repository] → covered, not mounted twice; nothing new is exposed.
