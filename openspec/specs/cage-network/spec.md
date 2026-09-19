# cage-network Specification

## Purpose
The structural network boundary of the cage: what the agent container can and cannot reach, by construction rather than by configuration the agent could influence.

## Requirements

### Requirement: Agent container has no direct egress

The agent container SHALL be attached only to an internal-only network. All outbound traffic SHALL be possible only via the egress proxy on that network.

#### Scenario: Direct connection attempt bypassing the proxy
- **WHEN** a process in the agent container attempts a direct TCP connection to an external address (ignoring proxy environment variables)
- **THEN** the connection fails — no route exists off the internal network

#### Scenario: Proxy-mediated allowed request
- **WHEN** a process requests an allowlisted URL via the configured explicit proxy
- **THEN** the request succeeds

### Requirement: DNS resolves only what policy permits

A DNS sidecar on the internal network SHALL serve the agent container. It SHALL forward only zones derived from (or explicitly configured consistent with) the egress allow-policy; every other zone SHALL be answered locally with NXDOMAIN, never forwarded upstream.

#### Scenario: Allowlisted host resolution
- **WHEN** the agent resolves a hostname within a permitted zone
- **THEN** resolution succeeds

#### Scenario: Unlisted zone (DNS exfiltration attempt)
- **WHEN** the agent queries any name in a zone the policy does not permit, including names with data-bearing labels
- **THEN** the sidecar answers NXDOMAIN locally and no query leaves the cage

### Requirement: Egress proxy is dual-homed and created in the correct order

The egress proxy SHALL have one interface on the internal network and one on a routable network. It SHALL be created on the routable network first and connected to the internal network second, so published ports and route-derived addresses bind correctly.

#### Scenario: Proxy reaches the internet while agent cannot
- **WHEN** the topology is up
- **THEN** the proxy can complete external requests and the agent container cannot, except through the proxy

### Requirement: Egress connects only to validated addresses (resolve-and-pin)

When the resolved-address guard is active, the proxy SHALL resolve an allowed hostname, validate the resolved addresses, and pin the upstream connection to a validated address, so that the address connected to is provably an address that passed validation. A change in DNS answers between validation and connection SHALL NOT be able to redirect the connection to an address the guard never judged. A hostname whose addresses fail validation at connection time SHALL have the connection refused and the denial recorded in the session denial log. TLS server-name verification SHALL continue to be performed against the hostname, never against the pinned address. The guard's config-scoped exemptions (the gateway host and the kube API host) and guard-off mode SHALL connect without pinning, preserving live container DNS; a hostname unresolvable at connection time SHALL proceed unpinned so that the connection fails on its own resolution and nothing flows.

#### Scenario: A rebinding flip between check and connect cannot redirect
- **WHEN** an allowed hostname validates as public and a subsequent resolution of the same name returns a private, loopback, or link-local address
- **THEN** the upstream connection is made to the validated public address, or refused — never to the unvalidated address

#### Scenario: Failing validation at connect time refuses the connection
- **WHEN** the addresses resolved at connection time include a non-global address (and the host is not exempt)
- **THEN** the connection is killed and the denial is recorded with the guard's reason

#### Scenario: Exempt hosts and guard-off keep live DNS
- **WHEN** the destination is the configured gateway or kube API host, or the guard is disabled via configuration
- **THEN** the connection proceeds without pinning, exactly as before

#### Scenario: TLS verification still uses the hostname
- **WHEN** a pinned HTTPS connection is established
- **THEN** the upstream certificate is verified against the destination hostname, not the pinned IP address

### Requirement: Address resolution is time-bounded and fails closed

The resolved-address guard SHALL bound the time spent resolving any single hostname, so that a slow or hung DNS answer cannot stall the proxy's request handling. This bound SHALL be enforced at the resolver layer as well as in the guard, so that a hung or black-holed lookup returns within a bounded, configured wall time (not the operating system's default), and the worker performing it is freed within that bound — resolution capacity therefore recovers on its own, without restarting the proxy. It SHALL also remain available under concurrent slow resolutions: resolutions for one host SHALL NOT exhaust the guard's resolution capacity for other hosts. To that end, at most one resolution per host SHALL be in flight at a time (concurrent requests for the same host share it), the number of concurrent distinct resolutions SHALL be bounded, and a request that cannot be resolved within the bound (either it exceeds the time bound or capacity is saturated) SHALL be treated as a guard failure — the request denied and, at connection time, the connection refused — never allowed through unresolved. When resolution capacity is saturated, the proxy SHALL surface an operator-facing signal (rate-limited) so a sustained many-host condition is observable rather than silent. A resolution that exceeds the time bound SHALL be briefly negative-cached so repeated requests to a slow host do not keep consuming capacity; that negative cache SHALL expire so the host is re-evaluated once resolution recovers. A fast resolution failure (a host that does not resolve) SHALL retain its existing behavior (the request is permitted because no connection can result); only exceeding the time bound or saturating capacity is treated as a failure.

#### Scenario: A hung DNS answer does not stall the guard
- **WHEN** an allowed hostname's resolution hangs past the guard's time bound
- **THEN** the guard returns a decision within that bound rather than blocking, and the request is denied / the connection refused (fail-closed)

#### Scenario: The resolver's own timeout is bounded so a worker recovers
- **WHEN** a lookup is black-holed (a nameserver accepts the query but never answers)
- **THEN** the proxy's resolver gives up within the configured bound rather than the OS default, freeing the worker so resolution capacity recovers without a proxy restart

#### Scenario: Capacity saturation is observable
- **WHEN** the resolver's concurrent-distinct-resolution capacity is saturated and a request is denied for that reason
- **THEN** the proxy emits a rate-limited operator-facing signal recording the saturation

#### Scenario: One slow host does not exhaust capacity for others
- **WHEN** many concurrent requests target a single slow-resolving host
- **THEN** they share a single in-flight resolution, and resolution capacity remains for other hosts (a different, fast-resolving host is still evaluated)

#### Scenario: A transient resolution stall is not cached
- **WHEN** a host's resolution exceeds the bound and later resolutions of the same host would succeed
- **THEN** requests within the short negative-cache window are denied without re-consuming capacity, and once the window expires the host is re-evaluated on a fresh resolution (a transient stall never poisons the host permanently)

#### Scenario: A fast unresolvable host is unaffected
- **WHEN** a hostname fails to resolve quickly (e.g. NXDOMAIN)
- **THEN** the guard keeps its existing behavior (permitted, since no connection can result), not treated as a timeout failure

### Requirement: Guard denials do not disclose resolved addresses to the agent

When the resolved-address guard denies a request, the reason returned to the agent (the proxy's denial response body and headers) SHALL NOT contain the specific resolved address the guard judged, nor other request-specific literals the guard echoes; it SHALL carry only a generic reason for the denial class. The operator-facing denial log SHALL retain the full detail, including the specific address, so operator diagnostics are unchanged. Denial reasons that already carry no such literal (policy blocks, default-deny, resolution timeout, exemptions) SHALL be shown to the agent unchanged.

#### Scenario: Agent-facing non-global denial omits the address
- **WHEN** the guard denies a request because the host resolved to a non-global address
- **THEN** the response the agent receives states the denial class (a non-global address) without the specific address literal
- **AND** the operator denial log still records the specific resolved address

#### Scenario: Literal-free reasons are unchanged
- **WHEN** a denial reason carries no request-specific literal (e.g. a policy block, default-deny, or resolution timeout)
- **THEN** the agent-facing reason is unchanged

### Requirement: Sidecar admin surfaces are unreachable from the agent network

Any management/admin API of any sidecar (proxy web UI, future gateway admin endpoint) SHALL be unreachable from the agent network by construction. Admin credentials, where they exist, SHALL be generated per-install, never checked in, never printed to stdout, and never embedded in Docker labels or config-hash values.

#### Scenario: Agent probes sidecar admin ports
- **WHEN** a process in the agent container scans all sidecar addresses/ports reachable from the internal network
- **THEN** no admin/management endpoint responds

### Requirement: Sidecar configuration cannot drift silently

Sidecars SHALL be stamped with a hash of their effective configuration and SHALL be recreated when the hash differs from the running instance.

#### Scenario: Config edited while sidecar runs
- **WHEN** the operator changes egress policy and relaunches
- **THEN** the sidecar is recreated with the new policy; the old policy is provably no longer in effect
