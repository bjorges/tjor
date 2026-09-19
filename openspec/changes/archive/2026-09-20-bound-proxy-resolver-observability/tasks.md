# Tasks

## 1. Bound the proxy's OS resolver (proxy/entrypoint.sh)

- [x] 1.1 Export `RES_OPTIONS="timeout:<t> attempts:<n>"` before the `exec`, with a small default (`timeout:1 attempts:2`) overridable via env (e.g. `TJOR_PROXY_RES_OPTIONS`) so glibc bounds every `getaddrinfo` in the proxy process; only set it when not already provided by the environment; verify via task 4.1
- [x] 1.2 Plumb the knob: pass the value through `compose.yaml` to the proxy service (and a `[proxy]` config default if that layer is used), documented as the proxy resolver bound; verify `compose config` renders

## 2. Surface cap saturation (proxy/addon.py)

- [x] 2.1 At the `resolve-capacity` denial in `_validated_addresses`, emit a rate-limited operator-facing stderr line via a bounded `_resolve_saturation_count` (mirroring `_denial_log_count`/`_strip_log_count`): first N and every Nth, host `_safe_ascii`-sanitized; verify via task 3.1

## 3. Tests (python/tests/test_addon_guards.py)

- [x] 3.1 Saturation signal: drive `_validated_addresses` into `resolve-capacity` (seed `_inflight` to the cap) repeatedly and assert the bounded stderr signal fires (first-N/every-Nth), is rate-limited (not once per call unbounded), and sanitizes the host; verify `pytest python/tests/test_addon_guards.py` passes

## 4. Resolver-bound check + docs

- [x] 4.1 Assert `proxy/entrypoint.sh` sets a bounded `RES_OPTIONS` (a shell/grep or unit check); document that the empirical black-hole bound (a live proxy container with a black-holed resolver returns within the bound) is a manual/CI check, noting glibc honors `RES_OPTIONS`
- [x] 4.2 README/config: note the proxy resolver bound and the shrunken residual (fast bounded recovery + observable saturation); reference #61

## 5. Changelog

- [x] 5.1 CHANGELOG entry under `[Unreleased]` (Security) describing the bounded proxy resolver (provable recovery) + observable cap saturation, referencing #61 (and #59); note the benign deny→permit interaction for black-holed allowed hosts

## 6. Full verification

- [x] 6.1 Run the full local gate — `pytest python/tests/` (mitmproxy installed), `tests/doc_consistency.sh`, `bash -n`/shellcheck on `proxy/entrypoint.sh`, and `openspec validate bound-proxy-resolver-observability` — and verify everything is green
