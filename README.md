# tjor

> *tjor* (Norwegian, nynorsk): **tether** — the rope that lets an animal graze freely, but only within a safe radius.

tjor runs AI coding agents (Claude Code, opencode, GitHub Copilot CLI) inside a portable, fail-closed container cage with per-session identity, brokered credentials, and session lifecycle management. The agent works at full speed inside the boundary — and the boundary, not the prompt, is the policy.

**Status: pre-alpha.** Design phase; no releases yet. Specs live in [`openspec/`](openspec/), decisions in [`docs/decisions/`](docs/decisions/).

## Why

Prompt-level rules are advisory. Harness-level permissions are harness-specific. The only guarantees that hold for *any* harness — including one running with permissions disabled — are structural: what the process can physically reach. tjor's design is corroborated by multiple independent production systems that converged on the same conclusion: restrict the environment, not the agent.

## Design (short version)

A compose-based container cage reproducing production-validated decisions:

- **Internal-only agent network** — no direct egress, by construction.
- **Dual-homed egress proxy** (explicit mode) with a fail-closed host/path allowlist and a DNS sidecar with zone-scoped forwarding.
- **Non-root agent user; writable repo mounts; per-session state roots** — a profile proven to sustain real daily work, hardened in tested increments.
- **Tiered guarantees**: a core that works on any Docker runtime, plus loud-when-absent hardening add-ons (e.g. AppArmor on runtimes that support it).

Plus four capabilities on top of the cage:

| Delta | What |
|---|---|
| **D1 — Session identity** | Vendor-neutral `x-agent-*` metadata, injected client-side; the proxy verifies and strips forgeries. Attribution-only for LLM traffic in v0.1 (shared credential, tagged sessions). |
| **D2 — Credential broker** | Short-TTL, per-session credentials; design target: opaque call-bound handles exchanged at the proxy boundary — the sandbox can *use* credentials, never *possess* them. |
| **D3 — Session lifecycle** | `tjor` session wrapper: deterministic naming, labels, attach picker, per-session state, GC of containers and expired credentials. |
| **D4 — LLM gateway (optional)** | LiteLLM sidecar on the egress network; backend-agnostic. |

See [`docs/clean-room-charter.md`](docs/clean-room-charter.md) for the operational lessons this build is grounded in, and the provenance rules it is built under.

## License

[MIT](LICENSE)
