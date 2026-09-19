# Proposal

## Why

The SSRF/resolve-and-pin guard resolves hostnames with a **synchronous** `socket.getaddrinfo` (via the injectable `_resolver`, inside the shared `_validated_addresses()`), called on a cache miss from both the request/CONNECT verdict path and the `#41` `server_connect` pin — all on mitmproxy's single event loop. tjor's threat model treats the in-cage agent as adversarial, so the agent can steer egress at a hostname whose DNS hangs and stall its own session's event loop for the full resolver timeout, wedging every concurrent flow in that session (#59). This is a self-DoS — confined to the already-adversarial session, not cross-tenant and not a boundary bypass — but the guard should not be a lever the agent can pull to freeze the loop.

## What Changes

- **Resolution becomes time-bounded.** `_validated_addresses()` runs the resolver with a bounded timeout so no single call can block the event loop longer than that bound, regardless of how slow or hung the upstream DNS answer is.
- **Fail-closed on timeout.** A resolution that exceeds the bound is treated as a guard denial (not "public"): the verdict path denies (403) and the `server_connect` pin kills the connection — distinct from a *fast* `NXDOMAIN`/`OSError`, which keeps the existing "unresolvable host passes (nothing can connect)" behavior unchanged.
- **Timeouts are not cached.** A transient hang denies only that attempt; the next request re-resolves, so a brief DNS blip does not deny a host for the whole cache TTL.
- **The sync `_resolver` test seam is preserved.** The bound is applied by running the existing sync resolver in a small worker pool with a result timeout, so the injectable-resolver seam and all existing sync guard tests are unchanged; a new test drives a *hanging* resolver and asserts the call returns fail-closed within the bound instead of blocking.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cage-network`: ADDED requirement — the resolved-address guard bounds resolution time and fails closed on a resolution that exceeds the bound, so a slow/hanging DNS answer cannot stall the proxy event loop.

## Impact

- **Code**: `proxy/addon.py` — a bounded-resolve helper (a small, capped `ThreadPoolExecutor` + `future.result(timeout=…)`) wrapping the `_resolver` call in `_validated_addresses()`; a `_RESOLVE_TIMEOUT` constant; timeout → fail-closed, uncached. No change to `_address_public`, the deny-nets, the pin, or the cache shape.
- **Tests**: `python/tests/test_addon_guards.py` — a hanging-resolver regression (returns fail-closed within the bound, never blocks), timeout-not-cached, and fast-`OSError`-still-passes; existing sync tests unchanged.
- **Docs**: the addon docstring/`_RESOLVE_TIMEOUT` comment; CHANGELOG (Security) referencing #59.
- **Behavior change**: a hostname whose DNS hangs is denied after the bound (with the reason logged) instead of stalling the loop; a normally-resolving or fast-failing host is unaffected. Closes #59.
