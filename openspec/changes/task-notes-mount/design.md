# Design

## Context

See proposal.md for the motivation. What shapes the approach (observed in the code unless marked):

- Every writable extra root passes one pipeline in `cmd_run`: physical-path resolution, `gate_sensitive_path --dir`, dedupe against the workspace, the worktree common-dir rule, the mixed-writability refusal, the self-mount guard; `run_agent` then verifies the bind source, mounts it at its host path, registers git trust as a tree, runs mask discovery and the git-check baseline over it, and hands it to the kernel sandbox allowlist. A root appended to `TJOR_EXTRA_DIRS` after the `--dir` loop gets all of that.
- `resolve_session` is called by the launch AND by `down`, `status`, `denials`, `reset`, `prune` and `git-check`, under a no-side-effects contract (#68); every lifecycle caller passes the harness `opencode` literally. The session root is read once, before `TJOR_REPO_ROOT` is exported, precisely so a trusted repository config cannot answer differently (`session_root_init`).
- `tjor_cfg.effective()` layers defaults, user config and a trusted repository config; `check()` warns on unknown keys except under `SECURITY_TABLES`, where it aborts.
- `verify_bind_source` returns early on an empty directory (nothing to compare).
- The session id is `<repo>-<hash8>[-<short>]`; `TJOR_PROJECT = tjor-<id>` becomes the Compose project name. The short-name grammar allows dots; Compose project names do not (review): a pre-existing edge for `--session a.b`, not widened here because task ids are dot-free.
- `GIT_CEILING_DIRECTORIES` stops discovery only above the listed directory, not at it (review, verified by the reviewers).
- A dotted `--session` name or a dotted workspace basename already produces a dotted Compose project name today; this change adds no new dots and does not fix that edge.
- `cmd_run` exports `TJOR_WORKSPACE` only at the end of `resolve_session`; inside it the local `ws` is the workspace. `os.supports_dir_fd` on this machine's macOS Python covers `open`, `mkdir`, `stat` and `lstat` (probed); the helper checks it at start and fails closed where it is missing.
- The lifecycle `--session` resolver reads a value equal to the workspace's base id as the default session, a value prefixed by it as its short form, and a qualified-looking value naming an existing session as that session (#52); the launch path bypasses this for a derived name, so a derived name must be one the resolver reads back the same way.
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

### D2. The template is confined and its fixed prefix exists

`task.notes_dir` must be absolute after expanding a leading `~`, already normalised (`os.path.normpath(t) == t`: no `.` or `..` component, no empty component, no trailing separator) and hold `{task}` exactly once, inside one component, with no other brace. The fixed prefix is the path up to, not including, that component; it must already exist as a real directory and tjor never creates it. Every component below the prefix is validated as a plain name (not `.`, not `..`, no separator) before any descriptor is opened, so `openat` never sees a `..` (review item 3: `openat(fd, "..")` opens the parent like any name). Rationale: creating the operator's notes root silently is how a typo becomes a new tree; confinement is decided on the template, not discovered by the walk.

### D3. The task id becomes a plain lower-case name when it is a path

With `notes_dir` configured the id must match `^[a-z0-9][a-z0-9_-]{0,31}$`. No dot: `.`, `..` and hidden names are impossible, and the derived session name never contains one (Compose project names reject dots). No upper case: one spelling per directory whether the filesystem folds case or not; the id is also lower-case on the wire and in labels as today. At most 32 characters: the id is the session's short name as-is, so there is no truncation and no two ids map to one name (review item 4). Without `notes_dir` the old grammar stays (the compatibility promise is literal). Alternative: keep the old grammar and lower-case for the session only; rejected because `A` and `a` would be two directories and one session.

### D4. A fixed order on the launch path: gate, create or validate, judge coverage, mount, scan

`resolve_session` only resolves (D1 `resolve`) and exports `TJOR_TASK_DIR` and `TJOR_TASK_PARENT` (the directory's parent, for D6); it creates nothing, so lifecycle commands keep their no-side-effects contract. In `cmd_run`, in this order and always, covered or not: (1) `gate_sensitive_path --dir` on the intended path; (2) under `session_lock_acquire`, `create` walks from the prefix: open the prefix (`O_DIRECTORY`), then for each relative component `openat(parent_fd, name, O_DIRECTORY|O_NOFOLLOW)`; on `ENOENT` and `create = true`, `mkdirat(parent_fd, name)` then open the same way; `ELOOP`/`ENOTDIR` refuse naming the component; `fstat` of the final descriptor gives its identity; with `create = false` a missing directory refuses; (3) `contains` judges whether the workspace or a `--dir` root covers the now-existing directory; any error in that walk refuses the launch, never reads as "not covered"; (4) only an uncovered directory is appended to `TJOR_EXTRA_DIRS`; (5) the scan. Rationale: the covered case still needs the directory created, a link under it refused and its content scanned (review, task 3.2), and an identity walk on a leaf that does not exist yet cannot answer. Residual, stated in the README: the engine receives the bind source as a path, so a component swapped between the walk and the container start is outside what the launcher can see (the same window every mount has today). Alternative: `lstat`/`mkdir`/`realpath` by path; rejected as raceable by a swapped component (review item 9).

### D5. The notes-root refusal is by filesystem identity and has no override

`contains WORKSPACE PREFIX` walks the prefix's parent chain by `(st_dev, st_ino)` and reports whether any ancestor (or the prefix itself) is the workspace; a match refuses the launch naming both paths. `--unsafe-dir` does not cover it: that flag means "mount this sensitive path anyway", this refusal means "you are about to mount every task", and the remedy is to launch from the code repository. Alternative: string comparison of physical paths; rejected because macOS folds case and normalises Unicode in path names, so two spellings of one directory compare unequal and the refusal fails open (review item 8).

### D6. The mount is covered-aware and the share check is a correspondence check

Coverage is decided in D4 step 3 by identity: a directory the workspace or a `--dir` root already covers is mounted once (one grant, one git-trust tree) but still created, validated and scanned; a directory under a read-only root is refused by the existing writable-under-read-only rule. The share check cannot be the generic non-emptiness comparison (a freshly created directory is empty, and a VM-side parent holding an old task directory would pass it, review item 4): `run_agent` binds `TJOR_TASK_PARENT` read-only into a throwaway container and requires `test -d /check/<leaf>` inside it. The parent is never empty (it holds the leaf), and the test is the correspondence the mount needs. Alternative: a probe file written into the notes directory; rejected (writing into the operator's directory to test it).

### D7. `[task]` is user-config only and a security table; ADR 0013 records the rule

`tjor_cfg.effective()` drops the `task` table from the repository layer before merging and `check()` warns, naming the file, when a trusted repository config carries one; `task` joins `SECURITY_TABLES`, so an unknown key under it aborts. A misspelled table name (`[tasks]`) only warns, as for every table: it cannot claim to configure the real one. "User config" is the layer the operator's own environment selects (`TJOR_USER_CONFIG`, `XDG_CONFIG_HOME`); the rule is about repository content, not about the operator's environment. Rationale: no configuration key creates a writable host mount today, and a repository must not be able to choose one even after approval (review item 2); a feature that is silently off because of a typo is the failure class `SECURITY_TABLES` exists for. The existing "honored only after approval" requirement is modified to carve out the user-only tables, so the synced spec does not contradict itself, and ADR 0013 ("repository configuration never names a host path to mount") records the project-level decision, referenced from the repo-config-trust slide.

### D8. One session per task is the task id itself; an explicit `--session` still names the session

With `session_per_task = true`, `--task <id>` and no `--session`: `resolve_session` sets the short name to the id after the `--session` canonicalisation block (never through it) and derives `sid = <base>-<id>`, using the local `ws`-derived base. An explicit `--session <name>` names the session as today and `--task` stays the label and the directory: that is how two harnesses work one task at once (review item 2); without it, the same task id is the same session whatever the harness, so a second harness meets the running-session guard, which runs after profile and broker preparation as it does for any reused session today (stated in the README). The round trip through the lifecycle resolver is guaranteed by refusing at launch exactly what it would misread (review item 1): an id equal to the base id, an id prefixed by `<base>-`, or an id that names an existing session's full id (state directory or labelled container, the same lookup the resolver makes); every other id the resolver reads back as this workspace's short name, with its "looked qualified" notice where the shape warrants it. The launch prints the id as the session name. Rationale: injective by construction, no harness prefix to guess, no truncation (review items 1 and 4). Alternative: `<session>.<id>` composites; rejected as not injective and as costing the lifecycle commands a harness they do not know.

### D9. The scan is bounded, link-free, descriptor-relative and honest about partial results

`scan DIR`: walk at most 8 levels and 5000 entries, skip `.git`, descend with `openat(parent_fd, name, O_DIRECTORY|O_NOFOLLOW)` and list with `os.scandir(fd)` so no link is followed at any level; open candidates relative to their parent with `O_NOFOLLOW|O_NONBLOCK` and keep only `S_ISREG` descriptors (a FIFO is skipped and reported); name a file whose basename, split on `.`, `_` and `-`, has a segment in {`token`, `tokens`, `credential`, `credentials`, `secret`, `secrets`, `password`, `netrc`, `npmrc`, `kubeconfig`}, ends in `.pem`, `.key`, `.p12` or `.pfx`, or starts with `id_` (so `tokenizer.md` is not a match); read regular files up to 256 KiB each and 16 MiB in total through `tjor_secrets.kinds_present`. Output records are tab-separated with the path rendered through `tjor_safeprint` and tabs and newlines escaped, so a hostile name cannot split or forge a record. The launcher prints a loud warning listing at most 10 findings and the total; when a bound was reached or an entry was skipped (unreadable, FIFO) the warning says the scan was partial and names the entry. It runs on the launch path after the gates and before the agent, within the bounds above. Alternative: refuse; rejected (the operator's own directory). Alternative: scan off the launch path; rejected for now, the bound keeps the cost small and the warning is most useful before the agent starts.

### D10. `tjor attach --task <id>` filters on the label

`cmd_attach` gains argument parsing: `--task <id>` (a missing value is a usage error), else the positional session as today; a positional together with `--task` is a usage error. The candidate rows, which carry the `tjor.task` label, are filtered on it instead of on the session id; single match, picker and none are unchanged. The label is global, so the same id in two repositories offers the picker.

### D11. The default configuration keeps the feature off

`config/tjor.toml` gains `[task]` with `notes_dir = ""`, `create = true`, `session_per_task = false`, commented. Empty `notes_dir` skips every new behaviour, which is how the "unchanged without configuration" scenarios are met.

### D12. Proof

- `python/tests/test_task.py`: template validation (confinement included); the grammar; `create` (per-component creation, a link at a component, a file at a component, prefix never created, `create = false`, `dir_fd` support asserted); `contains` (ancestor, self, sibling, an error on a vanished component reported as an error, a differently-spelled path to the same directory where the filesystem folds case, detected at test time); the scan (names, content, bounds reported, a FIFO and a link skipped and named, a hostile name kept to one record).
- `python/tests/test_cfg_and_corefile.py`: the repository layer's `[task]` is dropped with a warning; an unknown key under `[task]` in the user config aborts.
- `tests/integration/task_notes_test.sh` (docker-free, modelled on `workspace_gate_test.sh`): the mount list, the covered case (created, scanned, not appended), the refusals (notes root as workspace, bad ids, ids that would not round-trip, bad or traversing template, sensitive template with nothing created, link below the prefix), the launch order (a gate refusal leaves nothing created), `--session` with `--task` naming the session, the round trip through `down --session <id>` via the resolution seam, lifecycle resolution creating nothing, the correspondence share check with a docker shim that lists the parent with and without the leaf, the warning, and the unchanged path without `[task]`; registered in the boundary matrix as the launcher-side `task-notes` suite.
- Live: one case in `multirepo_test.sh` (mounted writable at its host path, `TJOR_TASK_DIR` set, the repository still the workspace, the session named by the task id) and one in `lifecycle_test.sh` (two task sessions up at once, `down --session a` leaves `b` running, Compose project names distinct).

## Risks / Trade-offs

- [The directory is writable and git-trusted as a tree, like any `--dir`; nested repositories, links and secrets written there reach the host notes repository] → stated as residuals in the README; the operator chose a per-task directory, not the notes root.
- [Every session launched with the same task id shares the directory] → stated; it is the feature.
- [The bind source is a path for the engine] → stated; the launcher's checks are by descriptor and identity, the window after them is the same every mount has.
- [`[a-z0-9][a-z0-9_-]{0,31}` refuses ids an operator already uses as labels, such as `JIRA-123`] → only once `notes_dir` is configured, with a message naming the grammar; the label-only grammar is unchanged.
- [The scan has false positives] → advisory only; findings are named so the operator can judge.
- [A notes directory inside the workspace repository] → covered, not mounted twice; still created, validated and scanned; nothing new is exposed.
- [Two harnesses on one task id share one session unless `--session` is given] → stated in the README with the `--session` remedy; the running-session guard still fires, late as it does today.
- [`os.supports_dir_fd` could lack `open`/`mkdir`/`stat` on an unusual Python build] → the helper checks at start and fails closed naming the missing call.
