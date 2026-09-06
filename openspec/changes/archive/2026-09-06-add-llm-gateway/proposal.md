# Proposal: add-llm-gateway (D4)

## Why

Today each harness talks to its model provider directly, and the operator
allow-lists that provider's host (`api.anthropic.com`, `api.openai.com`, …). An
optional **LLM gateway** lets a caged session instead point at a single
backend-agnostic endpoint (LiteLLM) that fans out to whatever provider the
operator configured — one place to route models, swap providers, or add a
self-hosted backend, without widening the egress policy per provider. This is
the last roadmap delta (D4, issue #4).

The gateway is **optional and off by default**. Enabling it must not weaken the
cage: the gateway's admin/management surface has to be unreachable from the
agent by construction (not merely password-gated, charter L30), and its
credentials must never touch the agent, the labels, or any config hash.

## What Changes

- A **LiteLLM sidecar on the egress network** (beside the proxy/dns sidecars),
  enabled by `[gateway] enabled = true`. The agent reaches it **only through the
  tjor proxy** — its sole route off the internal network — so the egress policy
  gains **exactly one host** (the gateway), and the gateway forwards to the
  operator's providers from the egress side.
- **Admin surface unreachable by construction.** The proxy is the agent's only
  path to the gateway, and its path policy toward the gateway host allows
  **only inference paths** (`/v1/chat/completions`, `/v1/completions`,
  `/v1/embeddings`, `/v1/messages`, `/v1/models`, `/health/liveliness`) and
  blocks everything else (`/key/*`, `/user/*`, `/team/*`, `/model/*` mutations,
  `/ui*`, …). The agent physically cannot reach the management API — no password
  involved.
- **Generated admin credential, never in the agent.** The launcher generates a
  per-install random **gateway master key** (LiteLLM's `LITELLM_MASTER_KEY`),
  kept only in the gateway + proxy sidecar env — never printed, never in a
  container label, never folded into the config hash. Inference from the agent
  authenticates by **the proxy injecting that key** toward the gateway host
  (reusing the D2 broker injection): the agent holds a placeholder key, exactly
  as it holds a placeholder GitHub token. So the master key gates both the admin
  API (which is also path-blocked) and inference, yet never reaches the sandbox.
- **Backend-agnostic (ADR 0005).** `[gateway]` config declares a model list
  (name → LiteLLM provider spec); the operator brings their own provider keys,
  which live only in the gateway sidecar env (egress side). The harness's
  `base_url` is pointed at the gateway (OpenAI-compatible endpoint) by the
  launcher.
- **SSRF IP-guard exemption for the gateway host only.** The gateway resolves to
  a private docker IP; the proxy's resolved-address guard (which denies
  allow-listed hosts resolving to non-global IPs) exempts exactly the configured
  gateway host — a deliberate, config-scoped internal endpoint, not a blanket
  off switch.

Out of scope (follow-ups): virtual per-session keys with a Postgres-backed
LiteLLM (the MVP uses master-key injection, no DB); the LiteLLM admin UI;
non-OpenAI-compatible base_url wiring for every harness beyond the
OpenAI/Anthropic-compatible endpoints LiteLLM already exposes; streaming-specific
policy nuances.

## Capabilities

### Added Capabilities

- `llm-gateway`: an optional LiteLLM sidecar on the egress network, reached only
  through the proxy (one allow-listed host), with its admin surface unreachable
  from the agent by construction and its generated master key injected by the
  proxy so it never enters the sandbox.

## Impact

- Code: `[gateway]` config (enabled, host, port, models, provider key env
  passthrough); launcher (generate master key, render LiteLLM config, start the
  sidecar on egress, wire the proxy broker-injection + path-block + IP-guard
  exemption toward the gateway host, set the harness base_url); compose (litellm
  service, gateway env); proxy addon (gateway-host IP-guard exemption; the
  inference-only path policy is expressed as ordinary `paths.block` rules).
  Docs + an ADR. Tests: key never in the agent/labels/hash; admin path blocked,
  inference path allowed; a live end-to-end is a documented manual check
  (needs a real provider key).
- No breaking changes: `[gateway] enabled` defaults false — sessions behave
  exactly as today unless the operator turns it on.
