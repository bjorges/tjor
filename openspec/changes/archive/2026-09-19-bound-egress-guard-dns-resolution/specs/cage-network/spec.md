# Spec Delta

## ADDED Requirements

### Requirement: Address resolution is time-bounded and fails closed

The resolved-address guard SHALL bound the time spent resolving any single hostname, so that a slow or hung DNS answer cannot stall the proxy's request handling. A resolution that exceeds the bound SHALL be treated as a guard failure — the request denied and, at connection time, the connection refused — never allowed through unresolved. A resolution that exceeds the bound SHALL NOT be cached, so a transient stall denies only the attempt that hit it and a subsequent request re-resolves. A fast resolution failure (a host that does not resolve) SHALL retain its existing behavior (the request is permitted because no connection can result); only exceeding the time bound is treated as a failure.

#### Scenario: A hung DNS answer does not stall the guard
- **WHEN** an allowed hostname's resolution hangs past the guard's time bound
- **THEN** the guard returns a decision within that bound rather than blocking, and the request is denied / the connection refused (fail-closed)

#### Scenario: A transient resolution stall is not cached
- **WHEN** one request's resolution exceeds the bound and a later request for the same host resolves normally
- **THEN** the later request is evaluated on its own fresh resolution, not denied by a cached timeout

#### Scenario: A fast unresolvable host is unaffected
- **WHEN** a hostname fails to resolve quickly (e.g. NXDOMAIN)
- **THEN** the guard keeps its existing behavior (permitted, since no connection can result), not treated as a timeout failure
