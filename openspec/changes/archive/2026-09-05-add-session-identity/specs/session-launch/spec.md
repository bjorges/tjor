## ADDED Requirements

### Requirement: Launcher derives and distributes the identity set

At session launch, the launcher SHALL derive the identity set (session id from the workspace as today; harness from the selected image; repo from the git toplevel basename; worktree when the workspace is a linked worktree; task id from a `--task` argument when given; parent session from `TJOR_PARENT_SESSION` in the calling environment when set) and SHALL deliver it to both the agent container (environment) and the proxy sidecar (identity registration).

#### Scenario: Launch with a task id
- **WHEN** `tjor run --task PLT-1234` starts a session
- **THEN** the agent environment contains `TJOR_TASK_ID=PLT-1234` and the proxy accepts `x-agent-task-id: PLT-1234` outbound

#### Scenario: Launch without a task id
- **WHEN** `tjor run` starts without `--task`
- **THEN** the session launches normally with the task-id variable absent and any outbound `x-agent-task-id` header stripped
