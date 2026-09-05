## ADDED Requirements

### Requirement: Agent containers carry discovery labels

Every agent container the launcher starts SHALL carry labels identifying the session (session id, workspace path, harness, task id when set, launch timestamp) so lifecycle tooling never parses container names.

#### Scenario: Labels present on a running agent
- **WHEN** a session is launched
- **THEN** its agent container carries the tjor session labels with the launcher's values

### Requirement: Agents launch detached and persist independently of the launching client

The launcher SHALL start the agent container detached so it outlives the launching terminal, then attach to it (unless `--detach` is given, which returns immediately after start). A dropped or killed attach client SHALL NOT stop or remove the agent container; container removal is only via `tjor down` or `tjor gc`. Passing a one-shot command still runs it to completion and propagates its exit code.

#### Scenario: Dropped terminal leaves a reattachable session
- **WHEN** the client attached to a running agent is killed
- **THEN** the agent container keeps running and `tjor attach` can reconnect to it

#### Scenario: Detached launch
- **WHEN** `tjor run --detach` is used
- **THEN** the launcher starts the session and returns without attaching, naming the session to attach to later

### Requirement: Named session derivation

When `--session <name>` is given (name matching `[A-Za-z0-9._-]{1,32}`), the session id SHALL be derived from both the workspace and the name; without it, derivation is unchanged (repo-scoped default session).

#### Scenario: Same repo, different names
- **WHEN** sessions `a` and `b` are launched from the same repo
- **THEN** their session ids differ and neither collides with the repo's default session
