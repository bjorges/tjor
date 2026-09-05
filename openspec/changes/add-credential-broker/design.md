# Design: add-credential-broker

## Context

The cage already MITMs TLS (constrained per-session CA), the proxy addon already has a host-scoped **injection** stage (D1's `identity.inject_hosts` proves the mechanism), and D3 already left a **revocation hook** in the `gc`/`down` teardown path. D2 fills those in for credentials. Constraints: ADR 0005 (attribution-only LLM identity — broker covers non-LLM credentials), charter L26 (host-side scripts touching agent-writable paths must be symlink-safe — the broker writes nothing into the agent home, so it sidesteps this by construction), charter L30 (no admin surface reachable from the agent network).

## Goals / Non-Goals

**Goals:** the last long-lived agent-possessable secret (the GitHub token) leaves the sandbox; per-session, short-TTL, repo-scoped; injected at the proxy, revoked at teardown; fail-closed and non-downgrading.

**Non-Goals:** the fully opaque call-bound *handle* exchange (ADR 0005's stronger north-star — a follow-up); credential sources beyond GitHub App + static-PAT passthrough; per-session LLM keys (ADR 0005 stands).

## Decisions

- **Inject at the proxy, scoped by destination host — reuse D1's machinery.** The credential is added to the `Authorization` header of intercepted requests whose host matches the credential's configured destination (e.g. `github.com`, `api.github.com`, `codeload.github.com`). This is the exact host-match + header-set stage D1 already built; D2 adds a *credential* value keyed by host, and reuses the fail-closed wrapper. *Alternative:* the placeholder-swap-in-body pattern (field research) — kept as the model for non-header credential forms, but header injection is cleaner for git-over-HTTPS and needs no body rewriting.
- **The agent holds only a placeholder.** git/gh are pre-wired (entrypoint) to send a fixed placeholder credential; the proxy strips the placeholder and injects the real one. So even the placeholder leaking tells an attacker nothing. Git-over-HTTPS basic auth carries the token in the `Authorization` header the proxy already sees post-MITM.
- **Broker runs host-side, on the egress network side of the proxy — never reachable from the agent network** (charter L30). It mints from a source and hands the proxy the current secret via the proxy's own config/env (recreated on rotation like any config drift, charter L12), or via a broker→proxy channel on the egress network only. The agent network cannot reach the broker.
- **v0.1 source = GitHub App installation token.** App id + private key (host-side, never in-image) + installation id → a ~1h repo-scoped token via the GitHub API. The broker refreshes before expiry. *Alternative source:* static PAT passthrough — no TTL benefit, but works for users without an App and still keeps the token out of the sandbox (injected at proxy, not written to home). Configured via `[broker]`.
- **Rotation without disturbing the session.** Token refresh updates the proxy's held secret; because injection reads the current value per request, in-flight and future requests use the fresh token with no agent-visible change. The proxy's admin/secret surface stays off the agent network (L30) and out of labels/config-hash (L30's corollary).
- **Teardown revocation via the existing D3 hook.** `tjor gc`/`down` already call a documented hook point; D2 makes it revoke (App tokens can be revoked via the API; static PATs are simply forgotten). Revoke runs *before* resource removal so a torn-down session's credential is dead immediately.

## Risks / Trade-offs

- **The proxy now holds a live secret in memory** — but the proxy already holds the MITM CA private key, so it is already the session's most-trusted component; concentrating the credential there does not add a new trust boundary. It is on the egress side, unreachable from the agent.
- **Placeholder-based git auth assumes git uses the `Authorization` header the proxy intercepts** — true for HTTPS basic/bearer; SSH is already rewritten to HTTPS (D3-era entrypoint), so this composes.
- **GitHub App setup is more work than a PAT** for the user — hence the static-PAT passthrough fallback, which still removes the token from the sandbox even without the TTL benefit.
- **Not yet the opaque-handle bar** (ADR 0005): host-scoped injection means a compromised proxy could use the credential broadly within its destination scope. Accepted for v0.1; the handle model (call-bound, single-use) is the tracked follow-up and this design leaves the injection stage where it can be tightened to it.

## Verification approach

Unit tests for the broker's mint/refresh/revoke logic (mocked GitHub API) and for the proxy injection stage (host-scoped, fail-closed, placeholder-strip) via the importable transform functions. Integration: an end-to-end test that configures a broker (a stub credential source on the egress side), launches a session, and asserts the agent can reach the destination host authenticated while `grep`-ing the entire container (fs + env + process args) proves the real secret is absent — plus a teardown test asserting the credential is revoked/forgotten.
