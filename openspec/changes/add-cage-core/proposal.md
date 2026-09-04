# Proposal: add-cage-core

## Why

tjor currently has decisions and lessons but no running artifact. The cage core is the walking skeleton everything else (D1–D4) attaches to: a portable, fail-closed container cage in which a coding-agent harness demonstrably does real daily work. The design is de-risked — every baseline decision reproduces patterns validated in production elsewhere (ADR 0004, clean-room charter) — so the remaining risk is execution, best retired by building the smallest complete vertical slice now.

## What Changes

- New compose-based cage topology: internal-only agent network, dual-homed egress proxy (explicit mode), DNS sidecar with zone-scoped forwarding.
- New fail-closed egress policy engine: host/path allowlist with defined precedence, one shared matcher used by every component, encoding-aware asymmetric matching, parity tests.
- New agent image: non-root, harness preinstalled (opencode first; Claude Code and Copilot CLI as toggles), self-update disabled, instructions deployed from image at start, build hygiene gates.
- New `tjor` launcher: session-scoped state root, same-path workspace mapping, host-dependency checks, loud degradation when a hardening add-on is unavailable.
- Conformance probes accompany every requirement: an adversarial test container asserting the boundary holds (GitHub #13); acceptance for the whole change is tracked as GitHub #12.

Out of scope for this change: D1 identity injection, D2 broker, D3 GC/attach UX, D4 gateway, frontend profile, LSM hardening add-ons (each lands as its own change).

## Capabilities

### New Capabilities

- `cage-network`: the network boundary — internal-only agent network, dual-homed proxy topology, DNS sidecar behavior, sidecar creation ordering, admin-surface unreachability.
- `egress-policy`: allowlist semantics — rule precedence, fail-closed on config error, matcher parity across call sites, encoding/normalization asymmetry.
- `cage-image`: the agent image contract — non-root user, harness install and toggles, disabled self-update, instruction deployment at start, verified build inputs.
- `session-launch`: the launcher contract — per-session state roots, workspace path fidelity, dependency preflight, tiered-guarantee reporting.

### Modified Capabilities

*(none — first change in the repo)*

## Impact

- New code: compose topology, proxy addon(s), image Dockerfile(s), launcher script/binary, test suites (unit, parity, conformance).
- Dependencies: Docker/Compose, mitmproxy, CoreDNS (or equivalent), one harness (opencode) for the first vertical slice.
- No existing behavior to break; establishes the conventions (config layout, state-dir layout) later deltas build on.
