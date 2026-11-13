# Design

## Context

The kernel-sandbox tier runs the harness under `cplt exec` with a Landlock ruleset built from the flags in `images/agent/entrypoint.sh` (add-landlock-tier, decision 2), cplt pinned at `2026.09.13-135112-daf7f1f`. cplt's Linux backend without Bubblewrap adds one rule for `/proc/self`, resolved in the child before `exec`: Landlock rules are attached to inodes, and `/proc/self` resolves to the `/proc/<pid>` directory of the process that opens it, so the rule covers the first sandboxed pid and no other (`src/sandbox_landlock.rs`: "Paths under /proc/self are magic symlinks that resolve to /proc/<pid>"). cplt grants all of `/proc` only under Bubblewrap, where a private pid namespace makes the grant harmless, or with `--allow-jvm-attach`.

Measured in the released 0.23.0 image on Colima (kernel 6.8, Landlock ABI 4, arm64), with the entrypoint's flag set:

- the first sandboxed process reads `/proc/self/maps`; a forked child gets `Permission denied` on its own;
- opencode 2.2.7 spawns `/usr/local/bin/opencode serve --stdio --port 0` (`--standalone`) or `serve --service` (default), and that child aborts about 1 ms after exec: `panic(main thread): abort() called`, trace `JSC::VM::tryCreate` ← `Zig__GlobalObject__create` ← `boot_standalone`;
- in the claude image, `claude --version` works as the first process and aborts the same way (`abort() called`, exit 134) when forked from a shell under the wrap; with the grant it runs;
- adding `--allow-read /proc` makes `run ping`, `session list`, `debug config` and `models` succeed, the last three with networking disabled;
- the newest cplt (2026.11.06-074203-2265661) behaves the same in `exec` mode and prints: "Without Bubblewrap only the agent's first process can read its own /proc/self ... Install bubblewrap, or pass --allow-read /proc if that is acceptable";
- `/etc/opencode/opencode.json`, where the entrypoint deploys a hardened profile's managed config root-owned (#46), is listed by `opencode --standalone debug config` unsandboxed and absent under the wrap: the directory is outside cplt's system grants, so the managed settings silently did not load whenever the tier was active.

Bubblewrap is not an option in-cage: it needs an unprivileged user namespace, which Docker's default seccomp profile blocks under the container's `cap_drop: [ALL]` / `no-new-privileges` posture (Dockerfile note for #10; the v0.18.15 attempt was reverted).

## Goals / Non-Goals

**Goals:**
- Every process in the harness tree can read its own `/proc/self`, so Bun-compiled harnesses and their children start under the tier.
- A hardened profile's managed opencode config applies under the tier.
- The grants are the smallest that do this, read-only, with the exposure measured and stated.
- A regression check that launches opencode v2 under the real wrap, offline, in CI, in both launch modes.

**Non-Goals:**
- Bubblewrap, user namespaces or any change to the container's capability posture.
- Per-harness or per-mode wrap flags (the failure class is "any Bun or Node child", not "opencode v2").
- Changing the shipped opencode launch mode (`config/tjor.toml` ships `args = []`, the service mode), the cplt pin, or the egress and network layers.

## Decisions

### D1. The wrap grants `/proc` read-only, for every harness and launch mode

`images/agent/entrypoint.sh` adds `--allow-read /proc` to the `wrap` array, unconditionally. Rationale: Landlock has no wildcard, so there is no way to grant each future child its own `/proc/<pid>` ahead of time; cplt's own answer under Bubblewrap is the same whole-tree read grant; the trigger is the runtime (Bun; Node.js reads the same files), not the harness, so a per-harness flag would leave MCP servers and agent-installed tools broken under one harness and working under another. The grant is read-only: writes under `/proc` are refused, and Docker's masked `/proc` paths are unaffected because masking is a mount, not a Landlock rule.

*Alternatives considered:* running `opencode serve` under cplt from the entrypoint and attaching the client (the server's own children stay broken, and it adds a port, a readiness wait and a second lifecycle); skipping the wrap for opencode v2 (drops the tier for the harness that needs it most); `--allow-jvm-attach` (grants `/proc` too, but also `/tmp/.java_pid*` sockets, and says the wrong thing in the startup summary).

### D2. What the grant exposes and what bounds it, measured

Measured on the pinned cplt with cplt as PID 1 (the entrypoint's layout) and a same-uid process started outside the wrap holding a denied file open:

| Read from the wrapped tree | Result |
|---|---|
| kernel-wide status files (`meminfo`, `stat`, the kernel command line, `net/tcp`, `self/mountinfo`) | readable, as the container's kernel reports them |
| PID 1 and the outside process: `cmdline`, `comm`, `status`, `stat`, `statm`, `cgroup`, `limits`, `mountinfo`, `oom_score`, `sched`, `fd` and `task` name listings | readable |
| PID 1 and the outside process: `environ`, `maps`, `smaps`, `mem`, `io`, `exe`, `ns/*`, `root`, `cwd`, `fd` targets | refused, whatever the target |
| the outside process's open fds: a granted workspace file (`fd/3`) and a denied file (`fd/4`) | refused, both: the ptrace rule, not the path rules |
| PID 1's `environ`, `exe`, `cwd`, `fd/0`, `root` and the outside process's `fd/3` and `environ`, read by the agent user with `docker exec` (control) | readable: the in-wrap refusals are Landlock's ptrace rule, not file permissions |
| a sibling inside the same sandbox: `environ`, `maps`, `exe`, `cwd`, `fd` targets | readable |
| a same-sandbox peer's `fd` link to a pipe fed by a sibling; to an open granted file | the pipe's content reads (and drains); the file reads; sockets cannot be reopened |
| a same-sandbox peer's `mem`, opened by a non-ancestor (a child of the probe reading the probe, a sibling) with `kernel.yama.ptrace_scope=1` | refused (`EACCES`); the ancestor opens its child's |
| the same with `ptrace_scope=0` or no Yama | opens (the kernel rule; not run here; the entrypoint prints a note on such an engine) |
| `/proc/sys` (hostname, the boot id), `/proc/version`, `kallsyms` (names; addresses zeroed under `kptr_restrict=1`), `mountinfo` (host-side mount sources), `cgroup` (`0::/`) | readable |
| PID 1's `comm`, the pid count | `cplt`, a handful: the pid namespace is the container's |
| the tree's own links: `/proc/self/root/<granted>`, a same-sandbox `root/<granted>` | resolve and read |
| the tree's own links: `/proc/self/root/<denied>`, a `/proc/self/cwd` traversal to a denied file, a same-sandbox `root/<denied>`, listing `/` through `root` | refused: the target's path rules apply |
| write to the agent's own `/proc/self/comm` | refused inside the wrap; succeeds for the agent user outside it; succeeds again under a `--allow-write /proc` mutation |
| write under `/proc/sys` (the current value written back) | refused with or without the wrap, and for container root (`EROFS`): Docker's read-only mount |

The refusals for processes outside the sandbox are Landlock's ptrace rule (a sandboxed process may not inspect a process outside its own domain), not file permissions: the holder is the same uid and the controls read the same entries outside the wrap. The container's pid namespace shows no host process. cplt's warning ("every host process's command line") describes a host; in the cage the command lines are tjor's own (cplt's flags) or the agent's. Inside the sandbox the harness and the tools it spawns are one uid and one domain: before this grant a spawned tool had the descriptors it inherited and the loopback service; with it, it can also reopen any peer's pipe or regular-file descriptor through `/proc/<pid>/fd` (the standalone client's stdio channel and a stdio MCP transport are such pipes) and, on an engine with Yama off, read a peer's memory. The harness's permission prompts are not a boundary against in-tree tools either way; tjor's boundary is the container, the egress proxy and the kernel path denies (README "Why"). The entrypoint prints a note when `kernel.yama.ptrace_scope` is 0 or absent, so the residual is stated on the engine where it applies.

### D3. The invariant lives in the granted-trees requirement

The kernel-sandbox spec's "The harness runs under kernel filesystem denies when the tier is active" is modified (not a second requirement restating it) to name the two read-only system grants, the link invariant, the exposure and its bounds, with scenarios for the spawned runtime, both opencode launch modes, the managed config, the links, the outside processes and the stated residual. The README and the slide carry the same sentences; ADR 0015 records the decision, the upstream references and the pinned version the claims hold for.

### D4. Proof: the Landlock suite, in CI, strict

`tests/integration/landlock_test.sh` part A runs a probe script as the harness command under the real wrap and reads findings back from the workspace. It now:

- replaces the `/etc/shadow` outside-tree read (denied by file permissions, so it proved nothing about Landlock) with `/etc/hostname`, world-readable in the image and outside cplt's system grants, and adds a `docker exec -u agent` control showing the same file is readable outside the wrap. No coverage is lost: `/etc/shadow` stays unreadable through file permissions and the image's non-root guarantee, which the agent-image CI job asserts; what the old probe claimed to prove, the kernel denial, is what the new one proves;
- pairs each direct read with its link: `/proc/self/root` for a granted and a denied path, a `/proc/self/cwd` traversal, the tree's own `exe`, `cwd` and `fd` links (self and a same-sandbox sibling), a sibling's `root` for a granted and a denied path, PID 1's `cmdline`/`status` (readable) and `environ`/`root`/`cwd`/`exe`/`fd` target (refused), and an unsandboxed same-uid holder (started by the test with `docker exec -u agent`, its pid handed to the probe through the workspace) keeping a granted workspace file on fd 3 and a denied file on fd 4, both refused, its `environ` refused, its `cmdline` readable. Every denial is asserted to be `EACCES`: the probe records the error text, so a missing file or an I/O error never passes as a denial, and `docker exec -u agent` controls read PID 1's and the holder's entries outside the wrap. Records the stated residuals (`meminfo`, `/proc/sys`, a sibling's `environ`, a peer's pipe and open file reopened through its `fd` links) and bounds the pid namespace (PID 1 is `cplt`, few pids). Peer memory is probed from a child of the probe and from a sibling: asserted refused when the engine's `ptrace_scope` is 1 or higher, asserted open and the entrypoint's note present otherwise, with the value printed. Asserts read-only on a write the agent may do outside the wrap, its own `/proc/self/comm` (with a `docker exec` control that it succeeds there), and records Docker's read-only `/proc/sys` separately with a `docker exec -u root` control (the current value written back), so the two are not confused;
- launches with `--profile-dir` carrying only `managed/opencode.json` (`username` set to a sentinel; opencode v2 drops unknown keys) and asserts `opencode --standalone debug config` shows it under the wrap;
- runs `opencode --standalone session list`, then the shipped default mode: `opencode session list` against fresh session state, the registration's pid alive with command line `opencode serve --service`, an HTTP answer on the registered loopback URL, a second invocation keeping the registration id; every call under `timeout 90` with stderr captured to the workspace and printed when a check fails;
- ties the survivor check to this session's service: `docker top` on the agent container gives the engine-side pid of `opencode serve --service` (anchored on the opencode binary, so neither a wrapper nor the client matches; the `docker top` output is printed when nothing matches); a throwaway `--pid=host` container with no capabilities, as uid 65534, reads that pid's command line from the engine's process table before `tjor down` (a control: the inspection must see it) and after (it must be gone). The inspection prints a sentinel whenever it ran, so "no survivor" is asserted only on an inspection that ran and found the pid gone; a failed `docker run` has no sentinel and fails both checks. The same mechanism works on a Linux engine host and inside the Colima VM. Then it relaunches the session with the stale registration still in the persisted home and asserts a fresh service with a new id;
- in strict mode (`TJOR_LANDLOCK_TEST_STRICT=1`, set by CI) fails instead of skipping when the engine has no Landlock or the image has no `opencode`, and tells a failed Landlock probe (docker, image, entrypoint) apart from a probe that answered "no Landlock";
- never aborts silently: every field lookup, `docker exec` and `docker run` on the host side tolerates failure and is bounded by a timeout, so a broken step reads as a failed check that prints what it saw; comparisons go through helpers that never put probe or engine output into shell text; the probe's completion is asserted; the build's output is shown when it fails; cleanup covers every session the suite starts.

A new `landlock` job in `ci.yml` (`needs: agent-image`, strict) runs it; the ruleset on `main` must list the job by name before the pull request can merge (CONTRIBUTING "Repository settings", `tests/ruleset_consistency.sh`). Every check name is registered in `python/gen_boundary_matrix.py`: the denials and the managed config as adversarial rows, the controls, residuals and opencode lifecycle as functional rows. The existing fail-closed path covers the flags themselves: a cplt that refused them would fail the exec and `set -e` aborts the start (add-landlock-tier, decision 3).

**Measured where.** The suite ran green on Colima (arm64, kernel 6.8, Landlock ABI 4, `kernel.yama.ptrace_scope=1`) from this branch, and on the Linux CI runner (x86_64, `ptrace_scope=1`) by the strict `landlock` job. The falsification (the released 0.23.0 image's cplt with the same flags minus the grants: child denied, both opencode launches aborting, managed sentinel absent; and the `--allow-write /proc` mutation letting the `comm` write through) was done by hand on Colima with the probe commands, not by CI. The peer-memory, pipe-reopen and DAC-control rows of D2 were measured by hand in a container with the launcher's capability set under the entrypoint's real wrap before the suite asserted them. The Yama-off case (`ptrace_scope=0` or no Yama) was not run on either engine; it follows from the kernel rule, the suite asserts it on such an engine, and the entrypoint states it there.

### D5. Nothing else in the wrap moves

`--allow-localhost-any`, `--inherit-env`, the home grant and the proxy port stay as decided in add-landlock-tier. The default service mode leaves `opencode serve --service` running (reparented to PID 1) after the client exits; it inherits the irrevocable ruleset and dies with the container, which D4 now measures; changing the shipped launch mode is a separate, user-visible decision.

### D6. The managed config directory is granted when it exists

`--allow-read /etc/opencode` is added when the directory exists (a grant on an absent path is a cplt warning; the entrypoint removes a stale managed file but may leave the directory). Read-only: the file is root-owned cargo and stays agent-immutable.

## Risks / Trade-offs

- [The agent reads the container kernel's status files and the cage's command lines] → measured and stated (D2); the command lines are tjor's or the agent's; an operator who passes a secret on a `docker exec` command line shows it to the agent, as on any shared machine.
- [A future cplt rejects or re-scopes `--allow-read /proc`] → the wrap fails to exec and the start aborts loudly (decision 3 of the tier); the strict CI suite catches a silent behavioural change at the next pin bump.
- [The offline opencode smoke depends on the CLI shape of the pinned opencode] → it is the CLI the image ships and pins; a later major that changes it fails the check visibly, which is the point of pinning.
- [The survivor check depends on `docker top` and `--pid=host`] → both are engine features present on a Linux host and in Colima; the before-down control fails loudly if either stops working, so a broken inspection cannot read as "no survivor".
- [A reader takes "Landlock denies outside the tree" literally and is surprised by `/proc`] → the README, spec, slide and ADR all name the grant.

## Migration Plan

Additive, ships with the next image build. Sessions already running are unchanged until relaunched. No config key changes. Rollback: `[landlock] mode = "off"` disables the tier without a rebuild (the #103 workaround, which this change makes unnecessary; remove it from profile configs once on the fixed image), or run the previous image tag.

## Open Questions

None blocking. Follow-ups filed separately: `--standalone` as the shipped opencode default; cplt pin bump (the 2026-11 releases add v2 session handling that tjor's `exec` mode does not use; the claims here are re-checked on each bump by the suite); an upstream note to Bun (graceful fallback when `/proc/self/maps` is unreadable; navikt/cplt PR 740 and its `/proc/self` deferred rule are the references).
