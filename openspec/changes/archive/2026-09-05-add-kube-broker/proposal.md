# Proposal: add-kube-broker

## Why

Running an agent against a Kubernetes cluster is exactly what tjor's structural model is good at — and it's what the original `k8s-debug` profile was for. The safe answer to "controlled cluster access" isn't gating which tools the agent may call; it's giving the session a **per-session, short-TTL ServiceAccount token whose RBAC is the action policy**. A read-only Role is read-only *by construction, cluster-enforced* — the agent physically cannot mutate, no matter what it's prompted to do. This generalizes the shipped D2 broker to a third credential source.

## What Changes

- A **`kube` broker source**: at launch the host-side broker mints a short-TTL ServiceAccount token via `kubectl create token <sa> -n <ns> --duration <ttl>` (reusing the user's kubeconfig for auth to the cluster), and the proxy injects that token into requests to the cluster's API server — the agent holds only a placeholder, exactly like the GitHub credential (D2). RBAC on the ServiceAccount is the policy: scope the SA to a read-only Role and the session is read-only, enforced by the cluster.
- **kubectl in the agent image** (pinned, checksum-gated), so a caged session can actually use the cluster.
- When the kube broker is active, the entrypoint writes a minimal in-cage kubeconfig pointing at the API server with a **placeholder** bearer token — kubectl authenticates through the proxy, which swaps in the real SA token toward the API host only.
- The API server host is derived from the kubeconfig and must be on the egress allow-list (a `kube` profile / `tjor policy add` covers it).

Out of scope: proxy-side kube **verb** filtering (block `exec`/`delete` — a defense-in-depth follow-up; RBAC is the primary control), in-proxy token refresh (the SA token lasts its TTL; re-launch to refresh, as with the App-token backstop), and non-kubectl cluster clients.

## Capabilities

### Modified Capabilities

- `credential-broker`: adds the `kube` source (short-TTL ServiceAccount token minted host-side via kubectl, injected toward the API server; RBAC is the action policy).
- `cage-image`: the agent image includes a pinned kubectl.

## Impact

- Code: broker config (`kube` source + SA/namespace/duration/api-host), launcher mint (`kubectl create token`, derive API host, write placeholder kubeconfig via the entrypoint), agent Dockerfile (pinned kubectl), docs (the RBAC-as-policy model, a `kube` profile snippet). Unit tests for the mint/derive/kubeconfig logic; the proxy injection reuses the D2 path (already conformance-tested). Real-cluster end-to-end is documented as a manual check (CI has no cluster).
- No breaking changes: `source` defaults to empty (disabled).
