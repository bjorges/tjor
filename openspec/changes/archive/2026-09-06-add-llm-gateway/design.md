# Design: add-llm-gateway (D4)

## Context

The cage already has the two mechanisms D4 needs: a **single egress chokepoint**
(the dual-homed proxy — the agent's only route off the internal network) and a
**credential broker** (D2) that injects a secret at the proxy toward a named
host so the agent holds only a placeholder. D4 places a LiteLLM sidecar on the
egress network and composes those two mechanisms so the gateway is powerful for
inference yet its control plane and credentials are structurally out of the
agent's reach.

## Goals / Non-Goals

**Goals:** an optional, off-by-default, backend-agnostic model endpoint reached
via one allow-listed host; the gateway admin surface unreachable from the agent
by construction; a per-install generated master key that never enters the agent,
labels, or config hash; provider keys confined to the egress side.

**Non-Goals:** virtual per-session keys (needs a Postgres-backed LiteLLM — a
follow-up); the LiteLLM admin UI; rewriting every harness's base_url mechanism
beyond LiteLLM's OpenAI/Anthropic-compatible endpoints; rate/cost governance.

## Decisions

- **Gateway on the egress network; reached only through the proxy.** LiteLLM
  attaches to `egress` (like proxy/dns), never to `internal`. The agent has no
  route to it except the proxy (its `http(s)_proxy`), so "reachable only via the
  chokepoint" is a property of the topology, not of a rule that could be
  misconfigured. The egress policy gains exactly one host: the gateway's.
- **Admin surface unreachable by construction — via host-block + path-allow
  carve-out (exhaustive default-deny).** The policy engine already supports a
  carve-out: a host on the *block* list is denied for EVERY path except those a
  `paths.allow` rule explicitly rescues. So the launcher adds the gateway host
  to `hosts.block` and adds a `paths.allow` carve-out for each inference
  endpoint. Every non-inference path — the entire management API, known or
  future — is denied by construction, with NO fragile admin-prefix enumeration.
  Because the proxy is the agent's only route to the gateway, that path decision
  is physically unavoidable. This is charter L30 satisfied without a password,
  and it fails safe against LiteLLM adding new admin routes later.
- **Master key injected by the proxy (D2 reuse), never in the agent.** LiteLLM
  runs with a generated `LITELLM_MASTER_KEY`. Rather than give the agent a key,
  the proxy injects the master key as the `Authorization` toward the gateway
  host — the exact D2 `pat` mechanism, just a different destination + secret.
  The agent's harness config carries a **placeholder** key and a `base_url`
  pointing at the gateway. So the one secret that authenticates inference is
  broker material in the proxy sidecar; the agent never holds it. *Alternative —
  run LiteLLM keyless and rely only on the path-block:* rejected; a generated
  admin credential is required (charter/#4), and defense in depth (key + path
  block + topology) is cheap here.
- **Key generation + non-exposure.** The launcher generates the master key
  (CSPRNG, host-side) once per install and stores it in a mode-0600 file under
  the user config dir (like a broker secret), NOT in the session dir that feeds
  the config hash, NOT in any label, NOT printed. It is passed to the gateway
  sidecar env and to the proxy's broker config (both egress side). Regenerating
  it is an explicit operator action.
- **IP-guard exemption for the gateway host only.** The proxy's resolved-address
  guard denies an allow-listed host that resolves to a non-global IP (SSRF/DNS
  rebind defense). The gateway legitimately resolves to a private docker IP, so
  the guard exempts exactly the configured gateway host (a single, config-scoped
  name) — not a blanket `TJOR_IP_GUARD=off`. The exemption is narrow and only
  present when the gateway is enabled.
- **Backend-agnostic config.** `[gateway]` declares `models` (each: a name plus
  a LiteLLM `model`/provider spec) and `provider_key_envs` (host env vars whose
  values are passed only into the gateway sidecar). The launcher renders a
  LiteLLM `config.yaml` into the gateway's egress-side mount. The operator's
  provider keys never leave the egress side.
- **base_url wiring.** LiteLLM exposes an OpenAI-compatible endpoint (and an
  Anthropic-compatible `/v1/messages`). The launcher sets the harness base_url
  env accordingly (`OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` / opencode's provider
  base_url) to `http://<gateway-host>:<port>`. MVP targets the OpenAI-compatible
  path first; per-harness specifics are documented.

## Risks / Trade-offs

- **Master key shared between proxy and gateway sidecars.** Both are egress-side
  and neither is the agent, so this is acceptable; the key is the gateway's
  authn secret, not a user credential. Documented.
- **Path-block completeness.** The security of the admin block rests on the
  inference-path allow-list being exhaustive and the admin-prefix block being
  complete. Mitigated by blocking broadly (everything not in the small inference
  set) and asserting it in tests; LiteLLM route additions in future versions are
  a maintenance item (pinned LiteLLM version).
- **No per-session key (MVP).** All sessions using the gateway share the master
  key via injection; per-session virtual keys need a DB and are a follow-up. The
  cage boundary (agent never holds the key) holds regardless.
- **HTTP vs HTTPS to the gateway.** LiteLLM serves HTTP on the egress network;
  the agent→proxy hop is already policy-controlled and the proxy→gateway hop is
  on the internal-to-docker egress network. Documented; a TLS gateway is a
  follow-up if the egress network is considered untrusted.

## Verification approach

Unit/integration without a real provider: the generated master key is absent
from the agent container (env, fs, process) and from all labels and the config
hash; an inference path toward the gateway host is allowed while an admin path
(`/key/generate`, `/ui`) is denied by the policy; the LiteLLM config renders the
configured models. A live end-to-end (real provider key → a caged `curl`/harness
call returns a completion, and `/key/generate` returns 403 through the proxy) is
a documented manual check, since CI has no provider credentials.
