# Design

## Context

See proposal.md — Why. Current state in `proxy/addon.py` (post-#59/#60):

- `_validated_addresses(host)` (event-loop thread) short-circuits exemptions/IP-literals, checks `_ip_cache` (10 s TTL), else `_resolve_pool.submit(_resolver, host).result(timeout=_RESOLVE_TIMEOUT)` — a single shared `ThreadPoolExecutor(max_workers=8)`. Timeout → `(False, "resolve-timeout", ∅)`, **not cached**; fast `OSError` → `(True, "unresolvable", ∅)`.
- Hooks are synchronous on mitmproxy's single event loop, so `_validated_addresses` is never re-entered concurrently — shared maps need no lock (worker threads only run `_resolver`; the done-callback cleanup is a GIL-atomic dict pop).
- `_address_public(raw) -> (bool, str)` returns free-text (`"non-global address 10.0.0.5"`); `_agent_reason` prefix-matches that text — the #60 fragility.
- `_RESOLVE_TIMEOUT`/`_RESOLVE_WORKERS` are hardcoded; the pool is never shut down.

## Goals / Non-Goals

**Goals:**
- One slow host cannot exhaust resolution capacity for other hosts; the named vector (N connections to one wildcard host) uses one worker.
- Excess load fails closed *fast*, not as a per-call-timeout backlog.
- Redaction keys off structure, not free-text.
- Stdlib-only; no new dependency (the addon's deliberate posture).

**Non-Goals:**
- A non-blocking DNS resolver / new dependency (considered and declined for this change — the stdlib mitigation substantially narrows the vector; the residual is documented).
- Killing hung worker threads (impossible for a blocked `getaddrinfo`); they free at the OS resolver's own timeout.
- Changing exemptions, the pin, `_ip_cache` shape, or address judgment logic.

## Decisions

1. **Per-host in-flight coalescing — the headline fix.**
   An `_inflight: dict[str, Future]` maps a host to its running resolution. `_validated_addresses` reuses an existing future rather than submitting a second; N concurrent connections to one host wait on one worker. This alone defeats the "8 connections to one wildcard host" vector the review called realistically triggerable. Cleanup: an `add_done_callback` pops the host from `_inflight` when the worker finishes (GIL-atomic; safe from the worker thread). On timeout the future is left in `_inflight` (still running/hung) so concurrent waiters keep coalescing onto it instead of spawning more.

2. **Bounded distinct in-flight, fail-fast (no queue).**
   A cap `_RESOLVE_MAX_INFLIGHT` (= workers) on `len(_inflight)`: a new distinct host beyond the cap returns `(False, "resolve-capacity", ∅)` **immediately** rather than submitting (which would queue behind hung workers and stall 5 s per call). This converts the durable per-call backlog into an immediate fail-closed, keeping the loop responsive; capacity returns as hung workers hit the OS resolver timeout.

3. **Brief negative-cache of resolve-timeouts — reverses #59's "never cache".**
   A timed-out host is cached `(False, "resolve-timeout", ∅)` for a short `_RESOLVE_NEGATIVE_TTL` (< the 10 s positive TTL), so a sustained single-host attack is served from cache without re-consuming a worker each attempt. #59 deliberately did NOT cache timeouts (for instant recovery); the review shows that is exactly what lets repeated hits re-exhaust the pool. The trade — recovery delayed by the short negative window instead of immediate — is the right call for a security control's availability. Positive results keep the 10 s TTL; the lookup distinguishes the two by `ok`/`why`.

4. **Env knobs + explicit shutdown (code-quality, @homer).**
   `_RESOLVE_TIMEOUT`/`_RESOLVE_WORKERS` (and the cap/negative-TTL) parse from `TJOR_`-prefixed env with the current values as defaults, matching the guard's `TJOR_IP_GUARD` style. `done()` calls `_resolve_pool.shutdown(wait=False, cancel_futures=True)` so queued (never-started) work is dropped on teardown.

5. **Structured denial reason — kills the #60 string round-trip.**
   `_address_public` returns `(ok, reason_class, detail)` where `reason_class` is a stable token (`"non-global-address"`, `"unparseable-address"`) and `detail` the specifics (the address). `_validated_addresses` composes the operator `why` as `reason_class + (": " + detail)`; the agent-facing redaction returns `reason_class` directly — no `startswith` against free-text, so a reword of `detail` cannot silently re-leak. `_agent_reason`/`_agent_rule` are simplified accordingly. The resolve-timeout / unresolvable / exemption reasons are already tokens and are unaffected.

6. **`api_host` comma check (minor, #57).**
   In `bin/tjor`, reject a comma in the derived `api` host that feeds the comma-joined `TJOR_KUBE_API_HOSTS`, parity with the context-name check — belt-and-suspenders over `same_server`'s implicit invariant.

## Risks / Trade-offs

- [Residual: many *distinct* genuinely-hung hosts still degrade the guard within the cap window] → Bounded by the cap and by the OS resolver's own timeout (workers free without a proxy restart), served fail-closed and fast beyond the cap; self-inflicted in the adversarial-agent model. Documented; the fuller fix (non-blocking resolver) is a separate, dependency-bearing change if ever warranted.
- [Negative-cache delays legitimate recovery from a transient stall by up to `_RESOLVE_NEGATIVE_TTL`] → Accepted; the window is short and the alternative (no negative cache) is the exploited behavior.
- [Structured-return refactor touches the hot judgment path] → Covered by the existing address-judgment tests plus the redaction tests; behavior is unchanged for every existing case.

## Migration Plan

No config/data/spec-format change; new env knobs are optional with today's values as defaults. Ships in the proxy image, rebuilt per release. Rollback is a plain revert. Patch release.
