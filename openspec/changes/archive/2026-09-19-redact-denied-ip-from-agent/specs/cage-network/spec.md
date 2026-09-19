# Spec Delta

## ADDED Requirements

### Requirement: Guard denials do not disclose resolved addresses to the agent

When the resolved-address guard denies a request, the reason returned to the agent (the proxy's denial response body and headers) SHALL NOT contain the specific resolved address the guard judged, nor other request-specific literals the guard echoes; it SHALL carry only a generic reason for the denial class. The operator-facing denial log SHALL retain the full detail, including the specific address, so operator diagnostics are unchanged. Denial reasons that already carry no such literal (policy blocks, default-deny, resolution timeout, exemptions) SHALL be shown to the agent unchanged.

#### Scenario: Agent-facing non-global denial omits the address
- **WHEN** the guard denies a request because the host resolved to a non-global address
- **THEN** the response the agent receives states the denial class (a non-global address) without the specific address literal
- **AND** the operator denial log still records the specific resolved address

#### Scenario: Literal-free reasons are unchanged
- **WHEN** a denial reason carries no request-specific literal (e.g. a policy block, default-deny, or resolution timeout)
- **THEN** the agent-facing reason is unchanged
