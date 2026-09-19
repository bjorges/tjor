# Design

## Context

See proposal.md — Why. Verified in `proxy/addon.py`:

- `_address_public` returns `(False, f"non-global address {addr}{detail}")` (and `f"unparseable address {raw!r}"`); `resolved_addresses_ok` surfaces that `why`, and `connect_verdict`/`request_verdict` wrap it as `tjor_policy.Verdict(False, f"ip-guard:{why}")`.
- Both hooks then use `verdict.rule` twice: `_log_denial(flow.request.host, verdict.rule)` (operator denial log, read by `tjor denials`) **and** the agent-facing 403 (`http.Response.make(..., body=f"... ({verdict.rule})", headers={"x-tjor-rule": verdict.rule})`).
- Other rules are already literal-free: `default-deny`, policy `block:*`, `ip-guard:resolve-timeout`, `ip-guard:gateway-exempt`/`kube-exempt`, `fail-closed:addon-error`.

## Goals / Non-Goals

**Goals:**
- The agent-facing denial for a guard denial carries no resolved-address (or echoed-input) literal.
- The operator denial log is byte-for-byte unchanged.
- Minimal, local change; no new plumbing.

**Non-Goals:**
- Changing `_address_public`, the verdict computation, `tjor_policy.Verdict`, or the denial-log format.
- Redacting non-guard rules (policy blocks / default-deny describe the agent's own request and stay informative).
- Moving operator detail off the denial log (it stays exactly where operators already look).

## Decisions

1. **Redact at the agent-facing 403 sites, not at the guard.**
   Keep `verdict.rule` detailed (so `_log_denial` and `tjor denials` are unchanged — the faithful reading of "the operator log keeps the address"); add a small `_agent_rule(rule)` used only when building the 403 body and `x-tjor-rule` header in the two hooks. This needs no change to the guard, the verdict, or the Verdict type, and there is no double-log risk. The alternative — making the guard emit a generic `why` and logging the specific address separately (e.g. to proxy stderr) — was rejected: it moves operator detail off the denial log (against #60's wording) and adds a second log site.

2. **A targeted mapping, not a general IP regex.**
   `_agent_rule` matches the two known specifics-bearing guard reasons by prefix and returns their generic form (`ip-guard:non-global-address`, `ip-guard:unparseable-address`); everything else passes through unchanged. A blanket "strip anything that looks like an IP" regex over every rule risks mangling unrelated rules and is harder to reason about; the guard's reason strings are a small known set, so an explicit mapping is clearer and safe. If a future guard reason embeds a literal, it is added here deliberately.

## Risks / Trade-offs

- [A future guard denial reason embeds a literal and is forgotten here] → It would reach the agent until `_agent_rule` is extended. Mitigated by the test asserting the non-global (and unparseable) cases are generic, and by keeping the specifics-bearing reasons a small, reviewed set; the operator log always has the full detail regardless.
- [The agent gets slightly less detail] → Intended; the agent still learns the denial class (non-global address), just not the literal. Operators retain full detail.

## Migration Plan

No config/data/spec-format change; the addon ships in the proxy image, rebuilt per release. Rollback is a plain revert. Ships in the next patch release.
