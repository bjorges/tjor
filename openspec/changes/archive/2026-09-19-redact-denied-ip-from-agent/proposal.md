# Proposal

## Why

When the resolved-address guard denies a request, its reason names the specific offending address — `_address_public` returns `non-global address 10.0.0.5`, which becomes `verdict.rule = "ip-guard:non-global address 10.0.0.5"`. That rule is used for two audiences at once: it is recorded in the operator denial log (`tjor denials`) *and* returned to the agent in the 403 body and the `x-tjor-rule` header (#60). So a guard denial hands the in-cage agent the concrete private/internal address the name resolved to. This is Low/Info — the agent resolved the name itself, so the address is not a brand-new disclosure — but the operator's diagnostic detail and the agent-facing message should not be the same string: the agent needs only *why* (a non-global address), not *which*.

## What Changes

- **The agent-facing denial is literal-free.** The 403 body and `x-tjor-rule` header carry a generic guard reason (`ip-guard:non-global-address`, `ip-guard:unparseable-address`) with no address/echoed-input literal.
- **The operator denial log is unchanged** — it keeps the full reason (including the specific resolved address), so `tjor denials` and the proxy's own diagnostics lose nothing.
- Only the guard reasons that embed a specific — the resolved non-global address, and the echoed unparseable input — are generalized; every other rule (policy blocks, `default-deny`, `resolve-timeout`, exemptions) is already literal-free and is shown to the agent unchanged, since those describe the agent's own request.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cage-network`: ADDED requirement — the resolved-address guard's agent-facing denial does not disclose the specific resolved internal address; the operator denial log retains it.

## Impact

- **Code**: `proxy/addon.py` — a small `_agent_rule(rule)` helper that maps a specifics-bearing ip-guard rule to its generic form; the two hooks (`http_connect`, `request`) use it for the 403 body + `x-tjor-rule` header while `_log_denial(...)` keeps the full `verdict.rule`. No change to `_address_public`, the verdict computation, `tjor_policy.Verdict`, or the denial-log format.
- **Tests**: `python/tests/test_addon_guards.py` — the agent-facing rule for a non-global-address denial carries no IP literal, while the value handed to the denial log still does; unparseable-input denial is likewise generalized to the agent; a policy/`default-deny`/`resolve-timeout` rule is unchanged.
- **Docs**: the `_address_public` #60 breadcrumb becomes a description of the split; CHANGELOG (Security) referencing #60.
- **Behavior change**: the agent-facing 403 for a guard denial no longer contains the resolved private IP; operators see no change. Closes #60.
