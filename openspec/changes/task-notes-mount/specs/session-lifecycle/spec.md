# Spec Delta

## MODIFIED Requirements

### Requirement: Reattachment

`tjor attach [session]` SHALL reattach the terminal to a running agent container, accepting either the fully-qualified session id or the short session name (resolved against the current workspace), or `--task <id>` to select the running agents carrying that task label. With no argument and exactly one running session, it attaches to it; with several candidates it SHALL offer an interactive picker; with none it SHALL say so and exit non-zero.

#### Scenario: Reattach after a dropped terminal
- **WHEN** an agent container is running and `tjor attach` is invoked with its session id
- **THEN** the terminal is attached to that agent's TTY

#### Scenario: Reattach by short name
- **WHEN** a named session is running and `tjor attach <short-name>` is invoked from its workspace
- **THEN** the short name resolves to the same session as its fully-qualified id and the attach proceeds

#### Scenario: Reattach by task
- **WHEN** two sessions run for tasks `a` and `b` and `tjor attach --task b` is invoked
- **THEN** the terminal is attached to the agent whose task label is `b`; with the same task id running in two repositories the picker is offered; with no such agent the command says so and exits non-zero
