## ADDED Requirements

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
