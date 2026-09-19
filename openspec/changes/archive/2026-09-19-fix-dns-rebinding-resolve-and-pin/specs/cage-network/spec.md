# Spec Delta

## ADDED Requirements

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
