# Tasks

## 1. Pool-exhaustion mitigation (proxy/addon.py)

- [x] 1.1 Env-configurable knobs: parse `_RESOLVE_TIMEOUT`, `_RESOLVE_WORKERS`, `_RESOLVE_MAX_INFLIGHT`, and `_RESOLVE_NEGATIVE_TTL` from `TJOR_`-prefixed env with the current values as defaults (matching the `TJOR_IP_GUARD` style); verify a unit test can override them
- [x] 1.2 Per-host in-flight coalescing: an `_inflight` map so at most one resolution per host runs; concurrent requests for the same host wait on the one future; a done-callback removes the host when the worker finishes (leave it on timeout so waiters keep coalescing onto the hung future); verify via task 2.1
- [x] 1.3 Bounded distinct in-flight, fail-fast: when `len(_inflight)` is at the cap and the host is not already in flight, return `(False, "resolve-capacity", frozenset())` immediately (no submit, no queue); verify via task 2.2
- [x] 1.4 Brief negative-cache of resolve-timeouts: cache `(False, "resolve-timeout", ∅)` under `_RESOLVE_NEGATIVE_TTL` (shorter than the positive `_IP_TTL_SECONDS`); the lookup applies the negative TTL to timeout entries and the positive TTL to successful ones; verify via task 2.3
- [x] 1.5 Explicit pool shutdown in `TjorPolicy.done()` (`_resolve_pool.shutdown(wait=False, cancel_futures=True)`); verify no exception on teardown

## 2. Mitigation tests (python/tests/test_addon_guards.py)

- [x] 2.1 Coalescing: many concurrent resolutions of one slow host (blocking `_resolver` gated by an `Event`) use a single worker, and a different fast host still resolves — i.e. one slow host does not exhaust capacity; verify `pytest python/tests/test_addon_guards.py` passes
- [x] 2.2 Cap fail-fast: with the cap saturated by distinct hung hosts, a further distinct host returns fail-closed **fast** (well under the timeout) with a capacity reason
- [x] 2.3 Negative-cache then recover: a timed-out host is served fail-closed from cache within the window (no new worker), and after the window (monkeypatched short) a now-fast resolution is allowed
- [x] 2.4 Existing bounded-resolution + guard tests still pass unchanged (single-call timeout, fast-unresolvable, pin/verdict wiring)

## 3. Structured denial reason (#60 robustness)

- [x] 3.1 Change `_address_public` to return `(ok, reason_class, detail)`; update `_validated_addresses` to compose the operator `why` from them; simplify `_agent_reason`/`_agent_rule` to key off `reason_class` (no free-text `startswith`); verify existing address-judgment and redaction tests still pass
- [x] 3.2 Tests: the agent-facing reason is derived from `reason_class` (a reworded `detail` cannot change the redacted output), and an end-to-end test exercises the `server_connect` pin-kill redaction for a **non-global-address** reason specifically (the coverage gap @homer flagged); verify pytest passes

## 4. api_host comma check (#57 advisory)

- [x] 4.1 In `bin/tjor`, reject a comma in the derived kube `api` host (parity with the context-name comma check), fail-closed with a clear message; add a `tests/integration/kube_test.sh` branch asserting an `api_host` containing a comma disables the broker; verify the suite passes

## 5. Docs and changelog

- [x] 5.1 Update the addon docstring / `_RESOLVE_*` comments to describe coalescing + cap + negative-cache + the documented residual (many distinct slow hosts, fail-closed); document the new env knobs where the other `TJOR_` knobs are documented
- [x] 5.2 CHANGELOG entry under `[Unreleased]` (Security) covering the pool-exhaustion hardening (#59 follow-up), the structured-reason robustness (#60), and the `api_host` comma check (#57); note the reversed "timeouts now briefly cached" behavior

## 6. Full verification

- [x] 6.1 Run the full local gate — `pytest python/tests/` (mitmproxy installed), `tests/integration/kube_test.sh`, `tests/doc_consistency.sh`, and `openspec validate harden-egress-guard-dns-availability` — and verify everything is green
