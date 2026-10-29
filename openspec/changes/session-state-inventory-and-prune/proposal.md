# Proposal

## Why

`tjor gc` never deletes session state directories — correct, and required by the session-lifecycle spec — but nothing else removes them or even lists them (#68). One directory accumulates under `session.root` per workspace × session name, throwaway test sessions included, and each can hold live secrets: the session proxy CA (`proxy-ca/`, `ca.pem`), broker material (`broker/`), harness auth (`home/.local/share/opencode/auth.json`) and agent-minted `gh` tokens (`home/.config/gh/hosts.yml`, ADR 0007). `tjor reset` cleans one session at a time and only by a name the operator already knows, so on a developer machine the real inventory is `ls ~/.tjor/sessions` and guesswork (this machine has five such directories from six weeks ago, found only by accident). A boundary that keeps credentials out of the cage should not leave them lying in forgotten directories on the host.

## What Changes

- **Launch records session metadata.** Every `tjor run` writes `meta.json` into the session's state directory (workspace, harness, profile name or directory, task id, first-launch and last-launch timestamps, launch count), atomically, with no secrets. Directories from older versions have no file and are shown as `unknown` where it would have supplied a value.
- **`tjor ls --state` inventories the state root.** One row per state directory under `session.root`: session id, workspace (from `meta.json`), last activity (newest `lstat` time in a shallow walk that never follows symlinks), whether any container of that session is running, and which known credential paths exist. Entries that are not real directories are reported, never descended.
- **`tjor prune` deletes state explicitly, and only state no running session uses.** Selectors are mandatory (`--older-than <duration>` and/or repeatable `--session <id>`); `--dry-run` lists exactly what a real run would remove; `--creds-only` deletes just the credential tier instead of the whole directory. A session with any running container (agent or sidecar) is refused — `tjor down` first. A session whose git-check marker is still pending is refused unless `--force`, because deleting the directory discards unreviewed findings. Every deletion passes the existing symlinked-ancestor guard (charter L26). Prune never runs implicitly; `gc` is unchanged and still never touches state.
- **One definition of the state tiers.** The `cache`, `sessions` and `creds` path lists that `tjor reset` owns today move into a small Python helper that `reset`, `ls --state` and `prune` all consult, so a credential path added for one command cannot be missed by the others.

Not breaking: two new commands, one new flag, one additive file.

## Capabilities

### New Capabilities
<!-- none: inventory and prune are lifecycle behaviours of existing sessions -->

### Modified Capabilities
- `session-launch`: a new requirement — a launch records the session's metadata (`meta.json`) in its state root, atomically and without secrets; older directories read as unknown.
- `session-lifecycle`: a new requirement — the state root is inventoried (`tjor ls --state`) and pruned only explicitly (`tjor prune`), with the refusals above; the garbage-collection requirement's "never deletes state" invariant is unchanged and prune is the single path that does.

## Impact

- `bin/tjor`: `cmd_run` writes `meta.json` after the state directory exists and before the agent starts; `cmd_ls` gains `--state`; a new `cmd_prune` (dispatch + `usage`); `cmd_reset` reads its tier paths from the helper instead of its own `case`.
- `python/tjor_state.py` (new): tier path lists, duration parsing, inventory (metadata, credential flags, last activity by `lstat`), JSON out; unit-tested under `python/tests/`.
- Tests: `tests/integration/lifecycle_test.sh` gains a live section (inventory of a legacy and a current directory, running-session refusal, pending-marker refusal, symlink-ancestor refusal, dry-run, real prune, `--creds-only`); `python/tests/test_state.py` for the helper; the existing reset tier checks guard the refactor.
- Docs: README "Managing sessions", `CHANGELOG.md` under `[Unreleased]`, the lifecycle slide (re-read and re-pinned for both specs), the two spec deltas synced at archive.
- Not affected: the cage, the proxy, the images, `gc`, `down`, the boundary matrix (the lifecycle suite is not a probe suite).
