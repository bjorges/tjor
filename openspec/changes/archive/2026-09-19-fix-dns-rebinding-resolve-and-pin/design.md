# Design

## Context

See proposal.md — Why. The relevant current state, verified against the shipped mitmproxy version (12.1.2):

- `resolved_addresses_ok(host)` (`proxy/addon.py`) resolves via an injectable `_resolver`, judges every address with `_address_public()` (IANA deny-nets + embedded-IPv4 unwrapping), caches `(ts, ok, why)` for 10 s, and is called from `connect_verdict()` / `request_verdict()` — i.e. at CONNECT/request time only. mitmproxy later resolves the hostname again when opening the upstream socket; nothing connects the two resolutions.
- mitmproxy 12.1.2's `server_connect(data)` hook fires before that connection; `data.server.address` is mutable there, and per the hook's own contract "Setting `data.server.error` kills the connection."
- Upstream TLS (mitmproxy `tlsconfig`): `server.sni = client.sni or server.address[0]`, and certificate verification uses `server.sni or address[0]`. For HTTPS through CONNECT the client's SNI is the hostname, so rewriting `address` to an IP leaves SNI and cert verification on the hostname. Plain-HTTP flows keep their Host header. The addon never touches `server.sni`.
- The guard suite (`python/tests/test_addon_guards.py`) loads the addon standalone, injects `_resolver`, and already contains mitmproxy-gated tests — the natural venue for hook-level adversarial cases. The `tjor conformance` topology runs with `TJOR_IP_GUARD=off` by design and cannot exercise the guard e2e.
- The addon's conventions: every enforcement path is wrapped fail-closed (an addon exception must never pass a request through), and denials are recorded via `_log_denial` for `tjor denials`.

## Goals / Non-Goals

**Goals:**
- One resolution feeds both the judgment and the connection: after the pin there is no second resolution to attack.
- The kill path is as fail-closed as the verdict path: validation failure or any exception at the hook kills the connection.
- Deterministic, unit-testable pin selection and cache behavior.

**Non-Goals:**
- Changing the guard's judgment itself (`_address_public`, deny-nets, embedded-IPv4 unwrapping) — untouched.
- Changing DNS behavior for the agent (CoreDNS sidecar) — this is proxy-side only.
- An e2e conformance-container probe (see the recorded scope decision in proposal.md).
- Pinning exempt hosts or guard-off sessions — deliberate internal endpoints need live docker DNS across container restarts.

## Decisions

1. **Pin in `server_connect` by rewriting `data.server.address`; kill by setting `data.server.error`.**
   Both are the hook's documented contract in mitmproxy 12.1.2 (verified in source, not from memory). Alternatives rejected: rewriting `flow.request.host` at request time breaks Host headers and TLS SNI derivation; a custom resolver/connection layer would fork mitmproxy internals this addon deliberately avoids.

2. **The guard's verdict hooks stay; `server_connect` becomes the enforcement point.**
   `http_connect`/`request` keep producing early 403s with rule names — good operator UX and unchanged parity/conformance behavior. Security no longer depends on them: whatever they concluded, the connection itself is made only to an address validated in the same hook that pins it. If the 10 s cache is fresh, the pin uses the cached *validated addresses*; if it expired, the hook re-resolves and re-validates. Either way no unvalidated address is ever connected.

3. **The cache stores the validated addresses.**
   `_ip_cache` entries become `(ts, ok, why, addresses)` via one shared validation helper that both the verdict path and the pin hook call. Pinning from a ≤10 s-old validated set is an availability trade, not a security one — every cached address passed the guard.

4. **Deterministic pin selection: prefer IPv4, then lexicographic.**
   `getaddrinfo` order is resolver-dependent; a deterministic choice keeps tests exact and behavior reproducible. Preferring IPv4 matches the proxy's container network reality; an IPv6-only upstream still pins its (validated) IPv6 address. Trade-off accepted: a pinned connection loses mitmproxy's multi-address fallback within one attempt — a retry is a new flow, which re-resolves and re-pins.

5. **No-pin branches are explicit and first: guard off, exempt host, IP literal, unresolvable.**
   Guard-off and exemptions preserve today's behavior exactly (live docker DNS for gateway/kube API hosts). An IP-literal destination is already the address that gets judged — nothing to pin. An unresolvable host stays unpinned so mitmproxy's own resolution fails the connection, keeping parity with the guard's documented unresolvable-passes stance rather than inventing a new denial class.

6. **Fail-closed wrapper around the hook.**
   Any exception while validating/pinning sets `data.server.error` — mirroring `_fail_closed()`'s contract that an addon error never lets traffic pass. Kills are also `_log_denial`'d (rule `ip-guard-pin:<why>`) so `tjor denials` shows them despite the client only seeing a failed connection.

7. **Rebinding regression tests drive the real hook.**
   Tests construct `ServerConnectionHookData` against a live-shaped `Server` object and a flipping `_resolver` (public at verdict time, private at connect time), asserting the connection is killed or pinned to the validated address — the exact TOCTOU sequence from #41, executed through the code mitmproxy invokes. These sit with the existing mitmproxy-gated tests in the guard suite.

## Risks / Trade-offs

- [Pinned address is down while another A record works] → One failed connection; the client's retry re-resolves and re-pins. Accepted: a security boundary choosing determinism over happy-eyeballs.
- [Kill at connect shows the client an opaque connection error, not a 403] → The denial log and proxy stderr carry the host and reason; the early verdict hooks still 403 the common (non-racing) case with a readable rule.
- [A long-lived keep-alive connection outlives a legitimate DNS move] → Identical to today: an established socket never re-resolves. No new exposure.
- [Guard-off conformance topology never exercises the pin e2e] → Accepted and recorded in the proposal; the hook-level suite covers the sequence, and #38's results matrix can cite it.

## Migration Plan

No config, data, or image-contract changes — the addon ships inside the proxy image, rebuilt per release as usual. Rollback is a plain revert.
