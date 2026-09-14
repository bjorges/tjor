## MODIFIED Requirements

### Requirement: Injection is scoped to the credential's destination

The proxy SHALL inject a brokered credential only on intercepted requests whose host matches that credential's configured destination host(s). A destination entry MAY additionally scope to a single port (`host:port`); a port-scoped entry SHALL match only requests to exactly that port, while an entry without a port matches any port (unchanged behavior). A request to any other allowed host — or to a scoped destination's host on a different port — SHALL NOT carry the credential. Destination matching SHALL use the shared policy host matcher for the host component; scope is re-evaluated per request, so redirects or authority changes never extend it.

#### Scenario: Credential does not leak to an unrelated allowed host
- **WHEN** the agent makes a request to an allowlisted host that is not the credential's destination
- **THEN** the request carries no brokered credential

#### Scenario: Port-scoped destination does not leak across ports
- **WHEN** a destination entry is scoped to a port and the agent requests the same hostname on a different port
- **THEN** the request carries no brokered credential

### Requirement: Kube token is short-lived; injection is scoped to the API server

The minted token SHALL be short-lived (a configured duration). The proxy SHALL inject it only toward the cluster API server's exact origin — the configured host AND port (https default 443 when the server URL names none) — never toward any other allowed host, and never toward the same hostname on a different port.

#### Scenario: Token not leaked to a non-cluster host
- **WHEN** the agent makes a request to an allowlisted host that is not the cluster API server
- **THEN** the request carries no kube SA token

#### Scenario: Token not leaked to an alternate port on the API hostname
- **WHEN** the agent requests the API server's hostname on a port other than the API server's
- **THEN** the request carries no kube SA token
