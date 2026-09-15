# session-launch Specification

## Purpose
The launcher contract: how a session starts, where its state lives, how the workspace appears inside the cage, and how the launcher reports what protections are actually active.

## Requirements

### Requirement: Per-session state root

Each session SHALL have its own state root on the host, from which the harness's state/config directories are bind-mounted, so sessions and auth survive container recreation. The container itself holds no durable state — all durable state lives in the state root — so a container can be removed and recreated without loss. (Container *lifetime* is governed by "Agents launch detached and persist independently of the launching client" below: containers persist until explicit teardown rather than being auto-removed.)

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

Every entry point SHALL obtain effective configuration through one shared merge implementation covering all config sections. When the current repo carries a `.tjor/config.toml` that the user has approved (`repo-config-trust`), it layers over the user config in that one merge path; an unapproved repo config is excluded from the merge.

#### Scenario: Override honored everywhere
- **WHEN** a user override is set for any config section
- **THEN** every entry point (launcher, debug CLI, topology setup) observes the same effective value

#### Scenario: Trusted repo layer applies through the same path
- **WHEN** an approved repo `.tjor/config.toml` sets a value
- **THEN** every entry point observes it via the same merge path, layered over the user config

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

**Threat-model note (posture change).** This replaced the earlier auto-removed (`--rm`) container model. The trade-off is deliberate: reattach requires the container to survive a dropped client, which *lengthens the window* in which a compromised agent's container lingers before teardown. This is accepted because the structural boundary (internal-only network, fail-closed egress, non-root, absent host credentials) holds for the container's whole lifetime whether it is 1 minute or 1 day — persistence does not widen what the agent can reach, only how long an idle container exists. `tjor gc` reaps idle containers on a bound; `tjor ls` re-verifies each running session's boundary on demand. See ADR 0006.

#### Scenario: Dropped terminal leaves a reattachable session
- **WHEN** the client attached to a running agent is killed
- **THEN** the agent container keeps running and `tjor attach` can reconnect to it

#### Scenario: Detached launch
- **WHEN** `tjor run --detach` is used
- **THEN** the launcher starts the session and returns without attaching, naming the session to attach to later

### Requirement: Interactive sessions receive a PTY at container creation

When the launcher's stdin is a terminal, the agent container SHALL be created with a pseudo-TTY allocated, so the harness process observes an interactive stdin/stdout from its first instruction — independent of when (or whether) an attach client connects, and independent of any redirection or capture of the launcher's own stdout. After starting the agent container the launcher SHALL verify that a PTY was actually allocated when one was intended, and SHALL abort with a clear error if not — a session must never proceed into a state where the harness silently hangs or degrades because its stdin is a pipe.

When the launcher's stdin is not a terminal, the launch SHALL proceed without a PTY (one-shot commands still run to completion and propagate exit codes), and the launcher SHALL warn loudly that interactive harnesses will not work in that session.

#### Scenario: Interactive launch from a terminal
- **WHEN** `tjor run` is invoked from a terminal (even with the launcher's stdout captured or redirected)
- **THEN** the harness process sees a TTY on stdin and stdout at its own startup, before any attach client connects

#### Scenario: Typed input reaches the harness through attach
- **WHEN** a terminal client attaches to a running interactive session and sends input
- **THEN** the harness receives that input on its interactive stdin

#### Scenario: Non-terminal launch degrades loudly
- **WHEN** `tjor run` is invoked without a terminal on stdin
- **THEN** the session starts without a PTY, the launcher warns loudly that interactive harnesses will not work in this session, and a one-shot command still runs to completion and propagates its exit code

#### Scenario: Intended PTY missing aborts
- **WHEN** the launcher intended a PTY but the created agent container reports none allocated
- **THEN** the launch aborts with a clear error naming the problem instead of leaving a silently broken session running

### Requirement: Named session derivation

When `--session <name>` is given (name matching `[A-Za-z0-9._-]{1,32}`), the session id SHALL be derived from both the workspace and the name; without it, derivation is unchanged (repo-scoped default session). Derivation SHALL be idempotent: a value already equal to, or prefixed by, the current workspace's qualified id SHALL resolve to the same session as its short form — never to a doubled id. A value that is an existing *other* workspace's fully-qualified session id SHALL be refused at launch with a clear error (launching this workspace under another workspace's session identity is never derived silently).

#### Scenario: Same repo, different names
- **WHEN** sessions `a` and `b` are launched from the same repo
- **THEN** their session ids differ and neither collides with the repo's default session

#### Scenario: Relaunching with the displayed qualified id
- **WHEN** `tjor run --session <qualified-id-of-this-workspace's-session>` is invoked (e.g. pasted from a tjor message)
- **THEN** it resolves to the same session as the short name — subject to the same already-running collision guard — and no doubled session id is ever created

#### Scenario: Foreign qualified id refused at launch
- **WHEN** `tjor run --session <id>` is given a fully-qualified id of an existing session belonging to a different workspace
- **THEN** the launch is refused with an error explaining the id belongs to another workspace

### Requirement: Additional repositories via repeatable --dir

`tjor run` SHALL accept a repeatable `--dir <path>` option. Each given path SHALL be resolved to an absolute path and mounted into the agent container at that same absolute path, writable by the agent user. Paths are in addition to the primary workspace (the invocation's git toplevel), which is unchanged.

#### Scenario: Two repositories in one session
- **WHEN** `tjor run --dir /path/to/repo-b` is launched from inside repo-a
- **THEN** the agent sees both repo-a and repo-b at their host paths, both writable, and git operations work in each

#### Scenario: Extra dirs do not change session identity
- **WHEN** a session is launched with and without `--dir` from the same primary workspace
- **THEN** the session id, `x-agent-repo`, and the harness cwd are identical in both cases

### Requirement: Read-only additional repositories via repeatable --dir-ro

`tjor run` SHALL accept a repeatable `--dir-ro <path>` option. Each given path
SHALL be resolved to an absolute path and mounted into the agent container at
that same absolute path **read-only**, enforced at the container level so no
process in the container — the harness tree and `docker exec` alike — can
write, create, delete, or rename anything under it. A `--dir-ro` mount SHALL
otherwise be treated as a mounted repo: trusted by git (`safe.directory`) and
covered by launch-time secret masking (dotenv discovery and configured deny
paths/dirs). The sensitive-host-path refusal SHALL apply to `--dir-ro` exactly
as to `--dir` (read-only access still exposes content for exfiltration), with
the same `--unsafe-dir` override. The same path given to both `--dir` and
`--dir-ro` in one invocation SHALL abort the launch with a clear error rather
than silently picking a writability.

#### Scenario: Writes into a read-only mount are refused

- **WHEN** a session is launched with `--dir-ro /path/to/repo-b` and any
  process inside the container attempts to create, modify, delete, or rename
  a file under `/path/to/repo-b`
- **THEN** the operation fails, while reads of the same tree succeed

#### Scenario: Git works read-only in the mount

- **WHEN** the agent runs read-only git operations (`status`, `log`, `diff`)
  inside a `--dir-ro` mounted repository
- **THEN** they succeed without dubious-ownership refusals

#### Scenario: Secret masking still covers the read-only mount

- **WHEN** a `--dir-ro` mounted repo contains a `.env` file at launch
- **THEN** the file is masked exactly as it would be in a writable mount

#### Scenario: Sensitive path refused read-only too

- **WHEN** `tjor run --dir-ro <sensitive path>` names a refused host location
  (home root, credential dirs) without `--unsafe-dir`
- **THEN** the launch aborts with an error stating the read-only exposure risk

#### Scenario: Conflicting writability for one path

- **WHEN** one invocation passes the same resolved path to both `--dir` and
  `--dir-ro`
- **THEN** the launch aborts with an error naming the path and the conflict

### Requirement: Each extra dir is verified before mounting

Every `--dir` and `--dir-ro` path SHALL be verified to exist and to be shared
with the container runtime (the same VM-share check applied to the primary
workspace). A missing or unshared path SHALL abort the launch with a clear
error naming the path.

#### Scenario: Unshared extra dir

- **WHEN** a `--dir` or `--dir-ro` path is not shared with the Docker VM
  (bind mounts of it would appear empty)
- **THEN** the launch aborts, naming the path, before the agent starts

#### Scenario: Nonexistent extra dir

- **WHEN** a `--dir` or `--dir-ro` path does not exist
- **THEN** the launch aborts with an error naming the path
