# session-launch Specification

## Purpose
The launcher contract: how a session starts, where its state lives, how the workspace appears inside the cage, and how the launcher reports what protections are actually active.

## Requirements

### Requirement: Per-session state root

Each session SHALL have its own state root on the host, from which the harness's state/config directories are bind-mounted, so sessions and auth survive container recreation while containers stay disposable.

#### Scenario: Container recreated mid-project
- **WHEN** a session's container is removed and relaunched with the same session
- **THEN** harness auth and session history are intact

### Requirement: Workspace path fidelity

The launcher SHALL mount the project workspace at the same absolute path inside the container as on the host, resolving the project root via the version-control toplevel rather than string manipulation of the working directory.

#### Scenario: Launch from a subdirectory of a repo
- **WHEN** tjor is launched from a subdirectory of a git repository
- **THEN** the container sees the repository root and working directory at identical paths to the host, and the harness associates prior sessions correctly

#### Scenario: Writable workspace
- **WHEN** the harness edits, builds, and commits inside the mounted repository
- **THEN** all operations succeed (mounts are writable by the agent user)

### Requirement: Host preflight with clear errors

The launcher SHALL verify its host dependencies (shell version, required tools, container runtime) before any action, and report each missing dependency by name with remediation guidance.

#### Scenario: Missing dependency
- **WHEN** a required host tool is absent
- **THEN** the launcher exits before touching any state, naming the tool and how to install it

### Requirement: Tiered guarantees degrade loudly

The launcher SHALL distinguish core guarantees (available on any supported runtime) from hardening add-ons (runtime-dependent). When an add-on is unavailable, the launcher SHALL state exactly which guarantee is inactive and continue only for add-ons — a missing core guarantee SHALL abort the launch.

#### Scenario: Runtime without LSM support
- **WHEN** the container runtime cannot enforce an optional hardening add-on
- **THEN** the launch proceeds with a persistent, explicit statement of which protection is inactive

#### Scenario: Core guarantee unavailable
- **WHEN** the internal-only network or egress proxy cannot be established
- **THEN** the launch aborts; the agent never starts with an open boundary

### Requirement: Single config merge path

Every entry point SHALL obtain effective configuration through one shared merge implementation covering all config sections.

#### Scenario: Override honored everywhere
- **WHEN** a user override is set for any config section
- **THEN** every entry point (launcher, debug CLI, topology setup) observes the same effective value

### Requirement: Launcher derives and distributes the identity set

At session launch, the launcher SHALL derive the identity set (session id from the workspace as today; harness from the selected image; repo from the git toplevel basename; worktree when the workspace is a linked worktree; task id from a `--task` argument when given; parent session from `TJOR_PARENT_SESSION` in the calling environment when set) and SHALL deliver it to both the agent container (environment) and the proxy sidecar (identity registration).

#### Scenario: Launch with a task id
- **WHEN** `tjor run --task PLT-1234` starts a session
- **THEN** the agent environment contains `TJOR_TASK_ID=PLT-1234` and the proxy accepts `x-agent-task-id: PLT-1234` outbound

#### Scenario: Launch without a task id
- **WHEN** `tjor run` starts without `--task`
- **THEN** the session launches normally with the task-id variable absent and any outbound `x-agent-task-id` header stripped

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
