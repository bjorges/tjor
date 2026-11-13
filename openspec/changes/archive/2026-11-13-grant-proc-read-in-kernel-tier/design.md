# Design

## Context

The kernel-sandbox tier runs the harness under `cplt exec` with a Landlock ruleset built from the flags in `images/agent/entrypoint.sh` (add-landlock-tier, decision 2). cplt's Linux backend without Bubblewrap adds one rule for `/proc/self`, resolved in the child before `exec`: Landlock rules are attached to inodes, and `/proc/self` resolves to the `/proc/<pid>` directory of the process that opens it, so the rule covers the first sandboxed pid and no other (`sandbox_landlock.rs`: "Paths under /proc/self are magic symlinks that resolve to /proc/<pid>"). cplt grants all of `/proc` only under Bubblewrap, where a private pid namespace makes the grant harmless, or with `--allow-jvm-attach`.

Measured in the released 0.23.0 image on Colima (kernel 6.8, Landlock ABI 4, pinned cplt 2026.09.13), with the entrypoint's flag set:

- the first sandboxed process reads `/proc/self/maps`; a forked child gets `Permission denied` on its own;
- opencode 2.2.7 spawns `/usr/local/bin/opencode serve --stdio --port 0` (standalone) or `serve --service` (default), and that child aborts about 1 ms after exec: `panic(main thread): abort() called`, trace `JSC::VM::tryCreate` ← `Zig__GlobalObject__create` ← `boot_standalone`;
- adding `--allow-read /proc` makes `run ping`, `session list`, `debug config` and `models` succeed, the last three with networking disabled;
- the newest cplt (2026.11.06) behaves the same in `exec` mode and prints: "Without Bubblewrap only the agent's first process can read its own /proc/self ... Install bubblewrap, or pass --allow-read /proc if that is acceptable";
- the Claude image's `claude` binary is a Bun standalone executable as well.

Bubblewrap is not an option in-cage: it needs an unprivileged user namespace, which Docker's default seccomp profile blocks under the container's `cap_drop: [ALL]` / `no-new-privileges` posture (Dockerfile note for #10; the v0.18.15 attempt was reverted).

## Goals / Non-Goals

**Goals:**
- Every process in the harness tree can read its own `/proc/self`, so Bun-compiled harnesses and their children start under the tier.
- The grant is the smallest one that does this, read-only, and its residual is measured and stated.
- A regression check that launches opencode v2 under the real wrap, offline, in CI.

**Non-Goals:**
- Bubblewrap, user namespaces or any change to the container's capability posture.
- Per-harness or per-mode wrap flags (the failure class is "any Bun or Node child", not "opencode v2").
- Changing the shipped opencode launch mode (`--standalone`), the cplt pin, or the egress and network layers.

## Decisions

### D1. The wrap grants `/proc` read-only, for every harness and launch mode

`images/agent/entrypoint.sh` adds `--allow-read /proc` to the `wrap` array, unconditionally. Rationale: Landlock has no wildcard, so there is no way to grant each future child its own `/proc/<pid>` ahead of time; cplt's own answer under Bubblewrap is the same whole-tree read grant; the trigger is the runtime (Bun, and Node.js reads the same files), not the harness, so a per-harness flag would leave MCP servers and agent-installed tools broken under one harness and working under another. The grant is read-only: `/proc/sys` stays unwritable and Docker's masked `/proc` paths (`kcore`, `keys`, `timer_list`, ...) are unaffected because masking is a mount, not a Landlock rule.

*Alternatives considered:* running `opencode serve` under cplt from the entrypoint and attaching the client (the server's own children stay broken, and it adds a port, a readiness wait and a second lifecycle); skipping the wrap for opencode v2 (drops the tier for the harness that needs it most); `--allow-jvm-attach` (grants `/proc` too, but also `/tmp/.java_pid*` sockets, and says the wrong thing in the startup summary).

### D2. The container is the pid namespace cplt wants from Bubblewrap

cplt's warning is written for a host: "granting /proc would expose every host process's command line". In the cage, `/proc` is the agent container's procfs, in the container's own pid namespace. What is visible is PID 1 (cplt, after the `gosu`/`env` exec chain) and the harness tree itself; the proxy, DNS and gateway sidecars are separate containers. Measured with `/proc` granted: the agent can list these processes and read their command lines (cplt's own wrap flags, which hold no secret); cplt's `environ` and `mem` are refused (`Permission denied`); `/proc/<cplt pid>/root` and `cwd` are refused outright, and the harness's own `/proc/self/root/<denied path>` is refused by Landlock the same way the direct read is. The environment the agent could in principle learn from PID 1 is the one it already receives through `--inherit-env`.

### D3. The invariant is a requirement, not a comment

The kernel-sandbox spec gains "Every process in the harness tree can read its own /proc entries", with the read-only grant, the magic-link invariant and the residual. The same sentence goes into the README and the slide's residual box, so a reader of any of the three learns that `/proc` is readable inside the tier and what that means. ADR 0015 records why a kernel grant was widened and what bounds it, in the same family as the Dockerfile's Bubblewrap note.

### D4. Proof: two checks in the live Landlock session

`tests/integration/landlock_test.sh` part A runs a probe script as the harness command under the real wrap, with the real proxy env, and reads findings back from the workspace. It gains:

- `child_proc_self`: a forked child (`sh -c 'cat /proc/self/maps'`, a new pid) reads its own maps; asserted `OK`;
- `opencode_standalone`: `opencode --standalone session list` exits zero with `OPENCODE_DISABLE_PROJECT_CONFIG=1`; needs no credentials or network (verified with `--network none`), and is exactly the launch that failed in #103; asserted `OK` (the probe writes `absent` when the image has no `opencode`, so a run against another harness image reports the gap instead of failing on a missing binary; the suite's default image is the opencode image, so CI exercises it);
- `proc_root_denied`: `/proc/self/root/etc/hostname` is refused like `/etc/hostname` itself (world-readable in the image, outside cplt's system grants); asserted `denied`.

Each name is registered in `python/gen_boundary_matrix.py`; the first two as functional rows, the third as an adversarial guarantee, and `docs/boundary-matrix.md` is regenerated. The existing fail-closed path covers the flag itself: if a future cplt refused `--allow-read /proc`, the wrap would fail to exec and `set -e` aborts the start (add-landlock-tier, decision 3).

### D5. Nothing else in the wrap moves

`--allow-localhost-any`, `--inherit-env`, the home grant and the proxy port stay as decided in add-landlock-tier. The opencode v2 default service mode leaves `opencode serve --service` running (reparented to PID 1) after the client exits; it inherits the irrevocable ruleset and dies with the container, so it is not a hole, and changing the launch default is a separate, user-visible decision.

## Risks / Trade-offs

- [The agent learns the cage's process list and command lines] → measured and stated as the residual; the processes are tjor's own and their command lines hold no secret (the proxy placeholder values travel in the environment the agent already has).
- [A future cplt rejects `--allow-read /proc` or changes its meaning] → the wrap fails to exec and the start aborts loudly (decision 3 of the tier); the live suite's `opencode_standalone` check catches a silent behavioural change at the next pin bump.
- [The offline `session list` smoke depends on opencode's CLI shape] → it is the same CLI the image ships and pins; a v3 that changes it fails the check visibly, which is the point of pinning.
- [A reader takes "Landlock denies outside the tree" literally and is surprised by `/proc`] → the README, spec and slide all name the grant.

## Migration Plan

Additive, ships with the next image build. Sessions already running are unchanged until relaunched. No config key changes. Rollback: the previous image tag.

## Open Questions

None blocking. Follow-ups filed separately: `--standalone` as the shipped opencode default; cplt pin bump (the 2026-11 releases add v2 session handling that tjor's `exec` mode does not use); an upstream note to Bun.
