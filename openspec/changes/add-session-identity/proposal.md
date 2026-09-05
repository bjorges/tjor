# Proposal: add-session-identity

## Why

Concurrent caged sessions are indistinguishable to everything downstream — LLM gateways, audit logs, upstream APIs see one anonymous stream. Session identity (delta D1, issue #1) makes every session attributable: tools inside the cage know who they are, and egress traffic can carry — but never forge — that identity. This was the original platform research's most durable finding: a shared proxy cannot infer identity; it must be injected explicitly and verified structurally.

## What Changes

- The launcher exports a frozen identity set into the agent environment: `TJOR_SESSION_ID`, `TJOR_TASK_ID` (new `--task` flag), `TJOR_HARNESS`, `TJOR_REPO`, `TJOR_WORKTREE`, `TJOR_PARENT_SESSION`.
- The same identity is handed to the proxy sidecar, which becomes the enforcement point for the vendor-neutral `x-agent-*` header schema (ADR 0004): outbound headers that don't match the session's registered identity are **stripped** — a session cannot impersonate another.
- Optional proxy-side injection of `x-agent-*` headers on an explicit host allowlist (`identity.inject_hosts`, e.g. LLM endpoints) — possible now because the cage already MITMs TLS for path policy. Default: no injection (identity metadata is not leaked to arbitrary destinations); LLM traffic attribution per ADR 0005.
- Fail-closed: missing/invalid identity configuration means every `x-agent-*` header is stripped.

Out of scope: credential brokering (D2), any per-session LLM credentials (ADR 0005 stands), gateway composition (D4).

## Capabilities

### New Capabilities

- `session-identity`: the identity contract — environment variables inside the cage, header verification/stripping at the proxy, opt-in injection on configured hosts.

### Modified Capabilities

- `session-launch`: the launcher additionally derives and exports the identity set (new requirement on session startup behavior).

## Impact

- Code: launcher (identity derivation, `--task`), proxy addon (verify/strip/inject stage), config schema (`[identity]`), tests (unit + parity for the identity matcher, integration via an egress-side echo fixture).
- No breaking changes; sessions without `--task` get identity minus task id.
