# Spec Delta

## ADDED Requirements

### Requirement: Multiple Kubernetes clusters reachable in one session

The kube broker SHALL support an explicit list of clusters (`[[broker.kube_clusters]]`), each entry naming its own kubectl context, ServiceAccount, namespace, token duration, and optional API-host pin. At session launch the broker SHALL mint a short-TTL token for each configured cluster against that entry's context, and the agent SHALL receive one kubeconfig containing a context per cluster, each carrying only a placeholder credential. The agent SHALL be able to switch between the configured clusters mid-session (e.g. `kubectl config use-context`) without restarting the session. When `kube_clusters` is absent, the single-cluster behavior is unchanged. There SHALL be no mechanism to add a cluster to an already-running session.

#### Scenario: Two configured clusters are both reachable after launch
- **WHEN** a session is launched with two `[[broker.kube_clusters]]` entries and the agent switches context and runs `kubectl get pods` against each
- **THEN** both requests are authenticated by that cluster's injected token, and no SA token value for either cluster is present anywhere in the agent container

#### Scenario: Client-side switching needs no restart
- **WHEN** the agent runs `kubectl config use-context` to move between two configured clusters during one session
- **THEN** the switch works without relaunching the session, because both clusters were provisioned at launch

#### Scenario: Single-cluster config is unchanged
- **WHEN** no `kube_clusters` list is configured (the flat `kube_sa`/`kube_namespace`/`kube_api_host` form)
- **THEN** the broker behaves exactly as the single-cluster broker did

### Requirement: Each cluster's token is injected only toward its own API origin

The proxy SHALL inject each configured cluster's token only on requests whose destination matches that cluster's exact API origin (host and effective port, #49). A request toward one cluster's API origin SHALL NOT carry any other configured cluster's token, and a request toward any non-cluster allowed host SHALL carry no cluster token. Two configured clusters that resolve to the same API origin SHALL be refused at launch (an origin cannot map to two tokens).

#### Scenario: Cross-cluster token isolation
- **WHEN** the agent requests cluster A's API origin
- **THEN** the request carries cluster A's token and never cluster B's

#### Scenario: No cluster token leaks to a non-cluster host
- **WHEN** the agent requests an allowlisted host that is not any configured cluster's API origin
- **THEN** the request carries no cluster token

#### Scenario: Ambiguous duplicate origin is refused
- **WHEN** two configured clusters resolve to the same API origin
- **THEN** the launch refuses the configuration and the broker is disabled (an origin cannot carry two different tokens)

### Requirement: Every configured cluster API host is guarded and pinned

The proxy's SSRF resolved-address guard SHALL exempt every configured cluster's API host (each a private-endpoint control plane may legitimately resolve to a non-global address), and the resolve-and-pin connection guard SHALL apply per configured cluster host exactly as for a single cluster. The exemptions SHALL apply only to the configured cluster hosts and only while the kube broker is active; every other allowed host is guarded and pinned as before.

#### Scenario: Each cluster's private endpoint is reachable, others still guarded
- **WHEN** two configured cluster API hosts resolve to private addresses during the session
- **THEN** the proxy permits both (per-cluster exemption)
- **WHEN** any other allow-listed host resolves to a private/non-global address
- **THEN** the proxy still denies it

#### Scenario: An exempt cluster host is not additionally pinned
- **WHEN** the destination is one of the configured cluster API hosts
- **THEN** the connection proceeds under the cluster exemption (unpinned, live DNS), while a non-exempt host is still resolve-and-pinned

### Requirement: Multi-cluster provisioning is fail-closed and per-cluster validated

Each configured cluster's optional `api_host` pin SHALL be validated against that cluster's context server before any token is minted (the single-cluster validation, applied per entry). If any configured cluster cannot be validated, cannot mint a token, or produces a duplicate/ambiguous API origin, the entire broker SHALL be disabled and the failure reported, naming the offending cluster — the session SHALL NOT start with a kubeconfig context that has no working credential, and SHALL NOT silently provision a subset of the configured clusters.

#### Scenario: One cluster fails to mint, the whole broker is disabled
- **WHEN** one of several configured clusters cannot mint a token (or its pin fails validation)
- **THEN** the launch reports which cluster failed and disables the broker entirely — no partial multi-cluster session and no injected credentials

#### Scenario: Per-cluster pin validation
- **WHEN** a cluster entry sets `api_host` and it does not match that entry's context server
- **THEN** the launch reports the mismatch for that cluster and disables the broker before minting any cluster's token
