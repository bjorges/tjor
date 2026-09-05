# Design: add-kube-broker

## Context

The D2 broker holds a secret only in the proxy sidecar and injects it toward configured hosts; the `pat` source is a static token injected as `Authorization`. Kubernetes uses the same shape — a bearer token toward the API server — so a kube token reuses the entire injection path. The one twist: minting a ServiceAccount token needs cluster auth (a kubeconfig, possibly with exec plugins / client certs), which lives on the host, not in the proxy.

## Goals / Non-Goals

**Goals:** per-session short-TTL SA token; RBAC as the cluster-enforced action policy; the token never in the sandbox; kubectl usable in-cage.

**Non-Goals:** proxy-side verb filtering (follow-up), in-proxy token refresh, non-kubectl clients, managing RBAC for the user (they bind the SA to a Role).

## Decisions

- **Mint host-side with kubectl, inject like a pat.** The proxy can't run kubectl (no kubeconfig, no exec plugins). So the launcher mints — `kubectl create token <sa> -n <ns> --duration <ttl>` — which delegates all cluster-auth complexity to the user's working kubectl, then hands the resulting short-TTL token to the proxy as a `pat`-shaped credential toward the API server host. Zero new proxy code; reuses the D2-tested injection and its conformance probes. *Alternative:* implement TokenRequest over the API in python — rejected: reimplementing kubeconfig auth (exec plugins, client certs, OIDC) is a large, fragile surface kubectl already solves.
- **RBAC is the policy.** The user points the source at a ServiceAccount bound to whatever Role fits the session (read-only for debugging, namespaced for a scoped task). tjor does not filter verbs; the cluster does, by construction. Documented as the primary control; proxy verb filtering is an optional future ring.
- **API host derived from kubeconfig; must be allowlisted.** The launcher derives the server host via `kubectl config view --minify` and uses it as the broker's inject host; the user must allow it in the egress policy (a `kube` profile / `tjor policy add`). Injection is scoped to exactly that host.
- **In-cage kubeconfig with a placeholder token.** When the kube broker is active, the entrypoint writes `~/.kube/config` pointing at the API server with a placeholder bearer token, so `kubectl` sends `Authorization: Bearer <placeholder>` and the proxy overwrites it with the real SA token. `NODE_EXTRA_CA_CERTS`/the session CA already make kubectl trust the proxy's TLS.
- **Short TTL, no refresh.** The token lasts its `--duration`; a session outliving it re-launches (the launcher re-mints). This mirrors the App-token backstop philosophy — short-lived by design; expiry means re-auth, not silent long-lived access.

## Risks / Trade-offs

- **`kubectl create token` requires the user's identity to have `create` on the SA's `serviceaccounts/token` subresource** — standard for a cluster admin/operator; documented. If it fails, the broker is disabled (fail-closed, no injection), loudly.
- **No refresh** means a session longer than the token TTL loses cluster auth mid-run — documented; pick a `duration` matching the work, or re-launch.
- **The API server's TLS is MITM'd by the proxy** like all egress; kubectl trusts the session CA (already installed). Cluster client-cert *auth* is not used (we use bearer tokens), so MITM doesn't break auth.
- **The SA's RBAC is the whole action policy, so scoping it is the operator's responsibility.** tjor mints a token for whatever ServiceAccount `kube_sa` names and does not (and cannot) narrow its permissions — an SA bound to `cluster-admin` gives the caged session cluster-admin. The security property ("read-only by construction", "namespaced by construction") holds only to the extent the operator bound the SA to a suitably narrow Role. Bind the least-privilege Role the session needs; treat a broad binding as equivalent to handing the agent that access.

## Verification approach

Unit tests for: the token-mint command construction and output parsing, the API-host derivation, and the placeholder-kubeconfig generation. The proxy injection itself is the D2 `pat` path, already covered by the broker conformance probes (real token injected toward the destination, placeholder overwritten, no leak elsewhere) — so a kube token behaves identically and needs no new proxy test. A real-cluster end-to-end (mint → `kubectl get` → RBAC denies a write) is documented as a manual check; CI has no cluster.
