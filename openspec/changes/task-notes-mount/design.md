# Design

## Context

See proposal.md for the motivation. What shapes the approach:

- Every writable extra root already passes one pipeline in `cmd_run`: physical-path resolution, `gate_sensitive_path --dir`, dedupe against the workspace, the worktree common-dir rule, the mixed-writability refusal, the self-mount guard; later `run_agent` verifies the bind source (VM share), mounts it at its host path, registers git trust as a tree, runs mask discovery and the git-check baseline over it, and hands it to the kernel sandbox allowlist. A root appended to `TJOR_EXTRA_DIRS` after the `--dir` loop gets all of that for free (observed: `bin/tjor` `cmd_run`, `run_agent`).
- `resolve_session` derives the session id as `<repo>-<hash8>[-<short>]` and canonicalises a user-supplied `--session` value against qualified-looking ids; the short-name grammar is `[A-Za-z0-9._-]{1,32}`; the task id grammar is `[A-Za-z0-9._-]{1,64}` and the id is a label only (observed).
- `workspace_toplevel` is the one guarded resolver (nearest-repository cross-check, #76); `TJOR_LAUNCH_DIR` becomes the harness cwd through compose `working_dir` (observed).
- `tjor_cfg.check` warns on keys absent from `config/tjor.toml`, so new keys need defaults there (observed).
- The secret-shape detector (`tjor_secrets.kinds_present`) and the terminal-escape sanitizer exist and are the ones to reuse (observed).
- Identity headers are a fixed table in `tjor_identity.py`; unknown `x-agent-*` headers are stripped toward every host (observed).

## Goals / Non-Goals

**Goals:**
- One opt-in configuration turns `--task <id>` into a mounted, writable notes directory with per-task session identity, without widening what the cage can reach beyond that one directory.
- Every path-safety rule the launcher already has applies to the notes directory by construction, not by a second copy.
- The notes repository above the directory can never become the workspace by accident.

**Non-Goals:**
- Anything the harness does with the directory (a prompt that points at it, resume behaviour): #73.
- Sharing or syncing notes between hosts, or per-task secrets.
- A task directory for lifecycle commands' own output; `TJOR_TASK_DIR` is for the agent.

## Decisions

### D1. Resolution, creation and the scan live in one Python helper

`python/tjor_task.py` with three subcommands the launcher calls: `resolve --template T --task ID [--create]` (prints the directory's physical path, or a reason on stderr and exit 1), `short-name BASE ID` (prints the composite short name), `scan DIR` (prints one line per credential-shaped finding, exit 0 always). Rationale: the component-wise walk (`lstat` per level, `mkdir` without `-p`, the prefix containment check on physical paths) and the bounded scan are easier to get right and to unit-test in Python than in bash, and the launcher already shells out to helpers this way (`tjor_state.py`, `tjor_policy_edit.py`). Alternative considered: pure bash in `cmd_run`; rejected because `pwd -P` plus `readlink` per component is the kind of code that is wrong in one edge case for a year.

### D2. The template and its fixed prefix

`task.notes_dir` must be absolute after expanding a leading `~` and must hold `{task}` exactly once (no other brace). The fixed prefix is the path up to, not including, the first component that holds `{task}`. The prefix must exist and be a directory; tjor never creates it (creating the operator's notes root silently is how a typo becomes a new tree). Below the prefix, every existing component must be a real directory (`lstat`, not a symlink); with `create = true` a missing component is made with `mkdir` (mode from the umask) and re-checked; with `create = false` a missing one refuses. After the walk, the directory's physical path must equal `<physical prefix>/<relative part>`; anything else is the symlink-escape refusal. Rationale: comparing physical paths after a per-component symlink check closes both the "link inside the prefix pointing out" and the "prefix itself is a link" cases, and the per-component check gives a precise error (which link, where it points). Alternative: `realpath` containment only; rejected because a link *inside* the prefix that points to another directory *inside* the prefix would pass while the operator's layout says otherwise, and because the error could not name the link.

### D3. The task id grammar tightens only when it resolves to a path

With `notes_dir` configured, the id must match `^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$` (no leading dot, which covers `.`, `..` and hidden names). Without it, today's grammar stays. Rationale: the acceptance criterion "behaviour with no `[task]` config is unchanged" is literal, and an id is only dangerous once it becomes a path component. Alternative: tighten unconditionally; cleaner, rejected for the compatibility promise. The proposal states the one visible change for configured setups.

### D4. The notes directory is an extra writable root, appended last

In `cmd_run`, after the `--dir` loop and before the read-only loop, the resolved directory is appended to `TJOR_EXTRA_DIRS` with the same dedupe (equal to the workspace: skip, it is the workspace already; equal to a `--dir`: skip) and `gate_sensitive_path --dir`. The read-only loop's conflict check then refuses the same path given as `--dir-ro`. Everything downstream is untouched. `TJOR_TASK_DIR` is exported either way (the directory is mounted at its host path whichever list it came through). Rationale: zero new mount code; every guard the spec enumerates for extra dirs is inherited by construction and the task list can say so instead of re-testing each. Alternative: a dedicated mount with its own checks; rejected (three copies of the sensitive gate were just collapsed into one in v0.19.0).

### D5. The notes-root refusal has no override

Refused when `TJOR_WORKSPACE == prefix` or `prefix == ${TJOR_WORKSPACE}/*` (component boundaries, physical paths), after workspace resolution and before any state is written. `--unsafe-dir` does not cover it: that flag means "mount this sensitive path anyway", while this refusal means "you are about to mount every task", and the remedy is a flag that does the right thing (`--workspace`, `--notes-workspace`), not a flag that does the wrong thing loudly. Alternative: warn and continue; rejected, the exposure is the whole point of the issue.

### D6. `--workspace <dir>` is "launch as if from there"

`cmd_run` resolves `<dir>` to a physical directory (must exist), `cd`s into it before `resolve_session`, and sets `TJOR_LAUNCH_DIR` to it. Nothing else changes: the nearest-repository cross-check, the sensitive gate, path fidelity and the metadata record all see a launch from that directory. Rationale: one semantics to explain and test; the flag exists so a launcher script in a task directory can target the code repository without a `cd`. Alternative: a separate resolution path taking a repository root; rejected, it would be a second resolver next to the one #76 just unified.

### D7. `--notes-workspace` sets the workspace directly

With the flag, `resolve_session` takes the resolved notes directory as the workspace without calling `workspace_toplevel`: the directory is not a repository root in the common case (it sits inside the notes repository) and discovery would climb exactly where we refuse to go. `GIT_CEILING_DIRECTORIES` is exported as the directory itself for the rest of the launch so any git call the launcher makes in it stops there; inside the cage the notes repository is not mounted, so discovery stops at the mount boundary on its own. The session id derives from the directory's path like any workspace; `TJOR_TASK_DIR` equals the workspace. The sensitive gate and the scan run on it. Requires `--task` and `notes_dir`; mutually exclusive with `--workspace`. Rationale: the issue's repo-less case with the smallest mechanism. Alternative: keep repo-less tasks host-side (not ship the flag); recorded as an open decision for the review, the code is a dozen lines either way.

### D8. One session per task is a derived short name, not a parsed one

With `session_per_task = true` and `--task <id>`: `short = lower("<name-or-harness>.<id>")`; if `len > 32`, `short = short[:23] + "." + sha256(short)[:8]` (32 characters, deterministic, the suffix keeps distinct long ids distinct). `resolve_session` applies it after the `--session` canonicalisation block and sets `sid = "<base>-<short>"` directly: the composite never enters the qualified-looking-id disambiguation (a composite such as `opencode.a-12345678` would match that pattern and be looked up as a foreign id). The launch prints `tjor: session <short> for task <id>`; `tjor ls` shows it like any short name. Rationale: the issue's design, and the only way to make "same task twice" meet the existing running-session guard without new state. The derived name also feeds `down/status/denials/reset --task <id>` (same derivation in `resolve_session`, which every lifecycle command already calls) so the operator need not remember it. `--task` with `--session` on a lifecycle command is a usage error (two answers to one question). Alternative: require an explicit `--session` per task; rejected, it is what the issue calls out as the friction.

### D9. `tjor attach --task <id>` filters on the label

`cmd_attach` gains `--task <id>`: the candidate rows (which already carry the `tjor.task` label) are filtered on it instead of on the session id; the rest (single match, picker, none) is unchanged. No workspace qualification is needed, the label is global, so the flag works from anywhere.

### D10. The scan is bounded and advisory

`scan DIR`: walk at most 8 levels and 5000 entries, skip `.git` and symlinks, name a file when its basename (lower-cased) contains `token`, ends in `.pem` or `.key`, or starts with `id_`; read regular files up to 256 KiB each and 16 MiB in total through `tjor_secrets.kinds_present` and name a file per kind found. The launcher prints a loud warning listing at most 10 findings (sanitised) and a count. Rationale: the issue asks for a warning, the detector exists, and a bound keeps a large notes tree from stalling a launch. Alternative: refuse; rejected (the operator's own directory; a false positive would block work).

### D11. The default configuration keeps the feature off

`config/tjor.toml` gains `[task]` with `notes_dir = ""`, `create = true`, `session_per_task = false`, commented. Empty `notes_dir` means every new behaviour is skipped, which is how the "unchanged without configuration" scenarios are met and tested.

### D12. Proof

A docker-free launcher test (`tests/integration/task_notes_test.sh`, modelled on `workspace_gate_test.sh`: source `bin/tjor`, a docker shim that fails loudly, a throwaway layout under `~/.tjor/tmp`) drives `cmd_run` to the point before docker and asserts the mount list, the refusals, the names and the unchanged path; it registers in the boundary matrix as the launcher-side `task-notes` suite. `python/tests/test_task.py` covers the resolver (template validation, prefix, per-component creation, every refusal, the symlink cases), the short-name derivation (cases from the spec, the 32-character boundary, determinism) and the scan (names, content, bounds, a symlink skipped). One live case in `multirepo_test.sh` shows the directory writable at its host path inside the cage with `TJOR_TASK_DIR` set and the session id carrying the task.

## Risks / Trade-offs

- [The notes directory is writable and git-trusted as a tree, like any `--dir`] → stated in the README; the operator chose a per-task directory, not the notes root, and the root is refused as a workspace.
- [A notes directory inside the workspace repository] → allowed (same writability class, no new exposure); the dedupe skips it when it equals the workspace.
- [The composite short name collides with a hand-picked `--session` name such as `opencode.a`] → same session, by construction; documented as the naming scheme.
- [A long task id's truncated name hides the id] → `tjor ls` keeps showing the `tjor.task` label; `attach --task` and the lifecycle `--task` resolve it without the name.
- [`--notes-workspace` makes a directory with no repository the workspace] → identical to today's non-repository launch (warned), with git discovery stopped at the directory.
- [The scan has false positives] → advisory only; findings are named so the operator can judge.

## Open Questions

- Whether `--notes-workspace` ships now or stays out until a user asks (D7 keeps it small; the issue itself lists this as open). The specs include it; striking it removes one requirement, one flag and one test group without touching the rest.
