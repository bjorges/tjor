# Spec Delta

## ADDED Requirements

### Requirement: Explicit kube API host override must match the active cluster

When `kube_api_host` is explicitly configured for the `kube` broker source, the launcher SHALL validate at session launch — before any token is minted — that the override and the currently-active kubectl context's API server name the same server, compared in one canonical representation (scheme, host, and effective port, with unschemed values assumed https and missing ports taking the scheme default). On mismatch, or when the active context's server cannot be read so the override cannot be validated, the session SHALL start with the broker disabled and SHALL report why — naming both server identities on mismatch — and SHALL NOT mint a token. The minted token's cluster and the proxy's injection/allowlist scope MUST never silently refer to two different clusters. With the override unset, behavior is unchanged: the server is derived from the active context.

#### Scenario: Mismatched override disables the broker before minting
- **WHEN** `kube_api_host` names a server that differs canonically from the active kubectl context's server
- **THEN** the launch reports the mismatch, naming both the configured override and the active context's server
- **AND** the broker is disabled (the session starts with no injected credential) and no token is minted

#### Scenario: Equivalent spellings validate as the same server
- **WHEN** `kube_api_host` is a bare `host:port` (assumed https) and the active context's server is the same host and port spelled as a full `https://` URL
- **THEN** validation passes and the broker behaves exactly as before — token minted, injection scoped to that exact origin

#### Scenario: Override set but active context unreadable fails closed
- **WHEN** `kube_api_host` is set but the active context's server cannot be read from the kubeconfig
- **THEN** the launch reports that the override cannot be validated, the broker is disabled, and no token is minted

#### Scenario: Unset override keeps existing behavior
- **WHEN** `kube_api_host` is empty
- **THEN** the API server is derived from the active context as before, with no validation warning
