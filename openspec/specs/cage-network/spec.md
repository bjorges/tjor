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
