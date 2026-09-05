## Purpose

Per-session identity: processes inside the cage know which session they are, and egress traffic can carry that identity — verified and impossible to forge across sessions — via the vendor-neutral `x-agent-*` header schema.

## ADDED Requirements

### Requirement: Identity environment inside the cage

Every agent container SHALL receive the session's identity as environment variables: `TJOR_SESSION_ID`, `TJOR_HARNESS`, `TJOR_REPO`, `TJOR_WORKTREE` (when applicable), `TJOR_TASK_ID` (when supplied at launch), and `TJOR_PARENT_SESSION` (when spawned on behalf of another session).

#### Scenario: Identity visible to tools
- **WHEN** a process in the agent container reads its environment
- **THEN** the identity variables are present and consistent with the launcher's session metadata

### Requirement: Forged identity headers are stripped

The egress proxy SHALL remove any outbound `x-agent-*` header whose value does not exactly match the session's registered identity, before the request leaves the cage.

#### Scenario: Cross-session impersonation attempt
- **WHEN** a request carries `x-agent-session-id` (or any `x-agent-*` header) with a value other than this session's registered identity
- **THEN** that header is removed and the event is logged

#### Scenario: Legitimate self-identification passes
- **WHEN** a request carries `x-agent-*` headers matching the session's registered identity
- **THEN** the headers pass through unmodified

### Requirement: Injection only on configured hosts

When `identity.inject_hosts` is configured, the proxy SHALL add the session's `x-agent-*` headers to intercepted requests whose host matches an entry. Requests to any other host SHALL NOT gain identity headers.

#### Scenario: LLM endpoint attribution
- **WHEN** an intercepted request targets a host matching `identity.inject_hosts`
- **THEN** the upstream-bound request contains the session's `x-agent-*` headers

#### Scenario: No identity leakage elsewhere
- **WHEN** a request targets a host not in `identity.inject_hosts`
- **THEN** no `x-agent-*` header is added

### Requirement: Identity handling fails closed

If the proxy has no (or malformed) registered identity for the session, every `x-agent-*` header SHALL be stripped from every outbound request, and the condition SHALL be reported loudly.

#### Scenario: Missing identity registration
- **WHEN** the proxy starts without valid identity configuration
- **THEN** all outbound `x-agent-*` headers are removed and the operator is warned

### Requirement: Identity is session-scoped

Identity values SHALL be unique per session and never shared between concurrently running sessions (charter L29); the session id is the launcher-derived id used for container naming and state roots.

#### Scenario: Two concurrent sessions
- **WHEN** two sessions run at the same time
- **THEN** their identity sets differ in `TJOR_SESSION_ID` and each proxy only accepts its own session's values
