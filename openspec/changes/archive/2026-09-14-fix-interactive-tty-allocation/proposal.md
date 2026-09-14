## Why

`tjor run` is currently unusable for every interactive harness (#51): Claude Code fails at startup with a `--print`/stdin error, and opencode hangs silently after the startup banner. The root cause (confirmed empirically) is that `docker compose run -d` auto-detects pseudo-TTY allocation from the *compose client's own stdout* — and `run_agent()` invokes it inside command substitution (`ctr="$(compose run -d ...)"`), which makes that stdout a pipe. The agent container is therefore created with `Tty=false` even from a real terminal, despite `tty: true` in `compose.yaml`. The harness (PID 1 via the entrypoint's `exec`) sees a non-TTY pipe on stdin from its first instruction; a TTY can never be added after creation, so the later `docker attach` cannot repair it. This blocks any real interactive use of tjor — the "working setup" path.

## What Changes

- The launcher forces PTY allocation at agent-container creation (`compose run -d -T=false`) whenever the launching terminal can support it (stdin is a terminal), independent of stdout redirection/capture.
- After creation, the launcher verifies the container actually got a PTY when one was intended, and fails loudly (boundary-style abort is not warranted — this is availability, not security — but the session must never proceed into a silent hang).
- When the launcher has no terminal on stdin, the session is created without a PTY as today, but the launcher warns loudly that interactive harnesses will not work in that session (one-shot commands keep working and keep propagating exit codes).
- A new integration test drives the REAL create-detached-then-attach flow under a genuine PTY (via `script(1)`), asserting (a) the in-cage process observes a TTY on stdin/stdout at its own startup, before any client attaches, and (b) interactive input typed through the attach reaches the in-cage process. This closes the exact gap that let #51 evade `lifecycle_test.sh` (which sets `TJOR_ATTACH_DRY=1`).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `session-launch`: the "Agents launch detached and persist independently of the launching client" contract gains a PTY-allocation requirement — an interactive launch SHALL give the harness a live PTY from process start (created with the container, not deferred to attach), verified after creation; a launch without a terminal SHALL warn loudly that the session is non-interactive.

## Impact

- `bin/tjor` — `run_agent()`: TTY force flag, post-create verification, no-terminal warning.
- `tests/integration/tty_test.sh` (new) — real-PTY integration test using `script(1)` (macOS/BSD and util-linux variants).
- `.github/workflows/ci.yml` — run the new test.
- No compose topology, proxy, policy, or image changes. No security-boundary changes: PTY allocation affects only the agent's own stdio.
- Compose compatibility: `-T` (`--no-tty`/`--no-TTY`) shorthand exists across compose v2–v5; `-T=false` parses on both spellings. If a future compose rejects it, `compose run` fails and `run_agent` already dies loudly ("failed to start the agent container") — fail-closed, never a silent hang.
