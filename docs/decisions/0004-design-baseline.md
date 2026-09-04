# ADR 0004 — Design baseline inherited from production-validated patterns

**Date:** 2026-09-04 · **Status:** accepted

These decisions are adopted up front rather than re-litigated per change, because multiple independent production systems converged on them (see charter). Each gets its own OpenSpec spec when implemented; this ADR records *what* and *why*.

- **Internal-only agent network** as the enforcement primitive. Capability drops, seccomp, and read-only rootfs do **not** prevent egress; network topology does.
- **Dual-homed egress proxy in explicit mode** (`HTTP(S)_PROXY`), not transparent mode. Proxy-aware CLIs expect it; transparent mode needs iptables redirection an internal bridge doesn't provide.
- **Fail-closed allowlist** with tested precedence (host blocks → path allows → path blocks → default) and a single shared matcher with parity tests across all call sites.
- **DNS sidecar with zone-scoped forwarding** — unlisted zones NXDOMAIN locally; DNS is an egress channel too.
- **Client-side identity injection** (env vars → harness config → gateway `extra_headers`); the proxy verifies and strips forgeries, never injects — header injection into TLS would require MITM the design doesn't want to depend on.
- **Vendor-neutral identity schema:** `x-agent-session-id`, `x-agent-task-id`, `x-agent-harness`, `x-agent-repo`, `x-agent-worktree`, `x-agent-parent-session`.
- **Writable repo mounts, non-root user** as the baseline profile. A `--read-only`/distroless posture contradicts what coding harnesses demonstrably need (subprocesses, PTY, native modules). Hardening lands as increments, each gated by a "harness still boots and does real work" regression test.
- **Tiered guarantees:** core (any Docker runtime) vs hardening add-ons (runtime-dependent, e.g. AppArmor). A missing add-on degrades **loudly**, never silently.
- **Compose-based topology** rather than hand-rolled scripting, for maintainability and shareability.
