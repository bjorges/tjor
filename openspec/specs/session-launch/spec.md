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
