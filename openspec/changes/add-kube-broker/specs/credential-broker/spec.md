## ADDED Requirements

### Requirement: Kubernetes ServiceAccount broker source

The broker SHALL support a `kube` source that, at session launch, mints a short-TTL Kubernetes ServiceAccount token (via the cluster's TokenRequest API, using the user's kubeconfig for auth) scoped to a configured ServiceAccount, and the proxy SHALL inject that token as the bearer credential toward the cluster's API server host only. The agent SHALL hold only a placeholder; the real SA token never enters the agent's filesystem, environment, or process memory.

#### Scenario: Caged kubectl authenticates without holding the token
- **WHEN** the kube broker is active and a caged session runs `kubectl get pods`
- **THEN** the request to the API server is authenticated by the injected SA token, and no SA token value is present anywhere in the agent container

#### Scenario: RBAC is the action policy
- **WHEN** the configured ServiceAccount is bound to a read-only Role
- **THEN** a mutating request (e.g. `kubectl delete`) is rejected by the cluster (RBAC), regardless of what the agent attempts — the boundary is cluster-enforced, not prompt-enforced

### Requirement: Kube token is short-lived; injection is scoped to the API server

The minted token SHALL be short-lived (a configured duration). The proxy SHALL inject it only toward the configured API server host(s), never toward any other allowed host.

#### Scenario: Token not leaked to a non-cluster host
- **WHEN** the agent makes a request to an allowlisted host that is not the cluster API server
- **THEN** the request carries no kube SA token
