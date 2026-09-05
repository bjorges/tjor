# credential-broker Specification

## Purpose
Per-session, short-TTL credentials that the sandbox can *use* but never *possess*: the real secret is injected at the egress-proxy boundary toward its configured destination host(s) only, never written into the agent's filesystem, environment, or process memory, and revoked at session teardown.

## Requirements

### Requirement: The real credential never enters the sandbox

When a broker is configured, the session's real credential SHALL NOT appear in the agent container's filesystem, environment variables, process memory, or any tool output. The agent SHALL authenticate to the credential's destination host(s) only because the proxy injects the secret on its behalf.

#### Scenario: Private clone with no token in the container
- **WHEN** a broker for GitHub is configured and the agent clones a private repository it is authorized for
- **THEN** the clone succeeds AND no token value is present anywhere in the container (filesystem, env, or process listing)

#### Scenario: Agent inspects its own git config for a secret
- **WHEN** the agent reads its git/gh credential configuration
- **THEN** it finds only a placeholder, never the real credential

### Requirement: Injection is scoped to the credential's destination

The proxy SHALL inject a brokered credential only on intercepted requests whose host matches that credential's configured destination host(s). A request to any other allowed host SHALL NOT carry the credential.

#### Scenario: Credential does not leak to an unrelated allowed host
- **WHEN** the agent makes a request to an allowlisted host that is not the credential's destination
- **THEN** the request carries no brokered credential

### Requirement: Credentials are short-lived and refreshed

A brokered credential SHALL have a bounded lifetime (for the GitHub App source, the installation token's ~1h TTL). The broker SHALL refresh it before expiry for the duration of the session, so a leaked-at-rest secret is useful only briefly.

#### Scenario: Long session outlives one token TTL
- **WHEN** a session runs longer than a single credential's TTL
- **THEN** the agent's authenticated requests keep succeeding because the broker refreshed the credential

### Requirement: Teardown revokes

When a session ends via `tjor down` or is reaped by `tjor gc`, the broker SHALL revoke or forget that session's credential so it cannot be reused afterward.

#### Scenario: Credential unusable after teardown
- **WHEN** a session is torn down
- **THEN** the broker no longer holds that session's credential and any cached copy is discarded

### Requirement: Fail-closed, never silent downgrade

With no broker configured, behavior SHALL be exactly the pre-broker default (in-session `gh auth login`). With a broker configured but unable to mint a credential, the session SHALL start with no injected credential and SHALL say so — it SHALL NOT silently fall back to a long-lived token.

#### Scenario: Broker cannot mint
- **WHEN** a broker is configured but minting fails (bad key, revoked app, network)
- **THEN** the session starts without an injected credential and the failure is reported; no long-lived credential is substituted

### Requirement: Scope is least-privilege

A brokered GitHub App credential SHALL be scoped to the repositories the session works on (installation/repository-scoped), not to the user's full account.

#### Scenario: Credential cannot reach an unrelated repo
- **WHEN** the agent attempts to use the brokered credential against a repository outside the session's scope
- **THEN** the upstream rejects it (the credential was never granted that scope)

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
