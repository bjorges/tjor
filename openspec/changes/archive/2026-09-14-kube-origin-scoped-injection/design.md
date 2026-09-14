## Context

See proposal.md — Why. Current mechanics:

- `TJOR_BROKER_HOSTS` is a comma list of host globs; the addon matches with `tjor_identity.should_inject` → `tjor_policy.host_matches` (host only). `flow.request.port` is available at both injection call sites but unused.
- The kube source sets the list to the bare API hostname (`tjor_kube.api_host`), whose docstring even documents "port-agnostic" — the gap under review.
- The same `TJOR_BROKER_HOSTS` value now also reaches the agent entrypoint (#47) for the GitHub-coverage decision, and the config hash (recreate-on-change) already includes it.

## Goals / Non-Goals

**Goals:**
- Exact-origin injection for the kube source by default; opt-in port scoping for any source.
- One parser + matcher (in `tjor_identity`, next to the host matcher) used by proxy and entrypoint — no second implementation.
- Zero behavior change for existing port-less configs.

**Non-Goals:**
- Scheme matching: everything the proxy intercepts is proxied HTTP(S); host+port is the origin identity that matters at this layer.
- Port scoping for identity `inject_hosts` (x-agent headers carry no secret material comparable to a bearer token; unchanged).
- Changing the egress policy's host model (`tjor policy add` stays hostname-level).

## Decisions

1. **Entry syntax `host[:port]`, parsed by `tjor_identity.parse_broker_hosts` → `(glob, port|None)` pairs; matched by `broker_covers(pairs, host, port)`.** Host component delegates to `tjor_policy.host_matches`; the port check is plain equality. A port-less entry matches any port — pat/github-app configs (`github.com`, `*.github.com`) keep working unchanged. Alternative — a separate `TJOR_BROKER_PORT` variable — rejected: it can't express per-entry scope and adds a second source of truth.
2. **IPv6 literals are bracketed when scoped** (`[2001:db8::1]:6443`); the parser treats a `:port` suffix as scope only when the prefix is bracketed or colon-free, so a bare IPv6 entry is never mis-split.
3. **`tjor_kube.api_origin(server)` composes the kube entry** — hostname (lowercased by urlparse), explicit port or https default 443, brackets for IPv6 — as a pure, unit-tested helper with a CLI verb (`origin`), same pattern as `api_host`. The launcher uses `api_origin` for `TJOR_BROKER_HOSTS`, and keeps `api_host` for the `tjor policy add` hint and the `TJOR_KUBE_API_HOST` SSRF exemption: policy and reachability are hostname-level questions; only the credential is origin-level.
4. **Entrypoint coverage asks port-aware** (`broker_covers(pairs, "github.com", 443) or (…gist…, 443)`): a broker scoped to `github.com:8443` would never have its credential injected on git's 443 traffic, so wiring the placeholder there would break git — the gh fallback is correct.

## Risks / Trade-offs

- [A kube API behind a port-rewriting proxy/LB could present a different port than the kubeconfig's] → the kubeconfig's server URL is exactly what the caged kubectl dials (placeholder kubeconfig is rendered from the same URL), so the request port always equals the configured origin's port.
- [Existing kube users' sessions change scope from any-port to one port] → that is the fix; the reachable surface (egress policy) is unchanged, only credential attachment narrows.
- [Entry with a bogus port (e.g. `host:99999`)] → parser only accepts 1–5 digit ports and leaves other strings as plain host globs (which then simply never match a real hostname containing `:`), failing toward non-injection — the safe direction.

## Migration Plan

Proxy sidecar picks the change up on recreation (config hash includes `TJOR_BROKER_HOSTS`, which changes shape for kube sessions). Agent image rebuild required for the entrypoint's port-aware coverage call. Rollback: revert the commit; port-less entries are forward/backward compatible.

## Open Questions

None.
