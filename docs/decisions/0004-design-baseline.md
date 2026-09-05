# ADR 0004 — Design baseline inherited from production-validated patterns

**Date:** 2026-09-04 · **Status:** accepted, amended 2026-09-05 (identity injection — see below)

These decisions are adopted up front rather than re-litigated per change, because multiple independent production systems converged on them (see charter). Each gets its own OpenSpec spec when implemented; this ADR records *what* and *why*.

- **Internal-only agent network** as the enforcement primitive. Capability drops, seccomp, and read-only rootfs do **not** prevent egress; network topology does.
- **Dual-homed egress proxy in explicit mode** (`HTTP(S)_PROXY`), not transparent mode. Proxy-aware CLIs expect it; transparent mode needs iptables redirection an internal bridge doesn't provide.
- **Fail-closed allowlist** with tested precedence (host blocks → path allows → path blocks → default) and a single shared matcher with parity tests across all call sites.
- **DNS sidecar with zone-scoped forwarding** — unlisted zones NXDOMAIN locally; DNS is an egress channel too.
- **Client-side identity injection** (env vars → harness config → gateway `extra_headers`); the proxy verifies and strips forgeries, never injects — header injection into TLS would require MITM the design doesn't want to depend on. *(Amended 2026-09-05 — see below.)*
- **Vendor-neutral identity schema:** `x-agent-session-id`, `x-agent-task-id`, `x-agent-harness`, `x-agent-repo`, `x-agent-worktree`, `x-agent-parent-session`.
- **Writable repo mounts, non-root user** as the baseline profile. A `--read-only`/distroless posture contradicts what coding harnesses demonstrably need (subprocesses, PTY, native modules). Hardening lands as increments, each gated by a "harness still boots and does real work" regression test.
- **Tiered guarantees:** core (any Docker runtime) vs hardening add-ons (runtime-dependent, e.g. AppArmor). A missing add-on degrades **loudly**, never silently.
- **Compose-based topology** rather than hand-rolled scripting, for maintainability and shareability.

## Amendment 2026-09-05 — proxy-side identity injection (D1)

The "never injects" clause above is superseded by the shipped D1 session-identity feature, a deliberate reversal recorded in the archived `add-session-identity` design.md. The original rationale — injection into TLS would require a MITM the design didn't want to depend on — dissolved once the cage core shipped with the proxy already terminating TLS for policy enforcement: injection adds no new interception. What holds unchanged: the proxy verifies and strips forged or unknown `x-agent-*` headers toward **every** host; injection of the registered identity set happens **only** toward hosts explicitly listed in `identity.inject_hosts`, matched with the same shared host matcher as policy. See `openspec/specs/session-identity/spec.md`.
