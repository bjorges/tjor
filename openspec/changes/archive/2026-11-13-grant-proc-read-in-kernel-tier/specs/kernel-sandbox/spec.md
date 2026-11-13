# Spec Delta

## MODIFIED Requirements

### Requirement: The harness runs under kernel filesystem denies when the tier is active

When the tier is active, the harness process and every process it spawns SHALL run under a kernel-enforced allowlist ruleset: filesystem access outside the granted trees (the workspace, operator-mounted extra repos, the harness's own state directories, and system paths needed to run) SHALL be denied by the kernel. The restrictions SHALL be irrevocable for the lifetime of the process tree: no process in the tree can lift or bypass them. (Landlock is allowlist-only — it cannot deny a path *inside* a granted tree; in-tree secret files are covered by the launch-time masking requirement below.)

The system paths needed to run SHALL include, read-only: the container's `/proc`, so that every process in the tree, not only the first one the wrap starts, can read its own `/proc/self` entries (language runtimes read them at startup, and a Bun-compiled one aborts when the read fails); and the managed opencode config directory (`/etc/opencode`) when it exists, so a hardened profile's managed settings apply under the tier instead of silently not loading. Neither grant SHALL weaken another rule. `/proc` SHALL NOT be writable from the tree: a write the agent user may do outside the wrap, such as setting its own `comm`, SHALL be refused inside it. A `root`, `cwd`, `exe` or `fd` link of the process itself or of a process inside the same sandbox SHALL resolve, and the target's own path rules SHALL apply: a granted file reads, a denied file or an ungranted directory listing is refused. For a process outside the sandbox (PID 1, an operator's `docker exec`), Landlock's ptrace rule SHALL keep the entries that need ptrace-level access refused whatever their target: `environ`, `maps`, `smaps`, `mem`, `io`, `exe`, `ns/*`, `root`, `cwd` and the `fd` targets. The rest of that process's entries stay readable: `cmdline`, `comm`, `status`, `stat`, `statm`, `cgroup`, `limits`, `mountinfo`, `oom_score`, `sched`, and the `fd` and `task` name listings. Documentation SHALL state what the `/proc` grant exposes: kernel-wide status files as the container's kernel reports them (memory, CPU, the kernel command line, the container's network and mount tables), those readable entries of the cage's other processes, and, for processes inside the harness's own sandbox, their environment, maps and open files. It SHALL state what bounds it: the container's pid namespace shows no host process, and the ptrace rule above. The harness's own permission prompts and its loopback service are harness-level controls that the tree's processes share one uid with; they are not a tjor boundary, with or without this grant.

#### Scenario: Outside-tree read is denied
- **WHEN** the tier is active and the harness attempts to read a container path outside every granted tree
- **THEN** the read fails with a kernel-level denial

#### Scenario: Outside-tree write is denied
- **WHEN** the tier is active and the harness attempts to create or modify a file outside every granted tree
- **THEN** the write fails with a kernel-level denial

#### Scenario: Child processes inherit the restrictions
- **WHEN** the harness spawns a shell or tool that attempts an outside-tree access
- **THEN** the access fails identically — the ruleset is inherited by the whole tree

#### Scenario: Restrictions cannot be dropped in-session
- **WHEN** any process in the harness tree attempts to remove or relax the active ruleset
- **THEN** the restrictions remain in force (the mechanism is one-way for an unprivileged process)

#### Scenario: A spawned runtime reads its own process state
- **WHEN** the tier is active and the harness spawns a child process that reads its own `/proc/self/maps` (a Bun or Node.js runtime does so while starting)
- **THEN** the read succeeds and the child starts, exactly as the first process in the tree does

#### Scenario: opencode v2 starts under the wrap
- **WHEN** the tier is active and opencode v2 is launched, with `--standalone` or in its default service mode
- **THEN** the server process it spawns starts inside the container and the command completes; a second invocation in service mode reuses that service, and the service does not outlive the container

#### Scenario: The managed opencode config applies under the wrap
- **WHEN** a profile's `managed/opencode.json` was deployed to `/etc/opencode` and the tier is active
- **THEN** opencode loads it under the wrap (a key set only there is visible in the merged config)

#### Scenario: The tree's own /proc links keep the target's path rules
- **WHEN** a process in the harness tree reads a path by way of `/proc/self/root/<path>`, a `/proc/self/cwd` traversal, or the `root` link of a process inside the same sandbox
- **THEN** a granted path reads and a denied path is refused, exactly as the direct read is

#### Scenario: Processes outside the sandbox keep their private entries
- **WHEN** a process in the harness tree reads the `environ`, `maps`, `root`, `cwd`, `exe` or an `fd` target of PID 1 or of a same-uid process started outside the wrap
- **THEN** the read is refused whatever the target would be; that process's `cmdline` and `status` remain readable

#### Scenario: /proc is read-only under the wrap
- **WHEN** a process in the harness tree writes its own `/proc/self/comm`
- **THEN** the write is refused, while the same write succeeds for the agent user outside the wrap

#### Scenario: The residual is stated
- **WHEN** an operator reads the kernel-sandbox documentation
- **THEN** it states that `/proc` is readable inside the tier, what that exposes and what bounds it
