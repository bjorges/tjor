# Spec Delta

## ADDED Requirements

### Requirement: Every process in the harness tree can read its own /proc entries

When the tier is active, the kernel ruleset SHALL grant read access to the container's `/proc`, so that every process in the harness tree, not only the first one the wrap starts, can read its own `/proc/self` entries (`maps`, `exe`, `status`, `cmdline`, `cgroup`). Language runtimes read these at startup and some abort when the read fails; a tier that lets the harness start but kills the processes it spawns would be a tier that LOOKS active and is not usable. The grant SHALL be read-only and SHALL NOT weaken any other rule: a path the ruleset denies SHALL stay denied when it is reached through a `/proc/<pid>/root`, `/proc/<pid>/cwd` or `/proc/<pid>/fd` link. Documentation SHALL state the residual plainly: the agent can list the cage's own processes and read their command lines, bounded to the cage's own processes by the container's pid namespace; no host process is visible.

#### Scenario: A spawned runtime reads its own process state
- **WHEN** the tier is active and the harness spawns a child process that reads its own `/proc/self/maps` (a Bun or Node.js runtime does so while starting)
- **THEN** the read succeeds and the child starts, exactly as the first process in the tree does

#### Scenario: opencode v2 starts its server under the wrap
- **WHEN** the tier is active and opencode v2 is launched, with `--standalone` or in its default service mode
- **THEN** the server process it spawns starts and the command completes; the session does not fail with "Standalone server exited before reporting readiness"

#### Scenario: Denied paths stay denied through /proc links
- **WHEN** a process in the harness tree reads a path the ruleset denies by way of `/proc/self/root/<path>` or another process's `root`, `cwd` or `fd` link
- **THEN** the read is denied exactly as the direct read is

#### Scenario: The residual is stated
- **WHEN** an operator reads the kernel-sandbox documentation
- **THEN** it states that `/proc` is readable inside the tier, what that exposes (the cage's own process list and command lines) and what bounds it (the container's pid namespace)
