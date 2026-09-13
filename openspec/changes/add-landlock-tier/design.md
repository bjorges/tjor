# Design: add-landlock-tier

## Context

See proposal.md → Why for motivation and the feasibility evidence. Constraints that shape the approach:

- **Single wrap point exists.** Every harness passes through the entrypoint's final handoff — `exec gosu agent env HOME=… USER=agent "$@"` (`images/agent/entrypoint.sh:249`). Wrapping there covers the whole harness tree for any harness (opencode/claude/copilot) with one change.
- **Preconditions are already met.** The agent service runs with `security_opt: ["no-new-privileges:true"]` and `cap_drop: [ALL]` (`compose.yaml:117-119`); `landlock_restrict_self` requires exactly `no_new_privs`. Docker's default seccomp profile allows the three landlock syscalls since 23.0 (moby/moby#43199) — no compose changes needed.
- **cplt's shape.** Single static Rust binary; Linux backend is Landlock + seccomp-BPF; wraps an arbitrary command; per-arch release tarballs with a `SHA256SUMS` file, date-based tags (latest at writing: `2026.09.13-135112-daf7f1f`). Crucially, **cplt fails hard when its backend is unavailable** — it will not run unsandboxed. That hard-fail is what `require` mode wants, but `auto` mode needs tjor's own probe *before* deciding to wrap.
- **Existing plumbing patterns.** Config flows host→container as `TJOR_*` env through one merge path (`bin/tjor` + `python/tjor_cfg.py` → `compose.yaml` agent environment). Multi-value paths use newline separation (`TJOR_SAFE_DIRS` precedent, entrypoint step 3). Build pins live in `config/tjor.toml` `[versions]`/`[versions.sha256]` and arrive as Dockerfile ARGs (gh/kubectl pattern).
- **Empirical findings from the pinned cplt in the built image (revision driver).** (1) Landlock is allowlist-only: cplt's `.env`/`--deny-path` denies are *not enforced* on Linux without bubblewrap, and cplt warns so at runtime; bubblewrap needs user namespaces, which Docker's default seccomp blocks under `cap_drop: ALL` — dead end in-cage on any runtime. (2) By default cplt starts its own CONNECT proxy and rewrites `HTTP(S)_PROXY`, strips `NO_PROXY`/`TJOR_*`/lowercase proxy vars from the env, and its Landlock net rules block outbound TCP to non-443 ports — including the tjor proxy port. (3) `cplt exec` grants neither `$HOME` nor the harness state dirs. All of these are correctable by flags (verified): `--no-proxy --no-gh-guard --no-git-guard --inherit-env --pass-env http_proxy/https_proxy/no_proxy --allow-port <proxy port> --allow-localhost-any --allow-read/--allow-write` grants. Outside-tree reads and writes are then genuinely kernel-denied with the cage env intact, and `opencode`/`gh` run normally under the wrap.

## Goals / Non-Goals

**Goals:**
- Kernel FS-deny enforcement for the harness process tree, on by default where the runtime supports it.
- Probe-before-wrap so `auto` mode can degrade loudly instead of inheriting cplt's hard failure.
- Tier status legible after the fact (`docker logs`) and at attach, in both the active and degraded states.

**Non-Goals:**
- cplt's network proxy and command-guard layers — tjor's egress proxy is the sole network boundary; enabling a second one would create split policy.
- Landlock for the sidecars (proxy/dns/gateway) — they are not agent-controlled and already run `cap_drop: ALL`.
- Host-side (macOS Seatbelt) sandboxing — tjor's model is the container; cplt-on-host is a different product's job.
- Config that *weakens* the default deny list (`--allow-read`-style loosening) — deferred until a concrete workflow needs it; config only extends denies in this change.

## Decisions

### 1. Probe: a self-contained syscall probe in the entrypoint, not `cplt doctor`

A ~10-line `python3` ctypes probe (python3 is already image cargo) calls `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)` and classifies **any** error as unavailable, reporting the errno. It runs via `gosu agent` so the probe context equals the enforcement context (post-uid-alignment, unprivileged).

*Alternative considered:* `cplt doctor`. Rejected as the probe: its output format and exit codes are not a stable contract across cplt's fast date-tagged releases, and the probe must be able to say *why* (errno) for the degradation message. cplt remains the enforcer; tjor owns the availability decision.

### 2. Wrap: conditionally rewrite the final exec

Entrypoint step 5 becomes a three-way branch on `TJOR_LANDLOCK` (mode) + probe result:

- active → `exec gosu agent env HOME=… cplt <fs-only flags> -- "$@"`
- degraded (`auto`, probe failed) → current exec, preceded by the persistent `INACTIVE` statement
- `off` → current exec, preceded by a one-line disabled-by-config statement
- `require` + probe failed → `FATAL` + `exit 1` (same pattern as the existing non-root guarantee abort, `entrypoint.sh:33-36`)

The invocation is resolved (verified against the pinned release in the built image):

```
cplt --project-dir "${TJOR_WORKSPACE}" \
     --no-proxy --no-gh-guard --no-git-guard \
     --inherit-env --pass-env http_proxy --pass-env https_proxy --pass-env no_proxy \
     --allow-port "${TJOR_PROXY_PORT}" --allow-localhost-any \
     --allow-read /home/agent --allow-write /home/agent \
     [--allow-write <each extra mounted repo>] \
     exec -- "$@"
```

Rationale per flag: `--no-proxy` (tjor's egress proxy is the sole network boundary; cplt otherwise starts its own CONNECT proxy and rewrites `HTTP(S)_PROXY`); `--no-gh-guard --no-git-guard` (no third policy layer — action policy is the proxy's); `--inherit-env` + `--pass-env` for the lowercase proxy vars (the cage env is load-bearing and holds no real secrets by construction — broker/gateway values are placeholders; cplt's sanitizer strips `NO_PROXY`, `TJOR_*`, and lowercase proxy vars otherwise); `--allow-port` (the harness must reach the egress proxy; cplt's Landlock net rules otherwise allow only 443); `--allow-localhost-any` (dev servers/MCP inside the cage are tjor-legal today; the tier must not restrict them — and cplt states on Linux this drops ALL its Landlock TCP-connect rules, which is exactly the spec's "no second network policy": the internal-only network and the egress proxy already own that boundary, so `--allow-port` becomes redundant-but-harmless); home granted wholesale (the session home holds no host secrets by design, and per-dir grants proved brittle — a missed dir breaks a harness mid-session; on Linux the write⇒exec separation is macOS-only anyway, per cplt's own warning).

### 2b. Dotenv masking is launcher-side bind mounts, not Landlock (hybrid revision)

Landlock cannot deny a path inside a granted tree, so issue #9's motivating example (in-repo `.env` reads) is delivered by the launcher instead: at `run_agent`, for the workspace and each `--dir` repo, find `.env` / `.env.*` files (excluding `.env.example|sample|template`, skipping `.git`) plus every `[landlock].deny_paths` entry that exists, and add a `--volume /dev/null:<path>:ro` mount per match. Host path == container path for repo mounts, so the host-side glob is the container truth. Bind-mount targets cannot be unlinked or replaced from inside the container (`EBUSY`), reads return empty, and the ro flag denies writes. Governed by `[landlock].mask_dotenv` (default `true`), stated loudly at launch (`tjor: + dotenv mask <path>`). Residual, documented honestly: a dotenv file *created mid-session* is not masked — masks are a launch-time snapshot.

*Alternative considered:* relying on cplt's `--deny-path`/`allow_env_files`. Rejected: not enforced on Linux without bubblewrap (cplt's own runtime warning), and bubblewrap cannot run in a `cap_drop: ALL` container (userns blocked by the default seccomp profile).

### 3. Fail closed after a passing probe

If the probe said available but `cplt` then fails to start the harness, the container start fails — no silent unwrapped fallback. The one forbidden outcome is a session that looks sandboxed and isn't. (`exec` semantics give this for free: a failed exec of the wrapper aborts the script under `set -e`.)

### 4. Config and env plumbing

`[landlock]` in `config/tjor.toml`: `mode = "auto"` (default), `mask_dotenv = true`, and `deny_paths = []` (extra launch-time mask paths). Launcher exports `TJOR_LANDLOCK` (mode string) to the agent service via `compose.yaml`; `deny_paths` and `mask_dotenv` are consumed launcher-side (masking happens at mount assembly, not in the entrypoint). Mode validation happens in the entrypoint (it is the enforcement point and must reject an unknown value anyway); the launcher additionally pre-validates for a friendlier error.

*Alternative considered:* launcher-side pre-probe via a one-shot `docker run` so `require` aborts host-side before compose. Rejected: an extra container start on every launch, duplicated probe logic, and the entrypoint abort already surfaces through the attach output — matching how the non-root guarantee aborts today.

### 5. Version pinning follows the kubectl pattern exactly

`[versions] cplt = "<date-tag>"`, `[versions.sha256] cplt_linux_arm64/amd64` (values from the release's `SHA256SUMS`); Dockerfile gains `CPLT_VERSION`/`CPLT_SHA256_*` ARGs and a sha-gated install block for `cplt-{aarch64,x86_64}-unknown-linux-gnu.tar.gz`. Installed unconditionally (like kubectl), independent of `HARNESS`.

### 6. Status line format is a contract

`tjor-entrypoint: kernel-sandbox: active (landlock ABI <n>)` / `kernel-sandbox: INACTIVE — <errno/reason>; sessions run without the kernel FS-deny tier` / `kernel-sandbox: disabled by config (mode=off)`. One greppable prefix (`kernel-sandbox:`) that the conformance probe and `docker logs` consumers key on.

## Risks / Trade-offs

- [Masking breaks a legitimate workflow — e.g. a dev server the agent runs reads the workspace `.env`] → deliberate: that read is precisely what issue #9 wants stopped. Escape hatches: `mask_dotenv = false`, or `mode = "off"` for the kernel tier. Loosening-style config beyond those toggles is explicitly deferred.
- [A dotenv file created mid-session is not masked] → documented residual: masks are a launch-time snapshot. The kernel tier cannot close this (Landlock cannot deny in-tree paths); honest docs over false comfort.
- [cplt CLI surface drifts across date-tagged releases] → version is pinned and only moves by explicit config bump; conformance asserts behavior (denied outside-tree access, masked dotenv, status line), so a bump that changes flags fails visibly at test time, not silently in the field.
- [cplt's seccomp-BPF layer stacks under Docker's builtin filter and could deny a syscall a harness needs] → filters compose (both must allow); mitigated by running the full conformance/harness smoke under the wrap before release. Verified so far: `opencode`, `gh`, `git`, `python3` run normally under the wrap.
- [Probe/enforcement divergence — probe passes, wrap fails] → Decision 3: fail closed, loudly. Never claim-then-degrade silently.
- [Agent-authored files could try to confuse the status surface (fake status lines in logs)] → the status line is emitted by the entrypoint before the harness starts; conformance reads the entrypoint's own output ordering, and the tier's *enforcement* is verified by an actual denied access, not by trusting the line.
- [cplt startup warnings are noisy (≈9 stderr lines per start)] → accepted: they are honest statements of what is and is not enforced, printed once per session start; suppressing them would hide exactly the honesty tjor values.

## Migration Plan

Purely additive. Ships in the next image rebuild; existing sessions are untouched until relaunched on the new image. Default `auto` cannot abort a launch on any runtime. Rollback: set `mode = "off"` (no rebuild needed) or run the previous image tag.

## Open Questions

- Renovate tracking for the cplt pin (`renovate.json` custom manager for `[versions]`) — nice-to-have follow-up, not required for the tier to ship.
- Whether extra `--dir` repos should be granted via `--repo-dir` (adds exec within the tree) instead of `--allow-write` (no exec) — start with `--allow-write` and promote if a real build-inside-extra-repo workflow needs it.
