# Tasks

## 1. Validated-address plumbing in the guard

- [x] 1.1 Refactor `resolved_addresses_ok()` in `proxy/addon.py` around one shared validation helper that returns `(ok, why, validated_addresses)` and stores all three in `_ip_cache` (entries become `(ts, ok, why, addresses)`), keeping `resolved_addresses_ok()`'s public `(ok, why)` signature and semantics (exemptions, IP literals, unresolvable-passes, cache TTL) unchanged; verify the existing guard tests in `python/tests/test_addon_guards.py` still pass unmodified
- [x] 1.2 Add a deterministic pin-selection helper (prefer IPv4, then lexicographic) per design decision 4; verify with unit tests covering IPv4-preferred over IPv6, IPv6-only sets, and single-address sets

## 2. The server_connect pin hook

- [x] 2.1 Add a `server_connect(data)` hook to `TjorPolicy`: return immediately (no pin) when the guard is off, the host is gateway/kube-exempt, or the destination is an IP literal; otherwise resolve-and-validate via the shared helper (cache-aware), pin `data.server.address` to the selected validated address on success, and on validation failure set `data.server.error` and record the denial via `_log_denial` with rule `ip-guard-pin:<why>`; an unresolvable host is left unpinned; verify via the hook-level tests in task 3
- [x] 2.2 Wrap the entire hook body fail-closed: any exception sets `data.server.error` (never a silent pass-through), mirroring `_fail_closed()`'s contract; verify via the fail-closed test in task 3.4

## 3. Adversarial hook-level tests (python/tests/test_addon_guards.py, mitmproxy-gated)

- [x] 3.1 Rebinding TOCTOU regression (#41): a flipping `_resolver` returns a public address on the first resolution (request/CONNECT-time verdict passes) and a private address afterwards; drive `server_connect` with real `ServerConnectionHookData` and assert the connection is killed (`data.server.error` set) or pinned to the validated public address — never connected toward the private one — and the denial is logged; verify `pytest python/tests/test_addon_guards.py` passes with mitmproxy installed
- [x] 3.2 Pin correctness: with a stable public resolution, assert `data.server.address` is rewritten to the validated address (deterministic selection) with the port preserved, and `data.server.sni` is never touched by the addon; verify via pytest
- [x] 3.3 No-pin branches: guard off (`_IP_GUARD` false), gateway-exempt and kube-exempt hosts, IP-literal destination, and unresolvable host each leave `data.server.address` and `data.server.error` unchanged; verify via pytest
- [x] 3.4 Fail-closed: a resolver raising an unexpected exception inside the hook results in `data.server.error` set (connection killed), never an unpinned pass-through; verify via pytest

## 4. Docs and changelog

- [x] 4.1 Replace the addon docstring's residual-TOCTOU paragraph (`proxy/addon.py` header) with the resolve-and-pin description, and update the `_IP_TTL_SECONDS` comment (the cache now bounds address staleness, not a TOCTOU window); verify the docstring reads correctly
- [x] 4.2 Add a CHANGELOG entry under `[Unreleased]` (Security) describing the resolve→connect rebinding TOCTOU and the resolve-and-pin fix, referencing #41 and noting the recorded conformance-probe scope decision; verify the entry renders under the correct heading

## 5. Full verification

- [x] 5.1 Run the full local gate — `pytest python/tests/` with mitmproxy installed (the new hook tests must not skip), `tests/doc_consistency.sh` — and verify everything is green
