# Design: add-session-lifecycle

## Context

Everything here is launcher-side bash plus compose labels — no new images, no new sidecars, no policy-engine changes. Constraints: charter L17 (tiered reset with dry-run), L26 (host-side scripts touching agent-writable paths must be symlink-safe at every touch point — GC is explicitly a "second touch point"), L29 (nothing shared across concurrent sessions), and the cage-core threat-model note that the core-guarantee check was launch-time-only.

## Goals / Non-Goals

**Goals:** discovery, reattach, per-repo multiplexing, cleanup — all without ever endangering session state (auth) implicitly.

**Non-Goals:** credential revocation at teardown (D2 wires into the gc hook later); cross-machine session registries; automatic background GC daemons (gc stays operator-invoked, per L29's "operator-invoked and short-lived" principle for lifecycle machinery).

## Decisions

- **Labels are the source of truth, names are cosmetic.** Discovery reads `tjor.session`, `tjor.workspace`, `tjor.harness`, `tjor.task`, `tjor.launched-at`, `tjor.role` labels (agent containers get them via compose from launcher env). Parsing container names is forbidden — that's the failure mode the reference-system review warned about.
- **`attach` = `docker attach`** to the agent container's existing PTY (same TUI, same process), not a new `exec` shell — reattaching means resuming the session you see in `tjor ls`, not opening a side door. Picker: `fzf` when installed, bash `select` menu otherwise; both operate on the same `ls` data.
- **Named sessions extend id derivation, not replace it**: `<repo>-<hash(workspace)>` stays; `--session a` yields `<repo>-<hash>-a`. Everything downstream (project name, state root, identity, CA dir) already keys off the session id, so isolation per L29 follows from derivation alone — the implementation is one flag plus validation.
- **GC deletes docker resources only, selected by label, never state dirs.** Deleting state (auth) is `reset`'s job, explicit and tiered. GC's deletion of docker volumes/networks/containers can't be redirected by agent-planted symlinks (docker API objects, not paths); the only filesystem GC touches is nothing — which is the safest possible answer to L26's "GC is a second touch point."
- **`reset` tiers map to concrete paths** under the session root: `cache` → `home/.cache`; `sessions` → harness state/history dirs (`home/.local/share`, `home/.local/state`); `creds` → `proxy-ca/`, `ca.pem`, harness auth files under `home/.config`/`home/.local/share` opencode auth; `all` → the session dir. Deletion uses `rm -rf` on the tier paths — rm does not follow symlinks when deleting, so agent-planted links cannot redirect the wipe outside the session root; paths are printed first under `--dry-run`.
- **Degradation re-check in `ls`**: for each session with running containers, `docker network inspect -f '{{.Internal}}'` on its internal network — the same check the launcher makes at start, now repeatable on demand. This is a checkpoint, not a watchdog; continuous enforcement remains out of scope (docker-socket users are trusted, per the cage-core threat model).

## Risks / Trade-offs

- `docker attach` detach requires the docker detach sequence (ctrl-p ctrl-q) to leave without killing the harness; `tjor attach` prints that hint on entry. Exiting the harness normally still ends the container (compose run --rm semantics).
- Concurrent named sessions multiply sidecars (one proxy+dns pair per session) — accepted: sharing sidecars across sessions is exactly the identity-collision trap L29 forbids.
- GC's age heuristic uses container `FinishedAt`; a topology whose sidecars run but whose agents exited long ago counts as idle — sidecars are restartable state-free infrastructure, safe to reap and recreate.

## Verification approach

Launcher logic is bash orchestrating docker — unit tests would mock away everything real, so verification is a live integration script (`tests/integration/lifecycle_test.sh`): launches two named sessions in a scratch repo, asserts `ls` output and label contents, asserts isolation (distinct networks/state/identity), exercises attach non-interactively (`docker attach` with a piped detach), runs `gc --dry-run` then `gc`, asserts state-dir survival and resumability, exercises every `reset` tier against planted files including a symlink-escape attempt. Runs in CI as a fourth job.
