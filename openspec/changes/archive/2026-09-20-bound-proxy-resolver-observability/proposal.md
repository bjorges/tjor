# Proposal

## Why

The v0.18.4 pool-availability hardening (#59 re-review) left one disclosed Medium residual (#61): a sustained attack on many *distinct* slow-DNS hosts can still saturate the resolver cap, and its "self-recovering, no restart" property rests on an **unverified** assumption — that the OS resolver eventually gives up on a hung `getaddrinfo()`. With the proxy's default resolver config, a black-holed nameserver can hang a worker for tens of seconds, so the cap frees slowly and the residual is larger than it needs to be. And when the cap *is* saturated, it happens silently — an operator can't see a sustained many-host attack. This change makes recovery **provable** and saturation **observable** — the two halves @linus recommended.

## What Changes

- **Bound the proxy's OS resolver.** The proxy image is Debian/glibc, which honors `RES_OPTIONS`; the proxy entrypoint exports `RES_OPTIONS="timeout:<t> attempts:<n>"` (config/env-tunable, small by default, e.g. `timeout:1 attempts:2` ≈ 3s), so a hung/black-holed lookup returns within a bounded, documented wall time instead of the OS default. Workers therefore free within that bound, so the cap recovers fast without a proxy restart — turning "expected to recover" into "provably recovers."
- **Surface cap saturation.** When the resolver cap (`_RESOLVE_MAX_INFLIGHT`) is hit and a request is denied `resolve-capacity`, the proxy emits a bounded operator-facing signal to stderr (rate-limited, like the existing forged-identity/denial-log counters), so a sustained many-distinct-host attack is visible rather than silent.
- **Document the bound.** The README/config note the resolver bound and the (now much smaller) residual.

Interaction, noted deliberately: with the OS bound tighter than the addon's `_RESOLVE_TIMEOUT`, a black-holed *allowed* host now returns a fast resolver error (treated as the guard's existing "unresolvable → permitted, nothing can connect" case) at ~the OS bound, rather than the addon's slower `resolve-timeout` deny. Both outcomes are safe — no connection results either way — and the worker frees fast, which is the point. The deny-vs-permit distinction only ever mattered for a host that can't be reached at all.

## Capabilities

### Modified Capabilities

- `cage-network`: MODIFIED "Address resolution is time-bounded and fails closed" — add that the resolution bound is enforced at the resolver layer (a hung lookup recovers within a bounded, configured time, not the OS default) and that resolver-capacity saturation is surfaced to the operator.

## Impact

- **Code**: `proxy/entrypoint.sh` (export `RES_OPTIONS`, value from a `[proxy]`/env knob with a small default); `proxy/addon.py` (a bounded stderr saturation counter at the `resolve-capacity` return, mirroring `_denial_log_count`); `config/tjor.toml`/`compose.yaml` for the knob if plumbed through config.
- **Tests**: `python/tests/test_addon_guards.py` (saturation signal fires, bounded); a check that the proxy entrypoint sets `RES_OPTIONS` to a bounded value (the empirical black-hole bound is a documented manual/CI check, like the kube live-cluster check — a true DNS black-hole needs a live proxy container).
- **Docs**: README/config note the resolver bound + the shrunken residual; CHANGELOG (Security) referencing #61/#59.
- **Behavior change**: proxy DNS lookups are bounded to the configured resolver timeout (a hung lookup now errors fast, freeing its worker); a new operator stderr line on cap saturation. No security-boundary change — still fails closed / permits only where nothing can connect. Closes #61.
