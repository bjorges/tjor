# ADR 0015 — `/proc` is readable inside the kernel-sandbox tier

**Date:** 2026-11-13 · **Status:** accepted

## Context

The kernel-sandbox tier (#9) runs the harness under `cplt exec`, a Landlock
allowlist plus seccomp. cplt's Linux backend without Bubblewrap grants
`/proc/self` by a rule it resolves in the child right before `exec`. Landlock
rules are attached to inodes, and `/proc/self` resolves to the `/proc/<pid>`
directory of the process that opens it, so the rule covers the first
sandboxed pid and no other: every process forked below it gets `EACCES` on
its own `/proc/self/*`.

That was invisible while every harness ran in one process. opencode v2
spawns a second Bun process for its server, and Bun aborts during
JavaScriptCore VM creation when it cannot read its own `/proc/self/maps`
(glibc's `pthread_getattr_np` reads it to find the main thread's stack).
Every session with the tier active failed to start (#103). cplt's maintainers
met the identical failure (navikt/cplt PR 740) and answered it with
Bubblewrap, whose private pid namespace makes granting all of `/proc`
harmless; without Bubblewrap the current cplt refuses opencode v2, with the
hint "pass --allow-read /proc if that is acceptable". Bubblewrap cannot run
in the cage: it needs an unprivileged user namespace, which Docker's default
seccomp profile blocks under `cap_drop: [ALL]` (the Dockerfile note for #10).

The failure class is "any Bun or Node child under the wrap": Claude Code's
binary is a Bun standalone executable too, and so is many an MCP server.

## Decision

1. **The wrap grants the container's `/proc`, read-only, unconditionally.**
   `--allow-read /proc` joins the cplt flags for every harness and every
   launch mode. Landlock has no wildcard, so a per-child `/proc/<pid>` grant
   is not expressible; cplt's own answer under a pid namespace is the same
   whole-tree read grant.
2. **The container is the pid namespace cplt wants from Bubblewrap.** cplt's
   warning ("every host process's command line") describes a host. In the
   cage `/proc` is the agent container's procfs: PID 1 is cplt after the
   entrypoint's exec chain, the rest is the harness tree; the proxy, DNS and
   gateway sidecars are other containers. Measured in the released image:
   the agent can list these processes and read their command lines (cplt's
   flags, no secret); cplt's `environ` and `mem` are refused; another
   process's `root` and `cwd` links are refused; the harness's own
   `/proc/self/root/<denied path>` is refused by Landlock exactly as the
   direct read is. The environment the agent could learn from PID 1 is the
   one `--inherit-env` already gives it.
3. **The grant is a stated residual.** The kernel-sandbox spec carries it as
   a requirement with the magic-link invariant; the README and the slide name
   it; the live Landlock suite proves a forked child reads its own
   `/proc/self`, that a denied path stays denied through `/proc/self/root`,
   and that `opencode --standalone` starts under the real wrap, offline.

## Consequences

- opencode v2 (standalone and service mode), Claude Code and Bun or Node
  children start under the tier. The tier is no longer a tier that looks
  active and is not usable.
- The agent sees the cage's own process list. Nothing in those command lines
  is secret by construction (the broker and gateway values in the cage are
  placeholders), and the pid namespace shows no host process.
- The fail-closed rule of the tier stands: a future cplt that refused the
  flag would fail the exec and abort the start, never run unwrapped.
- A `--allow-read` on `/proc` is read-only; `/proc/sys` stays unwritable and
  Docker's masked `/proc` paths are unaffected (masks are mounts, not rules).

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
