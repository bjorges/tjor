## ADDED Requirements

### Requirement: Optional LiteLLM gateway on the egress network

tjor SHALL support an optional LiteLLM gateway sidecar, enabled by
`[gateway] enabled = true` (default false). The gateway SHALL run on the egress
network only — never the internal agent network — so a caged session reaches it
solely through the proxy, and the egress policy SHALL gain exactly one host (the
gateway) rather than one host per model provider. When disabled, a session
SHALL behave exactly as if the feature did not exist.

#### Scenario: Gateway is not on the agent network
- **WHEN** the gateway is enabled
- **THEN** the LiteLLM container is attached to the egress network and not to the internal network, and the only agent-reachable route to it is the proxy

#### Scenario: Disabled by default
- **WHEN** `[gateway]` is absent or `enabled = false`
- **THEN** no gateway sidecar starts and the session's egress policy is unchanged

### Requirement: Gateway admin surface unreachable from the agent by construction

The gateway's management/admin endpoints SHALL be unreachable from the agent by
construction — the proxy (the agent's only route to the gateway) SHALL allow
only inference paths toward the gateway host and deny all management paths — not
by a password or an in-gateway auth check alone (charter L30).

#### Scenario: Inference allowed, management denied
- **WHEN** a caged request targets the gateway host at an inference path (e.g. `/v1/chat/completions`)
- **THEN** the proxy allows it
- **WHEN** a caged request targets the gateway host at a management path (e.g. `/key/generate`, `/ui`)
- **THEN** the proxy denies it (HTTP 403), regardless of any credential the agent presents

### Requirement: Generated gateway credential never enters the agent

The gateway's master key SHALL be generated per install with a CSPRNG and SHALL
never be present in the agent container (environment, filesystem, or process
memory), in any container label, or in any config hash. Inference from the agent
SHALL authenticate by the proxy injecting that key toward the gateway host; the
agent SHALL hold only a placeholder.

#### Scenario: Master key absent from the sandbox
- **WHEN** the gateway is enabled and a session is running
- **THEN** the generated master key value is present nowhere in the agent container, and nowhere in the session's labels or config hash

#### Scenario: Inference authenticated without the agent holding the key
- **WHEN** the agent sends an inference request with its placeholder key toward the gateway host
- **THEN** the proxy overwrites the Authorization with the real master key toward the gateway host only, and no other host receives it

### Requirement: Gateway host is exempt from the SSRF IP guard

The proxy's resolved-address guard (which denies an allow-listed host resolving
to a non-global address) SHALL exempt exactly the configured gateway host, so
the intended internal gateway is reachable while the guard still protects every
other host. The exemption SHALL apply only when the gateway is enabled and only
to the configured host.

#### Scenario: Gateway reachable, other private-resolving hosts still blocked
- **WHEN** the gateway host resolves to a private docker IP
- **THEN** the proxy permits it (gateway exemption)
- **WHEN** any other allow-listed host resolves to a private/non-global IP
- **THEN** the proxy still denies it
