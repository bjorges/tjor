# tjor

> *tjor* (Norwegian, nynorsk): **tether** — the rope that lets an animal graze freely, but only within a safe radius.

tjor runs AI coding agents (Claude Code, opencode, GitHub Copilot CLI) inside a portable, fail-closed container cage with per-session state and lifecycle. The agent works at full speed inside the boundary — and the boundary, not the prompt, is the policy. Per-session identity metadata and a credential broker are the next deltas on the roadmap (below), not shipped features.

**Status: pre-alpha, working skeleton.** The cage core runs: fail-closed egress with an adversarial conformance suite (10/10 probes green), opencode doing real work inside. Specs live in [`openspec/`](openspec/), decisions in [`docs/decisions/`](docs/decisions/).

## Quickstart

Requires bash ≥ 4.4, python3 ≥ 3.11, git, and a Docker engine with compose v2
(Colima, Docker Desktop, or native Linux).

```console
$ git clone https://github.com/bjorges/tjor && cd tjor
$ ./bin/tjor doctor              # host preflight + policy check + guarantee tiers
$ ./bin/tjor conformance         # adversarial suite: proves the boundary holds on YOUR runtime
$ cd ~/your/project
$ /path/to/tjor/bin/tjor run     # caged opencode session in this repo
```

Sessions are per-repo: state (harness auth, history) persists under
`~/.tjor/sessions/<session>/` across container restarts; the containers stay
disposable. `tjor run --harness claude` / `--harness copilot` select other
harnesses (images build on first use). `tjor policy <url>` previews an
egress verdict; `tjor down` removes a repo's topology.

The egress policy lives at `~/.config/tjor/policy.toml` (falling back to
[`config/policy.toml`](config/policy.toml)) — strict allow-list by default,
and a policy file that fails to parse denies everything.

## Why

Prompt-level rules are advisory. Harness-level permissions are harness-specific. The only guarantees that hold for *any* harness — including one running with permissions disabled — are structural: what the process can physically reach. tjor's design is corroborated by multiple independent production systems that converged on the same conclusion: restrict the environment, not the agent.

## Design (short version)

A compose-based container cage reproducing production-validated decisions:

- **Internal-only agent network** — no direct egress, by construction.
- **Dual-homed egress proxy** (explicit mode) with a fail-closed host/path allowlist and a DNS sidecar with zone-scoped forwarding.
- **Non-root agent user; writable repo mounts; per-session state roots** — a profile proven to sustain real daily work, hardened in tested increments.
- **Tiered guarantees**: a core that works on any Docker runtime, plus loud-when-absent hardening add-ons (e.g. AppArmor on runtimes that support it).
- **Session identity (D1)**: every session carries a frozen identity (`TJOR_SESSION_ID`, `--task` id, harness, repo, worktree) as environment inside the cage and as the vendor-neutral `x-agent-*` schema on the wire — the proxy strips forged or unknown identity headers toward every host (a session structurally cannot impersonate another) and injects the identity set only toward hosts you list in `identity.inject_hosts` (e.g. your LLM endpoints).

Plus the remaining roadmap deltas — **specced and tracked in issues #2–#4, not yet built**:

| Delta | Design target |
|---|---|
| **D2 — Credential broker** | Short-TTL, per-session credentials; target: opaque call-bound handles exchanged at the proxy boundary — the sandbox can *use* credentials, never *possess* them. |
| **D3 — Session lifecycle** | Deterministic naming, labels, attach picker, GC of containers and expired credentials (today: per-repo sessions with persistent state, no GC/attach UX). |
| **D4 — LLM gateway (optional)** | LiteLLM sidecar on the egress network; backend-agnostic. |

See [`docs/clean-room-charter.md`](docs/clean-room-charter.md) for the operational lessons this build is grounded in, and the provenance rules it is built under.

## License

[MIT](LICENSE)
