# ADR 0006 — Persistent (detached) session containers

**Date:** 2026-09-05 · **Status:** accepted

D3 (session lifecycle) changed how agent containers are launched: from
auto-removed foreground (`compose run --rm`) to **detached and persistent**
(`compose run -d`, no `--rm`), attached to afterward. Recorded here as a
deliberate posture change (surfaced by external review, which correctly
noted the original D3 change shipped without threat-modeling it).

**Why.** `--rm` deletes the container the moment the launching client exits —
so a dropped terminal destroys the session, and there is nothing for
`tjor attach` to reconnect to. Reattachment, the core D3 affordance, is
impossible under `--rm`.

**The trade-off.** A persistent container lingers after its client goes away,
until `tjor down` or `tjor gc` removes it — a *longer compromise window* than
an auto-removed container.

**Why it is accepted.** The security guarantee is structural and time-invariant:
the internal-only network, fail-closed egress proxy, non-root user, and
absent host credentials constrain what the agent can reach for the
container's entire lifetime, whether that is one minute or one day.
Persistence changes *how long an idle container exists*, not *what a
compromised agent inside it can do*. Compensating controls: `tjor gc`
reaps idle containers on an age bound (default 24h), and `tjor ls`
re-verifies each running session's internal-only boundary on demand.

**Alternatives considered.** Keep `--rm` and drop reattach — rejected;
reattach is the point of D3. A background supervisor that auto-reaps on
client disconnect — rejected as more moving parts than the lifecycle model
warrants, and it would fight the intentional survive-a-dropped-terminal
behavior.

Supersedes the `--rm` assumption in the cage-core design; the promoted
`session-launch` spec carries the reconciled requirements.
