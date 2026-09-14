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

The proxy SHALL inject a brokered credential only on intercepted requests whose host matches that credential's configured destination host(s). A destination entry MAY additionally scope to a single port (`host:port`); a port-scoped entry SHALL match only requests to exactly that port, while an entry without a port matches any port (unchanged behavior). A request to any other allowed host — or to a scoped destination's host on a different port — SHALL NOT carry the credential. Destination matching SHALL use the shared policy host matcher for the host component; scope is re-evaluated per request, so redirects or authority changes never extend it.

#### Scenario: Credential does not leak to an unrelated allowed host
- **WHEN** the agent makes a request to an allowlisted host that is not the credential's destination
- **THEN** the request carries no brokered credential

#### Scenario: Port-scoped destination does not leak across ports
- **WHEN** a destination entry is scoped to a port and the agent requests the same hostname on a different port
- **THEN** the request carries no brokered credential

### Requirement: Placeholder wiring is scoped to brokered destinations

The cage SHALL wire the placeholder GitHub git-credential helper only when the broker's configured destination hosts cover GitHub (`github.com` or `gist.github.com`), matched with the shared policy host matcher — never a second matcher implementation. When an enabled broker does not cover GitHub (e.g. a kube-only session), the session SHALL keep the same ambient GitHub auth path as a broker-less session (the `gh` fallback helper), so an intentional no-GitHub-credential posture behaves like one instead of presenting as broken git authentication.

#### Scenario: Kube-only broker leaves GitHub auth ambient
- **WHEN** a session runs with `[broker] source = "kube"` (injection scoped to the cluster API host only)
- **THEN** the GitHub credential helper is the same `gh` fallback as in a broker-less session, and git never sends a placeholder credential to github.com

#### Scenario: GitHub-covering broker still gets the placeholder
- **WHEN** a session runs with a broker whose hosts cover github.com
- **THEN** the placeholder helper is wired (and the proxy substitutes the real credential), unchanged from before

#### Scenario: Coverage respects host globs
- **WHEN** the broker hosts contain a glob that matches github.com (e.g. via the shared matcher's semantics)
- **THEN** the placeholder helper is wired, identically to how the proxy scopes injection

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

The minted token SHALL be short-lived (a configured duration). The proxy SHALL inject it only toward the cluster API server's exact origin — the configured host AND port (https default 443 when the server URL names none) — never toward any other allowed host, and never toward the same hostname on a different port.

#### Scenario: Token not leaked to a non-cluster host
- **WHEN** the agent makes a request to an allowlisted host that is not the cluster API server
- **THEN** the request carries no kube SA token

#### Scenario: Token not leaked to an alternate port on the API hostname
- **WHEN** the agent requests the API server's hostname on a port other than the API server's
- **THEN** the request carries no kube SA token

### Requirement: Kube API host is exempt from the SSRF IP guard

The proxy's resolved-address guard (which denies an allow-listed host resolving to a non-global address) SHALL exempt exactly the kube broker's configured API server host, so a private-endpoint cluster is reachable while the guard still protects every other host. The exemption SHALL apply only while the kube broker is active and only to that host; no global `ip_guard` opt-out is required to use a privately-resolving cluster.

#### Scenario: Private cluster reachable, other private-resolving hosts still blocked
- **WHEN** the kube API host resolves to a private address during a kube-broker session
- **THEN** the proxy permits it (kube exemption)
- **WHEN** any other allow-listed host resolves to a private/non-global address
- **THEN** the proxy still denies it

#### Scenario: No exemption without an active kube broker
- **WHEN** no kube broker is configured
- **THEN** a host resolving to a private address is denied by the guard as before, even if it matches a cluster-like name
