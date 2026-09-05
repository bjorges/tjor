## ADDED Requirements

### Requirement: Additional repositories via repeatable --dir

`tjor run` SHALL accept a repeatable `--dir <path>` option. Each given path SHALL be resolved to an absolute path and mounted into the agent container at that same absolute path, writable by the agent user. Paths are in addition to the primary workspace (the invocation's git toplevel), which is unchanged.

#### Scenario: Two repositories in one session
- **WHEN** `tjor run --dir /path/to/repo-b` is launched from inside repo-a
- **THEN** the agent sees both repo-a and repo-b at their host paths, both writable, and git operations work in each

#### Scenario: Extra dirs do not change session identity
- **WHEN** a session is launched with and without `--dir` from the same primary workspace
- **THEN** the session id, `x-agent-repo`, and the harness cwd are identical in both cases

### Requirement: Each extra dir is verified before mounting

Every `--dir` path SHALL be verified to exist and to be shared with the container runtime (the same VM-share check applied to the primary workspace). A missing or unshared path SHALL abort the launch with a clear error naming the path.

#### Scenario: Unshared extra dir
- **WHEN** a `--dir` path is not shared with the Docker VM (bind mounts of it would appear empty)
- **THEN** the launch aborts, naming the path, before the agent starts

#### Scenario: Nonexistent extra dir
- **WHEN** a `--dir` path does not exist
- **THEN** the launch aborts with an error naming the path
