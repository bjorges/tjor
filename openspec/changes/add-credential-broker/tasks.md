# Tasks: add-credential-broker

## 1. Broker module

- [ ] 1.1 `tjor_broker` module beside the policy/identity modules: source abstraction with two backends — GitHub App installation token (mint via API from app-id + private-key + installation-id, with expiry) and static-PAT passthrough; `mint()`, `refresh_if_stale()`, `revoke()` — verified by unit tests with a mocked GitHub API (mint returns token+expiry, refresh renews near expiry, revoke calls the revoke endpoint / forgets)
- [ ] 1.2 Config schema `[broker]`: source type, destination hosts (via the shared host matcher), and source params (app-id/key-path/installation, or a pat env-var reference) — verified by config unit tests; a broker config that fails to load fails closed (no injection), never a silent long-lived fallback

## 2. Proxy injection

- [ ] 2.1 Extend the addon injection stage: strip the fixed placeholder credential and inject the current real credential into the `Authorization` header on intercepted requests whose host matches the credential's destination; fail-closed wrapper; never inject toward non-destination hosts — verified by unit tests on the transform (placeholder-strip, host-scoping, missing-credential = strip only)
- [ ] 2.2 Deliver the current secret to the proxy on the egress side only and rotate it on refresh (config-hash/label discipline per charter L30 — never agent-reachable, never in labels) — verified by a topology assertion that the broker/secret surface is unreachable from the agent network

## 3. Launcher & entrypoint wiring

- [ ] 3.1 On `tjor run` with a broker configured: mint the session credential, register it with the proxy; entrypoint pre-wires git/gh to the fixed placeholder (no real value in the home) — verified in-cage: git config holds only the placeholder
- [ ] 3.2 Fill the D3 teardown hook: `tjor down` / `tjor gc` revoke the session's credential before removing resources — verified by an integration assertion that revoke is invoked (stub source records it)

## 4. Integration & conformance

- [ ] 4.1 End-to-end: a stub credential source on the egress side + a stub destination host that echoes the received `Authorization`; the agent's request arrives authenticated while a full-container scan (filesystem + env + process args) finds no real secret — verified by the integration test green locally and in CI
- [ ] 4.2 Teardown revocation and fail-closed (broker configured but mint fails ⇒ no injection, loud, no long-lived fallback) — verified by integration cases
- [ ] 4.3 Docs: README broker section + `[broker]` config documented (App setup and static-PAT fallback), ADR for the v0.1 host-scoped-injection vs opaque-handle decision; move D2 from roadmap to shipped
