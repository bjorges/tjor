# llm-gateway Specification

## Purpose
An optional LiteLLM sidecar on the egress network that gives the caged harness a single allow-listed inference host instead of one per provider: the agent reaches it only through the proxy, its admin surface is unreachable by construction, and the generated master key is injected at the proxy so it never enters the cage.

## Requirements

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

### Requirement: Session policy augmentation derives from the validated base policy

When the gateway is enabled, the session policy SHALL be generated from the base policy as parsed and validated by the one policy parser, re-emitting every section, the `methods` rules included. A base policy the parser rejects SHALL fail the launch with the parser's errors: no session policy is written, one left by an earlier launch into the same directory is removed, no agent starts, and the launcher says what that means for sidecars still running from an earlier launch.

#### Scenario: A malformed methods section fails the launch
- **WHEN** the gateway is enabled and the base policy has a `[[methods.restrict]]` rule with a misspelled key
- **THEN** the launch stops with the parser's error, and no session policy file exists in the session directory

#### Scenario: A reused session directory does not keep a stale policy
- **WHEN** the session directory holds a session policy from an earlier launch and the base policy is now rejected by the parser
- **THEN** the launch stops with the parser's error, the stale session policy is removed, no agent starts, and the output names the running-sidecar consequence

#### Scenario: Method rules survive augmentation
- **WHEN** the gateway is enabled and the base policy restricts a host to `GET` with a `POST` exception on one path
- **THEN** the session policy denies `POST` to that host with `method-block:POST`, admits the excepted path, and still carves the gateway's inference paths

#### Scenario: The generated policy is checked before it is written
- **WHEN** the augmentation serialises the parsed base policy, whose host or path patterns may hold a quote, a backslash or a control character
- **THEN** every string is emitted as a TOML basic string, the result is parsed by the same parser and compared rule for rule with the base plus the gateway additions, and a mismatch fails the launch with a message naming the augmentation, not a later "invalid policy"

#### Scenario: The launcher path is tested
- **WHEN** the launcher's topology step runs against a malformed base policy with the gateway enabled, in a fresh session directory and in one seeded with a stale session policy
- **THEN** the integration test sees a non-zero exit, the parser's error on stderr, and no session policy file in either case

### Requirement: Inference paths stay reachable under method restrictions

The augmentation SHALL add a `[[methods.except]]` rule for the gateway host admitting `POST` on each of the gateway's POST inference paths and `GET` on its model-listing and health paths, so a restrict rule that matches the gateway host (for example `host = "*"`, even with `allow = []`) cannot deny inference. The management surface SHALL stay denied by the host block regardless.

#### Scenario: A wildcard restriction does not break inference
- **WHEN** the base policy restricts `*` to `GET`, to `POST`, or to nothing (`allow = []`) and the gateway is enabled
- **THEN** every inference path toward the gateway host is allowed with the method it uses (`POST /v1/chat/completions`, `GET /v1/models`, `GET /health/readiness`) and `POST /key/generate` is denied with `host-block`
