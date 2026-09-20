# Design

## Context

See proposal.md — Why, and #10's 2026-09-14 investigation comment. Grounding in the repo:

- The agent image base is `debian:trixie-slim` (digest-pinned, `config/tjor.toml`), which carries a `bubblewrap` apt package. `images/agent/Dockerfile` already installs distro packages via one `apt-get install -y --no-install-recommends` (line 9: `ca-certificates curl git openssh-client jq ripgrep less procps gosu python3 unzip`), trusting apt's repo signing — distinct from the release-tarball tools (cplt, kubectl, the harness) which are sha256-gated build args.
- `cplt` (the kernel-sandbox tool, #9) is already in the image; at runtime it auto-detects `bwrap` and uses it, with no tjor flag. Today it logs `Bubblewrap unavailable … Using Landlock + seccomp only`.
- Resource limits follow one pattern: `config/tjor.toml [limits] <svc>_mem` → `bin/tjor` `TJOR_<SVC>_MEM="$(cfg limits.<svc>_mem --default …)"` (exported) → `compose.yaml` `mem_limit: ${TJOR_<SVC>_MEM:-…}`. The agent has `mem_limit: ${TJOR_AGENT_MEM:-4g}` but no `pids_limit`.
- `compose.yaml` is run via the standalone `docker-compose` (v2 file schema); `pids_limit` is a supported top-level service key there (no swarm/`deploy:` needed).
- CI's `agent-image` job runs an "image contract" step (`command -v <binary>` in the built image) across the harness matrix — the place to assert `bwrap`. Live-session jobs (lifecycle, PTY, multi-repo) run the agent for real — the behavioral gate.

## Goals / Non-Goals

**Goals:**
- Close the UNIX-socket `connect(2)` enforcement hole where the kernel needs bwrap, and stop the per-session warning.
- Bound the agent's process count without breaking real multi-process work.
- Keep both changes gated by the existing suites (#10's rule).

**Non-Goals:**
- No tjor-side bubblewrap flag, probe, or status reporting — cplt owns detection and enforcement, and reports its own status on the `[cplt]` log line (mirrors how Landlock status is cplt's to report).
- No other #10 candidate this pass (seccomp profile, read-only subpaths, git-hooks LSM deny, LSM verification at launch) — #10 stays open.
- No conformance probe for bubblewrap/socket enforcement (see Decision 3).

## Decisions

1. **Bubblewrap via apt, no sha256 gate.** It joins the existing `apt-get install` line, trusting apt repo signing — the same trust tier as `git`/`curl`/`openssh-client` already there. The release-tarball tools are sha256-gated because they bypass apt; a distro package does not, so gating it would be inconsistent and pointless. cplt picks it up automatically.
2. **`pids_limit` mirrors the `mem_limit` knob exactly.** `[limits] agent_pids` in config, `TJOR_AGENT_PIDS` via `cfg limits.agent_pids` exported beside the `*_MEM` knobs, `pids_limit: ${TJOR_AGENT_PIDS:-4096}` on the agent service. Default **4096**: generous headroom for parallel builds / test runners (a coding agent rarely holds thousands of processes at once), while any finite cap defeats a fork bomb — so the security value is insensitive to the exact number, and the number is chosen to protect real work, not to be tight. Env-tunable; if a heavy live-session CI job (multi-repo) ever trips it, raise `limits.agent_pids` rather than lowering the guard.
3. **No conformance probe for the socket enforcement; the existing suites gate it.** A probe asserting UNIX-socket `connect(2)` denial would be non-deterministic: the enforcement only engages below Landlock ABI v9 (on a modern CI kernel Landlock itself gates sockets, so bwrap may not be the active mechanism), and there's no meaningful in-cage socket to probe (no docker/D-Bus/SSH socket). So coverage is: CI asserts `bwrap` is *present* in the image (a build contract), and the live-session jobs prove the harness still works with it active. Honest about what's checked (presence + no-regression), not a false socket-denial claim.
4. **`pids_limit` presence is lint-asserted; its safety is regression-gated.** A `doc_consistency.sh` grep asserts the agent service carries `pids_limit` (so it can't be silently dropped); whether the default is high enough is proven by the live-session jobs booting and working under it.

## Risks / Trade-offs

- [A too-low pids cap breaks real work] → default chosen generous (4096) and env-tunable; the live-session CI jobs are the empirical gate. Any finite cap still stops a fork bomb, so erring generous costs no meaningful security.
- [Socket enforcement is kernel-ABI-dependent] → stated honestly: it engages where bwrap is the needed mechanism (older kernels); on newer kernels Landlock already covers it. Either way the tier is strictly additive — bwrap removes nothing.
- [Image grows slightly] → `bubblewrap` is a small package; acceptable for closing the gap and silencing the warning.

## Migration Plan

Additive: one apt package, one config knob + export, one compose key, two assertions. No spec/policy/product-contract change. Rollback is a plain revert (cplt falls back to Landlock+seccomp; the pid cap disappears). Patch release. The agent image is rebuilt/republished per release, so the change reaches sessions on the next `tjor run` (pull) or rebuild.

## Open Questions

- None material. The pids default is empirically confirmable only in CI (no local Docker here); if a live-session job trips it, bump `limits.agent_pids`.
