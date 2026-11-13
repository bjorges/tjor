# ADR 0015 — `/proc` is readable inside the kernel-sandbox tier

**Date:** 2026-11-13 · **Status:** accepted

## Context

The kernel-sandbox tier (#9) runs the harness under `cplt exec`, a Landlock
allowlist plus seccomp, with cplt pinned at `2026.09.13-135112-daf7f1f`.
cplt's Linux backend without Bubblewrap grants `/proc/self` by a rule it
resolves in the child right before `exec` (`src/sandbox_landlock.rs`,
"Paths under /proc/self are magic symlinks that resolve to /proc/<pid>").
Landlock rules are attached to inodes, and `/proc/self` resolves to the
`/proc/<pid>` directory of the process that opens it, so the rule covers the
first sandboxed pid and no other: every process forked below it gets `EACCES`
on its own `/proc/self/*`.

That was invisible while every harness ran in one process. opencode v2
spawns a second Bun process for its server, and Bun aborts during
JavaScriptCore VM creation when it cannot read its own `/proc/self/maps`
(glibc's `pthread_getattr_np` reads it to find the main thread's stack; the
crash report decodes to `JSC::VM::tryCreate` → `abort()`). Every session
with the tier active failed to start (#103). navikt/cplt PR 740 ("run v2
sessions on Linux") met the identical failure and answered it with
Bubblewrap, whose private pid namespace makes granting all of `/proc`
harmless; without Bubblewrap the 2026-11-06 cplt refuses opencode v2 and
prints "pass --allow-read /proc if that is acceptable". Bubblewrap cannot
run in the cage: it needs an unprivileged user namespace, which Docker's
default seccomp profile blocks under `cap_drop: [ALL]` (the Dockerfile note
for #10).

Measured in the released 0.23.0 image: a forked child of the first sandboxed
process is denied its own `/proc/self/maps`; opencode's `serve --stdio` and
`serve --service` children abort about 1 ms after exec; a forked
`claude --version` in the claude image aborts the same way (`abort() called`,
exit 134) and runs with the grant. Found on the way: `/etc/opencode`, where a
hardened profile's `managed/opencode.json` is deployed root-owned, is outside
cplt's system grants, so under the wrap the managed settings were silently
not loaded (`opencode debug config` lists the file unsandboxed and omits it
under the wrap).

## Decision

1. **The wrap grants the container's `/proc`, read-only, unconditionally.**
   `--allow-read /proc` joins the cplt flags for every harness and every
   launch mode. Landlock has no wildcard, so a per-child `/proc/<pid>` grant
   is not expressible; cplt's own answer under a pid namespace is the same
   whole-tree read grant; the failure class is "a Bun or Node child", not
   "opencode v2".
2. **The wrap grants `/etc/opencode`, read-only, when it exists.** A managed
   policy that a hardened profile relies on must load under the tier; a
   grant on an absent directory is a cplt warning, so it is added only when
   the entrypoint deployed the file.
3. **What the `/proc` grant exposes, measured on the pinned cplt with cplt as
   PID 1 and a same-uid process started outside the wrap:**
   - readable: kernel-wide status files as the container's kernel reports
     them (`meminfo`, `stat`, `cpuinfo`, the kernel command line, the
     container's `net/*` and mount tables); the command lines of the cage's
     other processes; the environment, maps and open files of processes
     inside the harness's own sandbox (the agent's own tree);
   - refused: PID 1's and the outside process's `environ`, `maps`, `root`,
     `cwd` and `fd` targets (Landlock's ptrace rule: a sandboxed process may
     not inspect a process outside its domain); an open fd that such a
     process holds on a denied file; a denied path reached through
     `/proc/self/root` or a `/proc/self/cwd` traversal, while a granted path
     resolves through the same link; every write under `/proc`.
   The container's pid namespace shows no host process. Docker's masked
   `/proc` paths are unaffected (masks are mounts, not rules).
4. **What this is not.** The harness's own permission prompts and its
   loopback service are harness-level controls. Every process in the tree
   shares one uid and one sandbox; a tool the harness spawns could already
   reach the harness's stdio and its service before this grant. tjor's
   boundary is the container, the egress proxy and the kernel path denies;
   the README's "Why" says so and this ADR restates it.
5. **The grant is a stated residual with live proof.** The kernel-sandbox
   spec carries it inside the granted-trees requirement; the README and the
   slide name it; the Landlock suite, now a CI job, pairs each direct denial
   with its `/proc` link, launches opencode v2 in `--standalone` and in the
   shipped default service mode, and loads a sentinel key from the managed
   config.

## Consequences

- opencode v2, Claude Code and Bun or Node children start under the tier; a
  hardened profile's managed policy applies under it. The tier is no longer
  a tier that looks active and is not usable.
- The agent sees the container kernel's status files and the cage's process
  list. Command lines of the cage's own processes are tjor's (cplt's flags)
  or the agent's own; an operator who runs `docker exec` with a secret on
  the command line shows it to the agent, as on any shared machine.
- The fail-closed rule of the tier stands: a future cplt that refused the
  flag would fail the exec and abort the start, never run unwrapped.
- Rollback: `[landlock] mode = "off"` disables the tier (the #103 workaround,
  no longer needed), or run the previous image tag.
- The claims above hold for the pinned cplt; a pin bump re-runs the suite.

## Alternatives considered

- **Bubblewrap in the image.** Rejected again (#10): user namespaces are
  blocked by the container's zero-capability posture, and a binary that
  cannot run would print a false "sockets restricted" signal.
- **Run `opencode serve` under cplt from the entrypoint and attach the
  client.** Rejected: the server's own children stay broken, and it adds a
  port, a readiness wait and a second process lifecycle to the entrypoint.
- **Skip the wrap for opencode v2, or document `mode = "off"`.** Rejected:
  drops the tier for the harness that needs it most.
- **`--allow-jvm-attach`.** Grants `/proc` too, but also `/tmp/.java_pid*`
  sockets, and says the wrong thing in cplt's startup summary.
- **Report to Bun.** Worth doing, not blocking: a graceful fallback when
  `/proc/self/maps` is unreadable would help every sandbox, but Node.js
  children read the same files and the grant is still the honest answer.
