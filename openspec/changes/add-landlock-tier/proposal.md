# Add the Landlock kernel-sandbox tier

## Why

The container boundary stops host access and unproxied egress, but inside the cage everything is one flat trust domain: the agent process can read any file the container can see — including in-repo secrets such as `.env` — with nothing constraining it at the kernel level. Issue #9 proposed running cplt's Landlock backend inside the cage as a defense-in-depth tier, gated on one open question: does Landlock work in an unprivileged container on the Docker VM kernel?

That question is now settled empirically (issue #9 thread, 2026-09-13): on the current Docker endpoint (Ubuntu 24.04 VM, kernel 6.8, default builtin seccomp profile, unprivileged container) `landlock_create_ruleset` reports ABI v4 and end-to-end enforcement works (`no_new_privs` → ruleset → `landlock_restrict_self` → denied read returns `EACCES`). No seccomp or capability changes are needed: Docker's default profile has allowed the three landlock syscalls since Docker 23.0 (moby/moby#43199), and the agent service already runs with `no-new-privileges:true` — exactly the precondition `landlock_restrict_self` requires. The tier is buildable today; availability on *other* operators' runtimes (Docker Desktop LinuxKit, Colima, gVisor) varies, which is why probing and loud degradation are part of the contract, not an afterthought.

## What Changes

- The agent image gains `cplt` (github.com/navikt/cplt, MIT — a Rust binary whose Linux backend enforces Landlock + seccomp-BPF), installed from a pinned GitHub release through the image's existing sha256 gate, exactly like `gh` and `kubectl`.
- The agent entrypoint probes Landlock availability at container start. When available, it execs the harness *under* cplt so the whole harness process tree runs behind an irrevocable kernel ruleset that denies filesystem access **outside the granted trees** (workspace, extra repos, harness state, system paths). When unavailable, it degrades **loudly**: a persistent, explicit statement that the kernel-sandbox tier is inactive, then normal startup — the container boundary remains the core guarantee.
- The probe treats **any** failure as tier-unavailable — `ENOSYS` (kernel too old / syscall filtered), `EOPNOTSUPP` (compiled in but disabled at boot), `EPERM` (hardened seccomp profile), or anything else. Never silent.
- **Workspace secret masking (hybrid, revised during implementation):** Landlock is allowlist-only — it cannot deny a path inside a granted tree, so cplt's in-workspace `.env` deny is unenforceable on Linux in a container (cplt states this at runtime; its bubblewrap fallback needs user namespaces, which Docker's default seccomp blocks in a `cap_drop: ALL` container). Issue #9's motivating example — in-repo `.env` reads — is therefore delivered by a second, runtime-independent mechanism: at launch, the launcher bind-mounts read-only `/dev/null` over each dotenv-style secret file present in the mounted repos. Masks work on every runtime, even where Landlock is unavailable, and a mount target cannot be unlinked or replaced by the agent.
- A new `[landlock]` config section controls the tier: `mode = "auto"` (default: enforce when available, degrade loudly otherwise), `"require"` (unavailable aborts the launch — promotes the add-on to a core guarantee), `"off"` (kernel tier disabled, stated at launch); `mask_dotenv = true` governs the launch-time secret masks and `deny_paths` extends the mask set. Config flows through the existing single merge path.
- cplt's *network* layer stays disabled: tjor's egress proxy is the sole network boundary, and the harness's `HTTP(S)_PROXY` environment must pass through the wrap unchanged.
- A conformance probe asserts the tier's actual behavior: with the tier active, a read of a denied path fails; with the tier unavailable, the degradation statement is present.

Assumption recorded: the tier defaults to **on** (`mode = "auto"`) — issue #9's framing is a hardening tier tjor *gains*, and `auto` cannot break launches on runtimes without Landlock because it degrades loudly. Operators who hit workflow friction from filesystem denies (e.g. a dev server legitimately reading `.env`) can set `mode = "off"` or tune deny paths.

## Capabilities

### New Capabilities

- `kernel-sandbox`: the in-cage kernel filesystem-deny tier — availability probe semantics, harness wrapping, degradation modes (`auto`/`require`/`off`), what the operator sees in each state, and the invariant that the tier never replaces or weakens the container boundary and never becomes a second network policy.

### Modified Capabilities

- `cage-image`: the image contract gains a requirement that `cplt` is present, version-pinned from config, and checksum-gated at build — parallel to the existing kubectl requirement.

No delta to `session-launch`: its existing "Tiered guarantees degrade loudly" requirement (scenario: *Runtime without LSM support*) already anticipated exactly this tier; `kernel-sandbox` instantiates that contract rather than changing it. Config plumbing rides the existing "Single config merge path" requirement unchanged.

## Impact

- **Code**: `images/agent/Dockerfile` (cplt install stage), `images/agent/entrypoint.sh` (probe + wrapped exec at the final gosu handoff), `config/tjor.toml` (`[landlock]` section; `[versions]`/`[versions.sha256]` entries), `bin/tjor` (config → `TJOR_LANDLOCK*` env plumbing; launch-time dotenv mount masks in `run_agent`), `compose.yaml` (agent service env passthrough), `images/conformance/probes.py` (tier probe).
- **Dependencies**: adds cplt (MIT, single static binary, date-tagged releases with per-arch Linux tarballs + `SHA256SUMS`; latest at proposal time: `2026.09.13-135112-daf7f1f`). MIT matches the ecosystem per ADR 0001.
- **Systems**: no new sidecars, networks, mounts, or capabilities; no change to the proxy, DNS, broker, or gateway. Runtime behavior change is confined to the agent process tree.
- **Compatibility**: not breaking. On runtimes without Landlock, `auto` behaves as today plus a loud notice. Existing sessions are unaffected until their image is rebuilt.
