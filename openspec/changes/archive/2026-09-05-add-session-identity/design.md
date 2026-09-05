# Design: add-session-identity

## Context

The cage core already MITMs TLS for path-level policy, the proxy addon has a per-request hook slot, and the launcher already derives a session id. Constraints: ADR 0004 (client-side injection principle, vendor-neutral schema), ADR 0005 (attribution-only LLM identity), charter L29 (no shared identifiers across concurrent sessions).

## Goals / Non-Goals

**Goals:** attributable sessions; structural non-forgeability (a session cannot claim another's identity); privacy by default (identity leaves the cage only toward hosts the user configured).

**Non-Goals:** authenticating identity to upstreams (headers are metadata, not credentials); per-session LLM keys (ADR 0005); persisting identity beyond the session state dir.

## Decisions

- **Verify-and-strip at the proxy, always; inject only on an allowlist.** The original platform analysis rejected proxy injection because it silently required MITM — tjor's cage core made MITM a load-bearing, tested fact, so injection is now honest. It stays opt-in (`identity.inject_hosts`) because broadcasting session metadata to every destination is a privacy leak, not a feature. *Alternative:* client-side injection via harness config — still supported implicitly (env vars are there; anything the harness injects that matches passes verification), but harnesses without header config would get no attribution.
- **Identity registration via proxy environment**, set by the launcher at sidecar (re)creation: identity changes recreate the sidecar exactly like policy drift (the config-hash already covers env by compose's own tracking; the identity values join the tjor.confighash input). *Alternative:* a mounted identity file — more moving parts for no gain at this size.
- **Matching is exact string equality** on the six known headers plus a case-insensitive `x-agent-` prefix rule for unknown ones (unknown `x-agent-*` headers are always stripped — the schema is closed). No globbing; the identity matcher lives beside the policy engine with the same unit + parity treatment.
- **`TJOR_*` env names in-cage, `x-agent-*` on the wire.** The wire schema stays vendor-neutral (ADR 0004); the in-cage env vars are tjor's own contract with its images.

## Risks / Trade-offs

- Injected headers are visible to configured upstream hosts — by design, and only there; documenting `inject_hosts` as an explicit data-sharing decision.
- Verification covers intercepted flows; a CONNECT tunnel that were ever passed through un-intercepted would bypass stripping — the cage configures no passthrough (established in add-cage-core's threat-model notes), so this holds by the same invariant.
- Header stripping on every request adds a per-request scan; the header set is small, cost negligible next to the existing policy evaluation.

## Verification approach

Unit tests for the matcher and strip/inject transforms (importable without mitmproxy, like the guard suite). Integration: an egress-side echo fixture in the conformance project (a container on the egress network that reflects received headers) lets probes assert, from inside the cage, that forged headers were stripped and injected ones arrived — closing the loop the cage's isolation otherwise hides.
