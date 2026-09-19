# Proposal

## Why

The proxy's resolved-address guard (`proxy/addon.py`) validates where an allowed hostname resolves, but validation and connection are two separate resolutions: the guard resolves at CONNECT/request time, then mitmproxy re-resolves when it actually opens the upstream connection. A low-TTL record that flips between the two points `connect()` at a private address the guard never saw — a DNS-rebinding TOCTOU against the egress boundary (#41). The addon's own docstring documents this residual window, and the guard's 10-second verdict cache *widens* it: a cached "ok" lets a since-flipped name pass while mitmproxy resolves fresh. tjor's threat model (the agent is adversarial; the proxy is dual-homed) makes this the bridge-into-internal-network primitive the guard exists to deny.

## What Changes

- **Enforcement moves to the connection.** A new `server_connect` hook resolves the hostname once, validates every returned address, and pins `data.server.address` to a validated address — after which no second resolution exists: the address that passed the check is provably the address connected to.
- A hostname that fails validation at connection time has the connection killed (`data.server.error`) and the denial recorded in the session denial log; any exception in the hook also kills the connection (fail-closed, matching the addon's existing convention).
- The existing CONNECT/request-stage guard checks stay as early, friendly `403` denials with rule names — useful UX, no longer the security enforcement point.
- The guard's cache now carries the validated addresses, so a pin within the trust window uses exactly the addresses that were judged.
- **No pin** for the config-scoped exemptions (gateway host, kube API host — deliberate internal endpoints whose container IPs change on restart and need live docker DNS), for `TJOR_IP_GUARD=off`, for IP-literal destinations (already judged as addresses), or for a hostname unresolvable at connect time (mitmproxy's own resolution then fails; nothing flows — parity with the guard's documented unresolvable-passes stance).
- Adversarial rebinding regression tests at the real mitmproxy hook seam: a resolver that returns a public address at check time and a private one at connect time must not be able to redirect the connection.
- **Recorded scope decision**: #41 asks for "a conformance probe" for the rebinding case, but the `tjor conformance` topology deliberately runs with `TJOR_IP_GUARD=off` (`bin/tjor` — every fixture resolves to a container-network address; "the guard itself is covered by unit tests"). An e2e probe there cannot exercise a disabled guard, so the rebinding regression test lives in the guard suite (`python/tests/test_addon_guards.py`) driving the actual `server_connect` hook — the same venue that already covers the guard, and the acceptance criterion (the rebinding case is regression-tested against the real code path) is preserved.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cage-network`: ADDED requirement — egress connections are made only to addresses the resolved-address guard validated (resolve-and-pin); a DNS answer that changes between validation and connection cannot redirect the connection.

## Impact

- **Code**: `proxy/addon.py` — validated-address plumbing in the guard, a deterministic pin-selection helper, and a `server_connect` hook on `TjorPolicy`. No launcher, compose, or image changes.
- **Tests**: `python/tests/test_addon_guards.py` (hook-level rebinding TOCTOU, pin correctness, no-pin branches, fail-closed).
- **Docs**: the addon docstring's residual-TOCTOU paragraph is replaced by the resolve-and-pin description; CHANGELOG Security entry referencing #41.
- **Behavior change**: a host that fails validation at connect time now dies at the connection (opaque upstream error to the client, with the reason in the denial log and proxy stderr) instead of possibly slipping through; a pinned connection uses one validated address, so per-connection multi-address failover is traded away (a retry opens a new connection and re-resolves + re-pins). Closes #41.
