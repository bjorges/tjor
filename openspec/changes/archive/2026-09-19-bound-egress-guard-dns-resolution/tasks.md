# Tasks

## 1. Bounded resolution in the guard (proxy/addon.py)

- [x] 1.1 Add a `_RESOLVE_TIMEOUT` constant (5 s) and a small capped module-level `ThreadPoolExecutor`, beside `_ip_cache`/`_IP_TTL_SECONDS`, with a comment on why (event-loop-stall / self-DoS, #59)
- [x] 1.2 In `_validated_addresses()`, run the `_resolver(host)` call through the executor with `future.result(timeout=_RESOLVE_TIMEOUT)`: a fast `OSError` still returns `(True, "unresolvable", ∅)` (unchanged); exceeding the timeout returns `(False, "resolve-timeout", ∅)` and is NOT cached; a normal result is judged and cached exactly as today; verify the existing guard tests still pass unchanged
- [x] 1.3 Ensure the timeout denial flows through the existing paths: the verdict returns `ip-guard:resolve-timeout` (denied + `_log_denial`) and the `server_connect` pin kills the connection (it already fails closed when `_validated_addresses` returns not-ok); verify via the tests in task 2

## 2. Tests (python/tests/test_addon_guards.py)

- [x] 2.1 Hanging-resolver regression (#59): inject a `_resolver` that blocks on an unset `threading.Event` (daemon-safe), monkeypatch `_RESOLVE_TIMEOUT` to a small value, and assert `_validated_addresses`/`resolved_addresses_ok` returns fail-closed within a wall-clock margin below the real default — proving it does not block; verify `pytest python/tests/test_addon_guards.py` passes
- [x] 2.2 Timeout is fail-closed end-to-end: `request_verdict`/`connect_verdict` deny with an `ip-guard:resolve-timeout` rule, and the `server_connect` pin sets `data.server.error` (connection killed) on a hanging resolver
- [x] 2.3 Timeout is not cached: after a hanging resolution denies, a subsequent resolution that returns a public address is allowed (fresh evaluation, not a cached denial)
- [x] 2.4 Fast-unresolvable unchanged: a `_resolver` raising `OSError` promptly still returns the permitted "unresolvable" verdict (not treated as a timeout)

## 3. Docs and changelog

- [x] 3.1 Update the addon docstring / add a comment on `_RESOLVE_TIMEOUT` describing the bound and the fail-closed-on-timeout vs pass-on-fast-unresolvable distinction
- [x] 3.2 CHANGELOG entry under `[Unreleased]` (Security) describing the event-loop-stall self-DoS and the bounded-resolution fix, referencing #59

## 4. Full verification

- [x] 4.1 Run the full local gate — `pytest python/tests/` (mitmproxy installed), `tests/doc_consistency.sh`, and `openspec validate bound-egress-guard-dns-resolution` — and verify everything is green
