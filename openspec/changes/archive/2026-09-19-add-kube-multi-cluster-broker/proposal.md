# Proposal

## Why

The kube broker binds a session to exactly one cluster: `prepare_broker()` mints a single SA token against the host's active kubectl context, writes one `broker.json`, and the proxy injects that one credential toward one API origin. Reaching a second cluster means ending the session and relaunching after `kubectl config use-context` (#57). A sibling project (kubecage) instead merges several clusters into one kubeconfig so an operator switches between them live, mid-session. This change brings that capability to tjor while keeping the broker's fail-closed, least-privilege, credential-never-in-cage posture — resolving the decision #57 asked for in favor of building it, not documenting the limit.

## What Changes

- **New `[[broker.kube_clusters]]` config** — an explicit list; each entry names its own `context` (the kubectl context to mint against), `kube_sa`, `namespace`, `duration`, and optional `api_host` pin. Chosen over auto-merging every reachable context: each cluster stays a deliberate, per-cluster-scoped grant.
- **Static provisioning at launch** — every configured cluster's token is minted (`kubectl create token --context <ctx>`) and the agent receives one **multi-context** placeholder kubeconfig. The agent switches with `kubectl config use-context` mid-session; no restart. There is **no** control channel to add a cluster to a running session (the sealed-cage model is preserved).
- **Per-cluster `api_host` validation** reuses #58: when pinned, an entry's `api_host` is validated against *that context's* server before its token is minted. Minting with `--context` makes the override a true selector for that entry.
- **Broker becomes per-origin** — the proxy holds an origin→token map and injects each cluster's token **only** toward that cluster's exact API origin (#49 scoping, per cluster). Cluster A's token never reaches cluster B.
- **Guard/exemption become sets** — the SSRF-guard exemption and the resolve-and-pin hook (#41) exempt *every* configured cluster API host; launch prints the `tjor policy add` line for each.
- **Fail-closed, all-or-nothing** — if any configured cluster cannot mint, validate, or has a duplicate/ambiguous API origin, the **whole** broker is disabled loudly (never a session whose kubeconfig lists a context with no working credential).
- **Back-compat** — the flat single-cluster config (`kube_sa`/`kube_namespace`/`kube_api_host` at `[broker]`) is unchanged; the legacy single-credential path runs exactly as today when `kube_clusters` is absent.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: ADDED requirements for the multi-cluster kube capability — explicit per-cluster list, static launch-time provisioning with a multi-context kubeconfig, per-origin injection isolation across clusters, per-cluster API-host exemption/pinning, and all-or-nothing fail-closed provisioning. Single-cluster behavior is preserved (additive).

## Impact

- **Code**: `bin/tjor` `prepare_broker()` (mint-per-cluster loop, per-cluster #58 validation, origin-uniqueness, env-list assembly); `python/tjor_kube.py` (a `--context` server read and a multi-context kubeconfig renderer); `python/tjor_broker.py` (a multi-credential kube broker state keyed by origin); `proxy/addon.py` (origin→token selection in `_apply_broker`/`broker_authorization`; `KUBE_API_HOSTS` set in `resolved_addresses_ok` and the `server_connect` pin from #41); `python/tjor_cfg.py` (register `broker.kube_clusters`, validate each entry's keys — `[broker]` is a security table where a typo aborts); `images/agent/entrypoint.sh` (render the multi-context kubeconfig; wire exemptions for all hosts); `config/tjor.toml` and `compose.yaml` (new env plumbing).
- **broker.json**: a new multi-kube shape (`{"source":"kube","clusters":[{origin,token},…]}`) used when `kube_clusters` is present; the pat/github-app shapes and the legacy single-cluster kube path are untouched.
- **Tests**: `python/tests/test_kube.py` (multi-context render), `test_broker.py` (per-origin selection), `test_addon_guards.py` (per-origin injection isolation + multi-host exemption + pin), `tests/integration/kube_test.sh` (mocked-kubectl: N clusters minted, per-cluster validation, all-or-nothing, duplicate-origin refusal), and a conformance probe for cross-cluster token isolation.
- **Docs**: README kube section (multi-cluster usage), `config/tjor.toml` comments, CHANGELOG. Closes #57.
