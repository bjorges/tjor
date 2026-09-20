# Proposal

## Why

Two low-cost hardening increments for this pass on #10 (the baseline is deliberately soft where production demands it — ADR 0004 — and is hardened in increments, each gated by the "harness still boots and does real daily work" regression plus the conformance suite):

1. **Bubblewrap is missing from the agent image.** The kernel-sandbox tier (#9) runs the harness under cplt with Landlock + seccomp, but every session logs `Bubblewrap unavailable … Using Landlock + seccomp only` and `UNIX sockets are NOT restricted … Landlock cannot gate connect(2) below ABI v9 (kernel 7.1) and Bubblewrap is not active`. Per the #10 investigation (2026-09-14): in tjor's current config this is **defense-in-depth, not an active vulnerability** — the agent container mounts no docker socket, runs no D-Bus session bus, and gets no forwarded `SSH_AUTH_SOCK`, so the specific sockets the warning names aren't live exposures. But closing the general UNIX-socket `connect(2)` enforcement hole on older kernels is worth doing, and the alarming-but-unactionable warning firing every session is worth silencing.
2. **The agent's process count is unbounded.** The agent container has a memory limit (`mem_limit`) but no process-count limit, so a runaway or fork-bomb in the (untrusted) harness process tree is unbounded on that axis.

## What Changes

- **Ship bubblewrap in the agent image.** Add `bubblewrap` to the agent Dockerfile's existing `apt-get install -y --no-install-recommends` line — apt's own repo signing covers it (same trust tier as `git`, `curl`, etc. already installed that way; no sha256 gate needed, unlike the release-tarball tools). cplt auto-detects `bwrap` at runtime and uses it with **no tjor-side flag or config** (per cplt's own auto-detect behavior), so the kernel-sandbox tier gains UNIX-socket `connect(2)` enforcement where the kernel needs bwrap, and the per-session "Bubblewrap unavailable" warning stops.
- **Bound the agent's process count.** Add `pids_limit` on the agent compose service, alongside the existing `mem_limit`, wired through the same knob pattern: `config/tjor.toml` `[limits] agent_pids`, exported by `bin/tjor` as `TJOR_AGENT_PIDS` (`cfg limits.agent_pids`), consumed as `pids_limit: ${TJOR_AGENT_PIDS:-…}`. The default is **generous** — real multi-process work (parallel builds, test runners) must be unaffected; the value is a DoS/fork-bomb ceiling, and any finite cap stops a runaway. Tunable per install.
- **Assertions.** CI's agent-image contract asserts `bwrap` is present in the built image; a `doc_consistency.sh` invariant asserts `pids_limit` is wired on the agent service. The **behavioral gate** — the harness still boots and does real work under both changes — is the existing live-session CI jobs (lifecycle, PTY, multi-repo), per #10's rule.

## Capabilities

### Modified Capabilities

(none — image + compose hardening with no tjor-side spec behavior change. cplt owns bubblewrap detection and the UNIX-socket enforcement; tjor only ships the binary. `pids_limit` is the same class as the existing, unspecced `mem_limit`. `.openspec.yaml` sets `skip_specs: true`. #10 remains open as the umbrella for future increments — this closes two of its candidates.)

## Impact

- **Code**: `images/agent/Dockerfile` (add `bubblewrap` to the apt-get install); `config/tjor.toml` (`[limits] agent_pids`); `bin/tjor` (`TJOR_AGENT_PIDS` via `cfg limits.agent_pids`, exported next to the `*_MEM` knobs); `compose.yaml` (`pids_limit: ${TJOR_AGENT_PIDS:-…}` on the agent service).
- **CI / tests**: `.github/workflows/ci.yml` (agent-image contract asserts `command -v bwrap`); `tests/doc_consistency.sh` (assert `pids_limit` wired on the agent service). The harness-still-works gate is the existing live-session jobs.
- **Behavior change**: the kernel-sandbox tier gains UNIX-socket `connect(2)` enforcement where the kernel supports bwrap (and the bwrap-unavailable warning stops); the agent container has a bounded process count. No change to the egress boundary, policy, credential handling, or any product behavior. Advances #10; the umbrella stays open.
