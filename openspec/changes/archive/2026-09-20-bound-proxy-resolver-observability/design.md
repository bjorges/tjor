# Design

## Context

See proposal.md — Why. Verified:

- The proxy base is `mitmproxy/mitmproxy:12.1.2` — Debian/glibc (its entrypoint uses `usermod`, `stat -c`, `gosu`). glibc's `getaddrinfo` honors the `RES_OPTIONS` environment variable (`timeout:`, `attempts:`), so exporting it in `proxy/entrypoint.sh` before the `exec` bounds every resolution the proxy process makes — both the addon guard's `_resolver` and mitmproxy's own upstream connect (same process, same resolver).
- `proxy/entrypoint.sh` is `#!/bin/sh`, runs as root, aligns the uid, then `exec gosu mitmproxy "$@"`. Env exported there is inherited by the mitmproxy process.
- `proxy/addon.py` already rate-limits operator-facing logs with bounded counters (`_denial_log_count`, `_strip_log_count`) to stderr; the `resolve-capacity` denial is returned from `_validated_addresses` and has no signal today.
- The addon's `_RESOLVE_TIMEOUT` default is 5s; a fast `OSError` from `_resolver` is the guard's "unresolvable → permitted (nothing can connect)" path.

## Goals / Non-Goals

**Goals:**
- A hung/black-holed lookup in the proxy returns within a bounded, documented wall time, so workers free fast and the cap self-recovers.
- Cap saturation is visible to an operator.
- Config/env-tunable; no new dependency.

**Non-Goals:**
- Killing hung worker threads (still impossible; the OS bound makes it unnecessary — the thread returns on its own within the bound).
- A non-blocking DNS resolver / new dependency (still declined; the OS bound + observability close the residual within the stdlib posture).
- Eliminating the residual entirely (many distinct slow hosts can still transiently saturate — now bounded-recovery and observable).

## Decisions

1. **Bound the OS resolver with `RES_OPTIONS`, set in the proxy entrypoint.**
   `export RES_OPTIONS="timeout:${t} attempts:${n}"` before the `exec`. glibc then caps each lookup at roughly `timeout × (attempts rounds, doubling)` per nameserver. Default `timeout:1 attempts:2` (~3s) balances a lost-packet retry against a tight bound. Chosen over rewriting `/etc/resolv.conf` (docker manages that file; an env var is cleaner and needs no write) and over a non-blocking resolver (dependency, declined). Value is tunable via a `[proxy]` knob / env with the small default.

2. **Keep the OS bound below the addon `_RESOLVE_TIMEOUT`.**
   With the resolver bound (~3s) < the addon bound (5s), a black-holed lookup returns a fast resolver error before the addon's timeout — the guard treats it as its existing "unresolvable → permitted" case (nothing can connect), and the worker frees at ~3s. This is the intended interaction: recovery is fast and provable. The deny-vs-permit distinction for an unreachable host is immaterial (no connection results either way); documented so it is not a surprise. (If an operator raises the OS bound above the addon bound, the addon's `resolve-timeout` fail-closed deny remains the backstop — still safe.)

3. **Rate-limited saturation signal in the addon.**
   A bounded `_resolve_saturation_count` (mirroring `_denial_log_count`): the first N and every Nth `resolve-capacity` denial print a rate-limited stderr line (`safe`-sanitized host). No new sink or dependency; reuses the operator-log pattern. It records that capacity saturated, not the specific hosts beyond the (sanitized) current one.

4. **Testing split by feasibility.**
   The saturation signal is unit-tested in `test_addon_guards.py` (drive `resolve-capacity`, assert the bounded log fires). The `RES_OPTIONS` export is asserted by a cheap check that the entrypoint sets a bounded value; the *empirical* black-hole bound (a real hung nameserver returning within the bound) needs a live proxy container with a black-holed resolver and is a documented manual/CI check — mirroring the kube live-cluster manual check, since the dockerless test suites can't stand up a black-hole.

## Risks / Trade-offs

- [`attempts:2 timeout:1` is too tight for a genuinely slow-but-healthy resolver on a loaded host] → Tunable via the knob; the default is generous for in-datacenter DNS and the negative-cache/retry still cover a transient miss. Operators on slow DNS can raise it.
- [The deny→permit flip for black-holed allowed hosts changes the observable denial] → Benign (nothing connects), and documented; the security boundary is unchanged.
- [The empirical OS-bound isn't covered by an automated dockerless test] → Accepted and stated; the env-set is asserted, the bound is a documented check, and glibc's honoring of `RES_OPTIONS` is well-established behavior.

## Migration Plan

Additive: an env export in the proxy entrypoint (small default, tunable), a bounded log line, docs. No data/spec-format change; the proxy image is rebuilt per release. Rollback is a plain revert. Patch release.
