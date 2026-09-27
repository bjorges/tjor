# Proposal

## Why

`dir_is_sensitive()` refuses `/`, system directories, `$HOME` and its ancestors, and credential directories for every `--dir` and `--dir-ro` path — but the **primary workspace is never checked**. The workspace is `git rev-parse --show-toplevel` (falling back to `pwd -P`), so on a machine whose dotfiles live in a git repository rooted at `$HOME`, running `tjor run` from `$HOME` or from any non-repository directory under it silently resolves the workspace to `$HOME` and mounts the entire home directory — `~/.ssh`, `~/.config` (tjor's own config included), `~/.tjor/sessions` with every other session's CA and broker material — **writable and git-trusted as a tree** (#53). No warning fires: the "not inside a git repository" notice only appears when discovery finds *no* repository. This inverts the gate: the one path tjor refuses as an extra mount is accepted as the workspace (#64).

A second, independent hole: `~/.tjor` (the default `session.root`) is not in the credential-directory list, so a workspace — or a `--dir` — that is, contains, or sits under the session root passes today even though each session state directory holds proxy CA keys, broker material, harness auth, and possibly agent-minted tokens (#68 inventories these).

## What Changes

- **BREAKING (by design): the sensitive-path gate covers the primary workspace.** At launch, before any state directory is created or any credential is minted, the canonical workspace is checked with the same `dir_is_sensitive` rule as `--dir`. A sensitive workspace aborts the launch. `--unsafe-dir` remains the single, explicit override, and it now prints a loud warning whenever it actually overrides a refusal (today it is silent).
- **The refusal explains how the workspace was resolved.** When git discovery climbed above the launch directory to reach a sensitive toplevel, the error says so: `<cwd> is not a repository; git resolved the workspace to <toplevel> via <toplevel>/.git — launch from a repository (or pass --unsafe-dir)`. A sensitive `pwd -P` fallback (no repository) gets the plain refusal.
- **The session root and the tjor user-config directory become sensitive paths.** `dir_is_sensitive` grows two roots: the effective `session.root` and the effective user-config directory (`$XDG_CONFIG_HOME/tjor` or `~/.config/tjor`). A path that equals, contains (is an ancestor of), or is under either is refused — for the workspace and for `--dir`/`--dir-ro` alike, since the same function serves all three. This matters even when `$HOME` is not the workspace (a custom `session.root` outside `$HOME`, or a custom `XDG_CONFIG_HOME`).
- **Lifecycle commands are unaffected.** `status`, `down`, `reset`, `denials` resolve the same workspace without the gate, so a session launched under `--unsafe-dir` can still be torn down and inspected from its workspace.
- **Non-launcher starts (entrypoint): decided, not silently skipped.** The entrypoint cannot evaluate host-side sensitivity (it does not know the host `$HOME`, session root, or config dir). It re-refuses only what it can judge without host context: an approved mount root of `/` or a system directory — `/` already covered by the malformed-root refusal; the system-dir list is added, and the launcher's `--unsafe-dir` reaches the cage so the single override holds end to end. The host-home / credential-dir / session-root half of the gate is a launcher guarantee, and the spec says so explicitly rather than claiming an entrypoint re-check it cannot make.
- **Coverage becomes visible.** A host-side integration test (no daemon needed — the refusal fires before any Docker call) proves each refusal, the override, and the unchanged normal path; a boundary-matrix row records the guarantee; `session-launch` is amended.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `session-launch`: a new requirement — *Sensitive host paths are refused as the primary workspace* — covering the workspace gate, the resolution-explaining error, the `--unsafe-dir` override and its warning, the session-root / config-dir extension of the sensitive set (applied to the workspace and to the extra-dir gates), the lifecycle-command exemption, and the honest scope of the entrypoint re-check. The existing `--dir-ro` scenario "Sensitive path refused read-only too" is unchanged in behavior but the sensitive set it references grows, which the new requirement states.

## Impact

- **Code**: `bin/tjor` — `dir_is_sensitive` (session root + config dir roots; ancestor/descendant containment), `resolve_session` (gate on the `launch` path before `mkdir -p` of the state dir, with the git-climb explanation), `cmd_run` (pass the `--unsafe-dir` intent into resolution; loud warning on an actual override), help text. `images/agent/entrypoint.sh` — system-directory refusal for the workspace root (host-context checks stay launcher-side, stated in a comment). `python/gen_boundary_matrix.py` — one REGISTRY entry (new `workspace-gate` suite source, see design). `docs/boundary-matrix.md` regenerated.
- **Tests**: new `tests/integration/workspace_gate_test.sh` (sourced launcher functions, mocked `git`/`docker` not required — the refusal precedes both; runs in the daemon-free `unit` CI job): `$HOME`-rooted dotfiles repo launch from `$HOME` and from a non-repo subdirectory both refused with the resolution message; `--unsafe-dir` launches with a warning; workspace equal to / containing / under the session root refused; workspace equal to / under the config dir refused; custom `session.root` and custom `XDG_CONFIG_HOME` honored; a normal repository launches unchanged; `--dir` of the session root refused; lifecycle command on a sensitive workspace not refused.
- **Docs**: README (the `--unsafe-dir` sentence gains "and the workspace"), CHANGELOG `[Unreleased]` (Security, **BREAKING**), `docs/boundary-matrix.md` (generated).
- **Behavior change**: launches whose workspace resolves to `$HOME`, an ancestor of it, a credential directory, the session root, or the tjor config directory are refused unless `--unsafe-dir` is given. Repository workspaces are unaffected. Existing sessions launched under such a workspace remain manageable via `down`/`reset`.
- **Out of scope** (stated in #64): credential *files* inside an otherwise non-sensitive workspace — path rules cannot see those.
