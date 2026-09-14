## Context

See proposal.md — Why. Mechanics, all verified empirically on docker 29.5.2 / compose v5.5.1 (and the flag surface holds back to compose v2):

- `compose run -d` decides pseudo-TTY allocation from the *compose client's* fds, not from the service's `tty: true`. Inside `ctr="$(compose run -d ...)"` the client's stdout is a pipe → container created `Tty=false`.
- A container's `Tty` is fixed at creation. `docker attach` never adds one.
- `compose run -T=false` (shorthand of `--no-tty`/`--no-TTY`, both spellings across compose versions) explicitly forces allocation, overriding auto-detection — verified to produce `Tty=true, OpenStdin=true` under command substitution.
- Compose refuses the force when the client's **stdin** is not a terminal ("cannot attach stdin to a TTY-enabled container because stdin is not a terminal"), even with `-d`. So the force must be conditional on `[[ -t 0 ]]`.
- With `Tty=true` created detached, the PTY exists from process start: an in-cage probe sees `[ -t 0 ] && [ -t 1 ]` succeed *before* any client attaches, and input later typed through `docker attach` reaches the process (verified end to end, including a readiness-gated input feed).

Constraint from `session-launch`: one-shot non-interactive usage (`tjor run ... true` in tests/CI, no terminal) must keep working and propagating exit codes.

## Goals / Non-Goals

**Goals:**
- Interactive harness sees a live PTY from its first instruction; the attach flow becomes a pure client re-connection, not the thing that creates interactivity.
- Fail loudly on every degraded path (no PTY possible, PTY intended but absent).
- A real integration test through the actual create-detached-then-attach flow, driven under a genuine PTY.

**Non-Goals:**
- Replaying harness output printed before the attach client connects (see Risks).
- Changing the persistent-container/attach architecture, compose topology, or anything security-boundary-related.
- Making `docker attach` work from a non-terminal client (docker refuses; the warning covers it).

## Decisions

1. **Force PTY with `compose run -d -T=false`, gated on `[[ -t 0 ]]`** — rather than:
   - *Dropping `-d` (foreground `compose run`)*: loses the container id capture, complicates `--detach` and exit-code handling, and still auto-detects from client fds; larger blast radius for the same result.
   - *`docker create`/`docker run -dit` directly*: would duplicate the whole agent service definition (mounts, env, networks, labels, limits, caps) outside compose.yaml — guaranteed drift.
   - *Redirecting compose's stdout to the terminal and discovering the container by name*: leaves TTY allocation dependent on ambient fd state — exactly the fragility that caused the bug.
   The `-T` shorthand is stable across compose v2 (`--no-TTY`) and v5 (`--no-tty`); `-T=false` parses on both. An unknown-flag failure makes `compose run` exit nonzero and `run_agent` already dies loudly.

2. **Post-create verification**: when the force was applied, `docker inspect -f '{{.Config.Tty}}'` must be `true`, else `die` (plain `die`, not `die_boundary` — availability, not a security boundary). Guards against future compose auto-detection changes silently reintroducing the hang.

3. **Loud warning on non-terminal stdin** (both attach and `--detach` modes): the session gets no PTY; interactive harnesses will not work in it; one-shot commands unaffected. This keeps `lifecycle_test.sh`'s non-interactive `tjor run ... true` usage working unchanged.

4. **Integration test drives a real PTY via `script(1)`** — `tests/integration/tty_test.sh`:
   - A `run_pty` helper papers over the BSD (`script -q /dev/null <cmd...>`) vs util-linux (`script -qec "<cmd>" /dev/null`) syntax split; test commands go into a temp script file so quoting stays trivial.
   - Probe A (startup TTY): `tjor run --session tty -- sh -c '[ -t 0 ] && [ -t 1 ]'` under the PTY → exit 0, plus assert the agent container's `Config.Tty=true`. This is the direct regression test for #51: it fails on the pre-fix code.
   - Probe B (interactive input): probe prints `READY`, then `read`s a line and exits 0 only if it matches; the feeder waits for `READY` in `docker logs` before writing the line into the PTY (early input gets eaten by compose's own startup — verified — so readiness-gating is load-bearing, not paranoia).
   - Probe C (non-terminal path): `tjor run` without a PTY still runs a one-shot command, propagates its exit code, and prints the new warning.

## Risks / Trade-offs

- [Output printed by the harness before the attach client connects is not replayed] → The gap is sub-second (inspect + echo between create and attach); full-screen TUIs repaint on the SIGWINCH that `docker attach` triggers when it sets the client's window size. Residual: a plain line printed pre-attach is only visible via `docker logs`. Accepted; documented here.
- [`script(1)` behavior differs across macOS/Linux] → helper with both syntaxes; CI runs the Linux variant, developers on macOS get the BSD one.
- [PTY input buffering: bytes fed before the attach client connects are consumed by compose startup] → readiness-gated feeding in the test; irrelevant for humans (they type after the screen appears).
- [A future compose version changes `-T` semantics] → post-create verification (decision 2) turns that into a loud abort, never a silent hang.

## Migration Plan

Pure launcher change, no state or image migration. Roll back by reverting the commit. Existing running sessions are unaffected (their containers keep their creation-time Tty).

## Open Questions

None.
