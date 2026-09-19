# Proposal

## Why

The v0.18.2 bounded-resolution fix (#59) bounds each *call* but not the *pool*: the guard resolves through a single shared 8-worker `ThreadPoolExecutor`. A re-review (v0.18.2, High) found that 8 concurrent connections to one policy-allowed slow-DNS host — realistic via a wildcard allow-pattern like `*.amazonaws.com` — exhaust the pool in one shot, after which every subsequent resolution for *any* host times out and is denied for as long as the attack is sustained. The control fails **closed** (deny-all, not a bypass), and it is a self-DoS in tjor's adversarial-agent model, but it turns a bounded per-call stall into a session-wide denial of the guard. Two review follow-ups ride along: the #60 redaction relies on brittle string-prefix matching against free-text (all three reviewers), and the #57 `api_host` pin has no explicit comma check (Low).

## What Changes

- **Per-host in-flight coalescing** (primary) — at most one resolution per host is in flight; concurrent requests for the same host share the one worker. This defeats the named vector (N connections to one wildcard host now use one worker, not N).
- **Bounded distinct in-flight resolutions, fail-fast** — a cap on concurrent *distinct* resolutions; beyond it a new host fails closed **immediately** instead of queueing a per-call-timeout backlog, so the event loop stays responsive and excess load doesn't accumulate.
- **Brief negative-cache of resolve-timeouts** — a timed-out host is cached fail-closed for a short window so repeated hits don't keep consuming capacity; the window expires so the host is re-evaluated once DNS recovers. **This reverses #59's "timeouts are never cached" decision** (which is what let repeated hits re-consume workers); recovery is now delayed by the short negative window rather than immediate.
- **Env-configurable knobs** — `TJOR_RESOLVE_TIMEOUT` / `TJOR_RESOLVE_WORKERS` (and the cap), matching the guard's existing `TJOR_`-style configurability; **explicit pool shutdown** in `done()`.
- **Denial reasons become structured** (secondary, #60) — `_address_public` returns a `(ok, reason_class, detail)` shape; the operator log composes the full text and the agent-facing redaction keys off `reason_class`, eliminating the free-text string round-trip that could silently re-leak an IP on a reword. An e2e test covers the `server_connect` pin-kill redaction of a non-global reason.
- **`api_host` comma check** (minor, #57) — reject a comma in an `api_host` pin, parity with the context-name check (both feed comma-joined env lists).

## Capabilities

### Modified Capabilities

- `cage-network`: MODIFIED "Address resolution is time-bounded and fails closed" — strengthen it so the guard also stays *available under concurrent slow resolutions* (one slow host cannot exhaust resolution capacity for others), and reconcile the caching clause (resolve-timeouts are now briefly negative-cached rather than never cached).

## Impact

- **Code**: `proxy/addon.py` — coalescing map + a distinct-in-flight cap + negative-cache in `_validated_addresses`; env-parsed `_RESOLVE_*` constants; `_resolve_pool` shutdown in `done()`; `_address_public` → structured return, with `_validated_addresses`/`_agent_reason`/`_agent_rule` keying off `reason_class`. `bin/tjor` — `api_host` comma check.
- **Tests**: `python/tests/test_addon_guards.py` — pool-exhaustion-under-concurrent-load (many coalesced connections to one slow host leave capacity for other hosts; distinct-host cap fails fast); negative-cache-then-recover; structured-reason redaction incl. the pin-kill path. `tests/integration/kube_test.sh` — `api_host` comma rejected.
- **Docs**: addon docstring/`_RESOLVE_*` comments; `config`/README for the new env knobs if documented there; CHANGELOG (Security) referencing #59/#60/#57. The residual (many *distinct* slow hosts can still self-degrade the guard within the cap window, fail-closed) is documented.
- **Behavior change**: a resolve-timeout is briefly cached (was uncached); no security-boundary change (still fails closed). Closes the v0.18.2 High finding and the v0.18.3/v0.18.1 review items.
