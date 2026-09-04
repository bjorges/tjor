# Clean-room charter: operational lessons tjor is built from

**Status:** living document · seeded 2026-09-04

tjor is a clean-room implementation (see [ADR 0003](decisions/0003-clean-room-provenance.md)). Its design decisions are not guesses: they reproduce patterns that multiple independent production systems — container cages and sandbox platforms the author has operated, studied, or read first-hand accounts of (e.g. Microsoft's public write-up of Azure SRE Agent's security architecture, Tech Community, 2026-08) — converged on. This file records that knowledge as **requirements and lessons**, never as code, so tjor can be built from this charter, OSS documentation (Docker, Compose, mitmproxy, CoreDNS, cplt, LiteLLM), and first principles alone.

The unifying thesis, reached independently by every reference system: **the environment is the policy.** Prompt text is advisory; harness permissions are harness-specific; only the structural boundary holds for any harness, including one running with its own permission checks disabled.

## Egress & network

- **L1.** An internal-only Docker network has no DNS. A DNS sidecar on the internal network is required, or every hostname lookup fails before the proxy is even consulted.
- **L2.** The egress proxy must be **dual-homed** — one interface on the internal network (where the agent reaches it), one on a routable network. `--publish` alone is inbound-only and gives the proxy no way out.
- **L3.** Allowlist evaluation needs an explicit, tested precedence: host blocklist → path-level allow carve-outs → path-level blocks → default mode. A config that fails to parse must **deny everything**, and that fail-closed behavior must have a unit test.
- **L4.** One glob/host matcher shared by every component (launcher preview, debug CLI, in-proxy addon), with a **parity test** asserting identical verdicts across call sites — divergent matcher implementations produce silent policy drift.
- **L5.** The harness vendor's own hosts deserve path-level treatment: allow docs/config endpoints, block gateway/telemetry endpoints — the harness works but doesn't phone home.
- **L6.** Corporate TLS interception (e.g. Cisco Umbrella) means a corporate CA must be bakeable into the image trust store via user-side overlay config, or nothing egresses on some networks.
- **L21.** DNS is an egress channel the HTTP-layer allowlist never inspects. A DNS sidecar that forwards `.` unconditionally lets any blocked host still resolve and lets data leave via query labels. Restrict forwarded zones to what the allow-policy needs (derive from allow-hosts in strict-allow mode; require an explicit zone list in default-allow mode); unlisted zones fail closed (local NXDOMAIN), never forward through.
- **L22.** Path-level rules must normalize percent-encoding and `.`/`..` segments before matching, and the two rule types must be **asymmetric**: a block rule fires if *any* encoded/decoded form matches (can't be evaded by encoding); an allow rule — especially a carve-out overriding a host block — fires only if *all* forms match (can't be widened by encoding). Symmetric matching on both sides is itself the vulnerability.
- **L25.** If a MITM CA is ever installed into the container trust store, constrain it: `basicConstraints=critical,CA:TRUE,pathlen:0` + `extendedKeyUsage=serverAuth`. Without `pathlen:0`, disclosure of the CA key yields delegable intermediate-CA-minting capability rather than direct-leaf-only interception.
- **L28.** Create a dual-homed sidecar on the egress (non-internal) network **first**, then `docker network connect` the internal network **second** — a published port, and any address the sidecar derives from its own default route, resolve against the network it was created on, not one attached afterward.

## Auth flows inside an internal-only container

- **L7.** Browser-based OAuth login (e.g. `az login`) breaks inside an internal-only container twice over: no browser, and the redirect listener binds an ephemeral port inside the container. Working pattern: pin the redirect listener to a **fixed port** inside the container and run a small host-side TCP relay forwarding it, so the host browser completes the flow. Device-code flow is the fallback where policy allows.
- **L29.** A network alias, DNS name, or other identifier shared across concurrently-running sessions is a session-identity bug waiting to happen: embedded DNS resolves a shared alias to an *arbitrary* attached holder, so a security-sensitive callback (an OAuth redirect, a credential handle) can misroute between concurrent sessions. Route callbacks to per-session-scoped names, and keep any relay for them operator-invoked and short-lived, not backgrounded and tied to unrelated container lifecycle.

## Image & build hygiene

- **L8.** Tool versions live in config, not hardcoded in the Dockerfile; inject them as default-less ARGs placed immediately before the RUN that uses them (BuildKit cache-key locality), and resolve any "latest" against the upstream registry at build time so builds are reconstructible.
- **L9.** Build-time tokens go through BuildKit secret mounts, never layers — and verify by grepping the built image filesystem for the token.
- **L10.** Whitelist-style `.dockerignore`: deny all, explicitly re-include every COPY source. Prevents state dirs and credentials leaking into build context.
- **L11.** Pin sidecar images by digest.
- **L12.** Stamp sidecars with a config-hash label and recreate on drift — otherwise config changes silently fail to apply to already-running sidecars.
- **L23.** Every build-time binary download needs a checksum/digest verification gate before unpacking, with an honest threat model documented (it catches corruption and CDN mismatch; it does **not** prove publisher authenticity if the transport terminates at a corporate TLS-inspection proxy, L6). Prefer publisher-published checksum files; fall back to pinned per-arch digests. Hash-pin pip installs (`--require-hashes`) for anything touching credential handling; pin git-based tool installs to a commit SHA, not a mutable tag.

## Harness & session state

- **L13.** Disable harness self-update inside the image (notify-only): self-update can corrupt the session database mid-session and fights read-only install paths. Harness version bumps happen by image rebuild.
- **L14.** Bind-mount the harness's XDG state dirs from a per-session state root so sessions and auth survive container recreation; the container itself stays disposable.
- **L15.** Map the host working directory to the **same path** inside the container — harnesses scope project context and session history to cwd, so a path mismatch corrupts session association. Resolve the project root via `git rev-parse --show-toplevel`, never `$PWD` string manipulation.
- **L16.** Agent instructions are image cargo: re-deploy prompts/skills from the image into the harness config dir on **every container start**, so instructions are versioned with the image, not mutable user state.
- **L17.** Provide tiered reset (cache / sessions / creds / all) with `--dry-run` — wiping state is routine, and ad-hoc wiping destroys the wrong things.
- **L27.** A cache or state directory the sandbox can write must never be read by a host-side tool that deserializes it unsafely (pickle-like formats, `eval`). Give the sandbox-side cache a distinctly-named directory/env-var so a host tool's existing env var can't silently become the sandbox's mount.

## Credentials

- **L26.** Any host-side script that opens a path inside a session's agent-writable bind mount (to copy out a credential, initialize a file, publish a token) must check for and refuse a symlink at that path before `cp`/`rm` — the agent controls what's there. Check at **every** touch point, not just the first: a background GC pass is a second touch point.
- **R1.** Secret placeholder pattern (observed as a product feature in a public sandbox tool): real tokens held host/proxy-side; the sandbox sees a placeholder substituted per destination host. Design target for the tjor broker, strengthened by the handle model below.
- **Handle model** (from Azure SRE Agent's public architecture): tools receive **opaque credential handles** — call-bound, destination-locked, scope-limited, single-use — exchanged for the real credential only at the egress-proxy boundary. The sandbox can *use* credentials, never *possess* them: the real value never enters its filesystem, env, process memory, tool output, or model context.
- **Discovered-secret risk** (same source, production incident): an agent can find an *already-committed* secret in repo content or tool output, quote it, and persist it in summaries/memory — a secret the platform never issued. Credential isolation does not cover this class; it needs a separate scrubbing/redaction mechanism. Open design item.

## Platform, launcher & verification

- **L18.** Kernel-LSM hardening (e.g. AppArmor) needs a runtime that supports it (works under Colima on macOS; not Docker Desktop). The launcher must detect availability and **degrade loudly**, stating which guarantees are inactive — never silently.
- **L24.** A "profile loaded" check for any kernel LSM must verify both **mode** (enforcing, not complain) and **content** (hash of the currently-loaded policy vs. what current config would produce) — checking only for the profile's name in status output has failed silently in practice.
- **L19.** Every entry point merges config through one shared function. Observed failure mode: two scripts merging different subsets of config sections, silently dropping overrides.
- **L20.** Check host dependencies up front (bash ≥ 4.4, `yq`, `envsubst`, GNU coreutils) with clear errors — the launcher is the first thing a new user runs on a heterogeneous machine.
- **L30.** Any sidecar with a management/admin API (a proxy's web UI, an LLM gateway's admin endpoint) must be unreachable from the agent's network **by construction**, not gated by a password alone. Generate any such credential per-install (never ship one in checked-in config), never print it to stdout, and never fold it into a config-hash label — labels are `docker inspect`-visible to any local process.

## Requirements evidenced by peer systems

- **R2.** Declared port publishing for dev servers is a first-class need for front-end work.
- **R3.** Browser automation in-image (playwright + Chromium + the agent-facing skill) for a front-end profile; ephemeral-port allowances for Vite/Next-class dev tooling.
- **R4.** A curated baseline MCP-server set per image, recorded as a decision; org context injected into agent instructions at session creation (the same render-at-launch pattern as L16).

*(Lesson numbering is stable so specs and issues can cite entries; gaps in the sequence are intentional where original lessons merged.)*
