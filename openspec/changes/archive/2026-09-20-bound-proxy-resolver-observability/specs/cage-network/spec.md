# Spec Delta

## MODIFIED Requirements

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
