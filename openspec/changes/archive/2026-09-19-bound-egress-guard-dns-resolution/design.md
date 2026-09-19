# Design

## Context

See proposal.md — Why. Current state in `proxy/addon.py`, verified:

- All addon hooks are **synchronous** (`def http_connect`, `def request`, `def server_connect`), and the guard chain is sync: `resolved_addresses_ok` / the pin → `_validated_addresses(host)` → `_resolver(host)` (default `_system_resolver` = `socket.getaddrinfo`; injectable for tests).
- `_validated_addresses` short-circuits exemptions and IP literals, checks the 10 s `_ip_cache`, else resolves and judges each address with `_address_public`. A fast `OSError` returns `(True, "unresolvable", ∅)` — the documented "nothing can connect, so permit" stance.
- The whole thing runs on mitmproxy's event loop, so a blocking `getaddrinfo` blocks every flow in the session until it returns.
- 60+ guard tests call the sync functions and inject `_resolver` as a plain function.

## Goals / Non-Goals

**Goals:**
- No single resolution can block the event loop beyond a fixed bound.
- Fail closed on exceeding the bound; preserve the fast-unresolvable-passes behavior.
- Keep the sync call signatures and the injectable-`_resolver` test seam intact.

**Non-Goals:**
- Rearchitecting the guard/hooks to async (see Decision 1).
- Changing address judgment (`_address_public`, deny-nets), the pin, exemptions, or the cache shape.
- A configurable timeout surface (a fixed constant is enough; revisit only if a real cluster needs longer).

## Decisions

1. **Bound with a capped thread pool + `future.result(timeout=…)`, not async hooks.**
   A module-level `ThreadPoolExecutor` runs the existing sync `_resolver`; `_validated_addresses` calls `future.result(timeout=_RESOLVE_TIMEOUT)`. This keeps every signature sync and the injectable-`_resolver` seam and all existing tests unchanged. The alternative — `async def` hooks awaiting `asyncio.wait_for(loop.getaddrinfo(...))` — is the more idiomatic mitmproxy shape but would force the guard chain and all three hooks async and rewrite the sync test harness; rejected as disproportionate for a self-DoS hardening. Trade-off accepted: a hung `getaddrinfo` leaks its worker thread until the OS resolver gives up, but the pool is capped so at most N hang concurrently; further calls never *run* a new thread and their `result(timeout)` still returns within the bound (fail-closed), so the loop is never blocked past the bound regardless of load.

2. **`_RESOLVE_TIMEOUT` = a small fixed number of seconds (5 s).**
   Long enough for a legitimately slow resolver, short enough that a stall is a blip not a freeze. A module constant beside `_IP_TTL_SECONDS`, documented; not configurable (no evidence a real cluster's DNS needs longer, and a knob here is attack surface).

3. **Timeout ⇒ fail closed, and distinct from fast-unresolvable.**
   Exceeding the bound returns `(False, "resolve-timeout", ∅)` — verdict denies, pin kills. A *fast* `OSError` keeps returning `(True, "unresolvable", ∅)` (unchanged). The difference is deliberate: NXDOMAIN means "provably nothing to connect to" (safe to permit); a timeout means "unknown" (must not permit). The pin's fail-closed kill already exists; this feeds it a denial verdict for the timeout case, and the denial is `_log_denial`'d like other guard denials.

4. **Do not cache timeouts.**
   Only real resolutions (public, or denied-by-address) enter `_ip_cache`. A timeout returns without caching, so a transient hang denies only the attempt that hit it — caching it would deny the host for the full 10 s TTL on one blip.

5. **Testing a hang without a real hang.**
   The injected `_resolver` becomes one that blocks on a `threading.Event` never set (or sleeps well past the bound); the test asserts `_validated_addresses`/`resolved_addresses_ok` returns fail-closed within a wall-clock margin under the bound, proving it did not block. A short test-only `_RESOLVE_TIMEOUT` (monkeypatched) keeps the suite fast. The blocked worker thread is a daemon so it never hangs test teardown.

## Risks / Trade-offs

- [Leaked worker threads under a sustained hanging-DNS flood] → Bounded by the pool size; excess resolutions fail closed within the bound without spawning threads. Daemon threads don't block shutdown. The agent only degrades its own session.
- [A legitimately slow cluster/registry DNS (>5 s) now fails closed] → Accepted; 5 s is generous for DNS, and the next attempt re-resolves (timeouts uncached). Bump the constant if a real deployment proves it too tight.
- [Pool executor as module state in the addon] → One small capped executor created at import, mirroring the module-level `_ip_cache`; no per-request setup cost.

## Migration Plan

No config/data/image-contract change; the addon ships in the proxy image, rebuilt per release. Rollback is a plain revert. Ships in the next patch release.
