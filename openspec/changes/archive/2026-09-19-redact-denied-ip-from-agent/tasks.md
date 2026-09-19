# Tasks

## 1. Redact the agent-facing denial reason (proxy/addon.py)

- [x] 1.1 Add `_agent_rule(rule)`: map `ip-guard:non-global address …` → `ip-guard:non-global-address` and `ip-guard:unparseable address …` → `ip-guard:unparseable-address`; return every other rule unchanged. Verify with unit assertions in task 2
- [x] 1.2 In `http_connect` and `request`, use `_agent_rule(verdict.rule)` for the 403 body and the `x-tjor-rule` header, while `_log_denial(flow.request.host, verdict.rule)` keeps the full (detailed) rule; verify via task 2

## 2. Tests (python/tests/test_addon_guards.py)

- [x] 2.1 `_agent_rule` unit cases: non-global-address and unparseable-address rules are generalized (no IP/echoed literal); `default-deny`, a policy `block:*`, `ip-guard:resolve-timeout`, and exemption rules pass through unchanged
- [x] 2.2 End-to-end at the hooks (mitmproxy-gated): a request denied for a non-global address yields an agent-facing 403 body + `x-tjor-rule` header with NO IP literal, while the value passed to `_log_denial` (operator log) still contains the specific address; verify `pytest python/tests/test_addon_guards.py` passes

## 3. Docs and changelog

- [x] 3.1 Update the `_address_public` #60 breadcrumb comment to describe the implemented split (operator log detailed, agent-facing generic)
- [x] 3.2 CHANGELOG entry under `[Unreleased]` (Security) describing the agent-facing redaction, referencing #60

## 4. Full verification

- [x] 4.1 Run the full local gate — `pytest python/tests/` (mitmproxy installed), `tests/doc_consistency.sh`, and `openspec validate redact-denied-ip-from-agent` — and verify everything is green
