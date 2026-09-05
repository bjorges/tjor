# Proposal: add-session-lifecycle

## Why

tjor currently manages exactly one implicit session per repo, offers no way to see what's running, no way to reattach to a live session, and no cleanup story — exited topologies, stale networks, and session state accumulate until someone hand-runs docker commands. D3 (issue #3) turns sessions into first-class, discoverable, multiplexable, garbage-collected things — the last piece of daily-driver ergonomics before the credential broker (D2).

## What Changes

- **Discovery**: agent containers get session labels; new `tjor ls` lists every tjor session on the machine (running/exited, workspace, task, age) and re-verifies each running session's core guarantee (internal-only network), flagging degraded sessions loudly — the launch-time-only TOCTOU gap from the cage-core threat model gets a recurring checkpoint.
- **Reattach**: new `tjor attach [session]` reattaches to a running agent container's terminal; with several candidates, an interactive picker (fzf when present, plain menu otherwise).
- **Concurrent sessions per repo**: `tjor run --session <name>` derives a distinct session id (own topology, own state root, own identity) so parallel work in one repo no longer collides; the unnamed default stays repo-scoped.
- **Garbage collection**: new `tjor gc [--age <dur>] [--dry-run]` reaps exited agent containers and tears down topologies with no live agent, plus orphaned tjor networks/volumes. Session *state dirs* (auth!) are never touched by `gc`.
- **Tiered reset** (charter L17): new `tjor reset {cache|sessions|creds|all} [--dry-run]` for the current repo's session state, so routine wipes stop being ad-hoc `rm -rf` with the wrong blast radius.

Out of scope: credential lifecycle (D2 revokes credentials at teardown — the gc hook point is left ready), remote/multi-host sessions.

## Capabilities

### New Capabilities

- `session-lifecycle`: discovery, reattachment, multiplexing, garbage collection, and tiered state reset.

### Modified Capabilities

- `session-launch`: the launcher additionally labels agent containers for discovery and accepts `--session <name>` for id derivation.

## Impact

- Code: launcher (new subcommands `ls`, `attach`, `gc`, `reset`; `--session` flag), compose (agent labels), an integration test script exercising the lifecycle end-to-end (runs in CI next to conformance).
- No breaking changes: existing default sessions keep their ids, state dirs, and behavior.
