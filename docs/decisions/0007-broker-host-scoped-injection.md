# ADR 0007 — Credential broker: host-scoped injection (v0.1) vs opaque handles

**Date:** 2026-09-05 · **Status:** accepted

D2 removes the last long-lived, agent-possessable secret (the GitHub token)
from the cage. ADR 0005 named the north-star: **opaque, call-bound,
single-use credential handles** exchanged for the real secret only at the
proxy. v0.1 ships a nearer bar and records why.

**Decision.** The broker holds the real, short-TTL credential in the **proxy
sidecar only** (egress side, unreachable from the agent network) and injects
it into the `Authorization` header of intercepted requests toward the
credential's configured destination host(s) only. The agent holds a fixed
**placeholder** so git attempts auth; the proxy overwrites it. This reuses
D1's host-scoped injection stage and D3's teardown-revocation hook.

**What this achieves (the important part).** The real secret never enters the
agent's filesystem, environment, process memory, or tool output — proven by
an integration test that scans a live agent container. Credentials are
short-TTL (GitHub App installation tokens, ~1h, repo-scoped) and refreshed in
the proxy; revoked best-effort at teardown, auto-expiring as the backstop.

**Where it stops short of ADR 0005.** Injection is *host-scoped*, not
*call-bound*: within a destination host's scope, the proxy could authenticate
any request the agent makes to that host, not just one pre-authorized call.
A compromised proxy is therefore as powerful as the credential's scope. This
is accepted for v0.1 because the proxy is *already* the session's most-trusted
component (it holds the MITM CA private key); D2 adds no new trust boundary,
only a secret to the component that already has the highest one. Least-
privilege is applied at the source instead: GitHub App tokens are scoped to
the session's repositories.

**The follow-up.** The opaque-handle model (call-bound, destination-locked,
single-use) is the tracked next step; the injection stage is deliberately the
seam where it plugs in — the agent-facing contract (placeholder) does not
change when the proxy-side exchange is tightened.

**Known limitations (v0.1, surfaced by review).**

- **The broker removes the *need* for the agent to hold a token, not its
  *ability* to obtain one.** A user or a compromised task can still run
  `gh auth login` inside a broker-enabled session and mint a real, long-lived
  token via the interactive device flow (github.com and api.github.com are on
  the allowlist). The broker guarantees that *tjor* never places a real secret
  in the sandbox; it does not sandbox away the agent's own ability to
  authenticate. Closing this would require blocking the auth endpoints or
  wrapping `gh` — deferred; documented here so the "agent never holds a real
  secret" claim is read precisely (tjor-supplied credentials, not
  agent-minted ones).
- **Revocation depends on a graceful proxy shutdown.** `tjor down`/`gc` now
  stop the proxy with SIGTERM (grace period) *before* force-removal so the
  addon's `done()` hook revokes the credential; the ~1h installation-token
  TTL is the backstop if that shutdown is ever skipped (an out-of-band
  `docker rm -f`). This corrects an earlier release where force-removal
  SIGKILLed the proxy and revocation never fired.

**Alternatives considered.** Broker as a separate sidecar with its own API —
rejected: another admin surface to keep off the agent network (charter L30),
no gain over holding the secret in the proxy that already terminates TLS.
Writing a short-TTL token into the agent home (the original D2 sketch) —
rejected: it still *possesses* the secret; injection at the proxy is strictly
stronger.
