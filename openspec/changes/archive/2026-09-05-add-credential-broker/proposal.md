# Proposal: add-credential-broker

## Why

Today a caged session authenticates to GitHub the way a human would: a one-time in-session `gh auth login` mints a user-scoped OAuth token that then lives in the agent's home, readable by the agent for the rest of the session. That is the last long-lived, agent-possessable secret in the cage. D2 (issue #2) replaces it with **short-TTL, per-session, per-repo-scoped credentials that the sandbox can use but never possess** — the real token is injected at the egress-proxy boundary and never enters the agent's filesystem, environment, or process memory.

## What Changes

- A host-side **broker** mints a per-session credential from a configured source and hands the proxy the real secret; the agent's git/gh traffic to the credential's destination host(s) is authenticated by the proxy **injecting** the secret on already-allowed, TLS-intercepted requests. The agent sees no token.
- **v0.1 source: a GitHub App installation token** (short-TTL — ~1h, repo-scoped) minted from an App id + private key + installation, refreshed by the broker before expiry. A **static-PAT passthrough** is supported as a fallback source for users without an App.
- **Placeholder discipline**: nothing real is written into the session home. The pre-wired `gh` credential helper and git are pointed at a placeholder; the proxy swaps placeholder→real per destination host (the pattern the field research called out; RFC-clean because the cage already MITMs TLS).
- **Teardown revokes**: the broker revokes/forgets the session's credential when the session ends — wired into the `tjor gc` / `tjor down` hook D3 already left in place.
- **Scope guard**: the proxy injects the credential **only** toward the credential's configured destination host(s) (like `identity.inject_hosts`), never elsewhere — a broker secret cannot leak to an unrelated allowed host.
- Fail-closed: no broker configured ⇒ behavior is exactly today's (in-session `gh auth login`); a broker configured but unable to mint ⇒ the session starts with no injected credential and says so, rather than silently falling back to a long-lived token.

Out of scope for v0.1: the fully opaque call-bound *handle* exchange (ADR 0005's north-star — a stronger bar than host-scoped injection; tracked as a follow-up), non-GitHub credential sources beyond static passthrough, and per-session LLM credentials (ADR 0005 stands: attribution-only).

## Capabilities

### New Capabilities

- `credential-broker`: minting, proxy-side injection scoped to destination hosts, refresh, and teardown revocation of per-session credentials — the agent never possesses the secret.

### Modified Capabilities

- `session-lifecycle`: the GC/teardown path SHALL revoke the session's brokered credential (the hook is already present; this change fills it in).

## Impact

- Code: a host-side broker (python, beside the policy/identity modules), proxy addon injection stage (reusing the identity-injection host-match machinery), config schema (`[broker]`), launcher wiring (mint on run, revoke on down/gc), unit tests + an integration test that proves the agent can `git clone` a private repo while no token is present anywhere in the container.
- No breaking changes: unconfigured broker = today's behavior.
