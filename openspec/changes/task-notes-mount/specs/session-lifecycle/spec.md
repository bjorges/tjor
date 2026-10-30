# Spec Delta

## MODIFIED Requirements

### Requirement: Reattachment

`tjor attach [session]` SHALL reattach the terminal to a running agent container, accepting either the fully-qualified session id or the short session name (resolved against the current workspace), or `--task <id>` to select the running agent carrying that task label. With no argument and exactly one running session, it attaches to it; with several candidates it SHALL offer an interactive picker; with none it SHALL say so and exit non-zero.

#### Scenario: Reattach after a dropped terminal
- **WHEN** an agent container is running and `tjor attach` is invoked with its session id
- **THEN** the terminal is attached to that agent's TTY

#### Scenario: Reattach by short name
- **WHEN** a named session is running and `tjor attach <short-name>` is invoked from its workspace
- **THEN** the short name resolves to the same session as its fully-qualified id and the attach proceeds

#### Scenario: Reattach by task
- **WHEN** two sessions run for tasks A and B and `tjor attach --task B` is invoked
- **THEN** the terminal is attached to the agent whose task label is B; with no such agent the command says so and exits non-zero

### Requirement: Session references resolve unambiguously

Lifecycle commands taking `--session` (`down`, `status`, `denials`, `reset`) SHALL accept both the short session name and the fully-qualified session id, resolving them to the same session, and SHALL accept `--task <id>` when `task.session_per_task` is enabled, resolving to the per-task session the launch derived. Resolution SHALL be idempotent: a value already carrying the current workspace's qualification prefix SHALL never be qualified again (no doubled ids, ever). A fully-qualified id belonging to another workspace SHALL be honored verbatim when a session with that exact id exists (state directory or labeled containers), making lifecycle commands usable from any working directory; the resolution SHALL state that a fully-qualified id is being used. A value that merely looks like a fully-qualified id but matches no existing session SHALL be treated as a short name, with a notice. Error and hint messages that display a session reference alongside a command SHALL only show invocations that are safe to paste verbatim.

#### Scenario: Pasting the displayed qualified id tears down the right session
- **WHEN** `tjor down --session <qualified-id>` is run with the exact id tjor's own messages displayed, from the launch workspace
- **THEN** that session — not a doubled phantom — is torn down

#### Scenario: Teardown from a different working directory
- **WHEN** `tjor down --session <qualified-id>` is run from a directory other than the session's workspace and a session with that id exists
- **THEN** the named session is torn down, with a notice that a fully-qualified id was used

#### Scenario: Qualified-looking short name still works
- **WHEN** `--session` receives a value shaped like a qualified id but no session with that exact id exists
- **THEN** the value is treated as a short name (with a notice) and resolution proceeds as for any short name

#### Scenario: Teardown that matches nothing says so
- **WHEN** `tjor down` resolves to a session with no containers and no state directory
- **THEN** the command reports that nothing was found for that session instead of silently reporting success

#### Scenario: Teardown by task
- **WHEN** `task.session_per_task` is enabled and `tjor down --task A` is run from the repository
- **THEN** the session the launch derived for task A is torn down, and `--task` together with `--session` is a usage error
