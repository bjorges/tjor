# Design

## Context

See proposal.md — Why. Current state, verified in the code:

- `prepare_broker()` (`bin/tjor`) kube branch mints one token via `kubectl create token <sa> --namespace <ns> --duration <ttl>` (no `--context`; active context), writes a **pat-shaped** `broker.json` (`{"source":"pat","token":…}`), and exports single-valued `TJOR_BROKER_HOSTS` (the API origin), `TJOR_KUBE_SERVER`, `TJOR_KUBE_API_HOST`.
- The proxy (`proxy/addon.py`) loads **one** `BrokerState` from `broker.json`; `broker_authorization(host, port)` returns that one token when `broker_covers(BROKER_HOSTS, host, port)`. `resolved_addresses_ok` and the new `server_connect` pin (#41) exempt a single `KUBE_API_HOST`.
- `tjor_kube.py` renders a **single-context** placeholder kubeconfig; `same_server` (#58) already gives canonical server-identity comparison; `api_origin` gives the exact `host:port`.
- `[broker]` is a `SECURITY_TABLES` member in `tjor_cfg.py`: an unknown key inside it **aborts** the launch. `broker.hosts` is already read as a JSON array in bash (`cfg … | python3 -c json.load`); `gateway.models` is the array-of-tables precedent (registered `EXTRA_KNOWN`).
- The entrypoint renders the kubeconfig from `TJOR_KUBE_SERVER` via `tjor_kube.py config`.

## Goals / Non-Goals

**Goals:**
- One session, N clusters, client-side switching, each cluster's token isolated to its own origin.
- Every existing single-cluster guarantee holds per-cluster (never-in-cage, #49 origin scope, #58 pin, #45 exemption, #41 resolve-and-pin).
- Additive: the flat single-cluster path is untouched and stays the default.

**Non-Goals:**
- Auto-discovering/merging every reachable context (rejected: breadth against the deliberate-grant posture).
- Adding a cluster to a running session (no control channel into the sealed cage).
- In-cage token refresh (unchanged: short-TTL, no refresh; a long session re-launches).
- Per-cluster *egress policy* automation beyond printing the `tjor policy add` hints.

## Decisions

1. **Explicit list keyed by context; mint with `--context`.**
   `[[broker.kube_clusters]]` entries each carry `context`, `kube_sa`, `namespace`, `duration`, optional `api_host`. Minting becomes `kubectl create token <sa> --context <ctx> --namespace <ns> --duration <ttl>` — the true per-entry selector #57/#58 anticipated. The server for an entry is read with `kubectl config view --minify --context <ctx>` (a `--context` variant of `kube_server_url`), and a pinned `api_host` is validated against it with `same_server` (#58), per entry, before any mint.

2. **broker.json v2 for multi-kube; legacy shape preserved.**
   When `kube_clusters` is present, write `{"source":"kube","clusters":[{"origin":"host:port","token":"…"},…]}`. The pat/github-app shapes and the flat single-cluster kube path (pat-shaped) are unchanged, so back-compat is structural, not conditional. `broker.json` stays proxy-only, 0600, atomic (unchanged `write_broker_json` for legacy; a new writer for v2).

3. **Proxy holds an origin→token map.**
   For a `source:"kube"` config the proxy builds `KUBE_CREDS = {canonical_origin: token}`. `broker_authorization(host, port)` (and `_apply_broker`) look up the request's canonical origin in that map instead of consulting the single `BROKER`. Selection is by exact origin (#49) — a same-host different-port service matches nothing. This keeps the injection call site's shape (find credential for this origin, else strip) but sources it per-cluster.

3a. **Origin uniqueness enforced at launch, not in the proxy.**
   Two entries with the same canonical origin would make the map ambiguous. `prepare_broker()` refuses duplicate origins (fail-closed, broker disabled) so the proxy map is always unambiguous — the check lives where the human-readable error belongs.

4. **Guard/exemption/pin generalized to a set.**
   `TJOR_KUBE_API_HOST` → `TJOR_KUBE_API_HOSTS` (comma list); the proxy parses it into a set. `resolved_addresses_ok` and the #41 `server_connect` pin change their single-host `host == KUBE_API_HOST` test to `host in KUBE_API_HOSTS`. `TJOR_KUBE_SERVER` → `TJOR_KUBE_SERVERS` (the per-cluster servers the entrypoint renders contexts for).

5. **All-or-nothing provisioning.**
   Any per-cluster validation/mint failure, or a duplicate origin, disables the whole broker with a message naming the cluster. Rationale: consistent with the existing "fail-closed, never silent downgrade" requirement, and it avoids a kubeconfig context that silently has no credential — more confusing than a clean all-off with a clear reason. Alternative (skip-and-continue) rejected; see Risks.

6. **Multi-context kubeconfig renderer.**
   `tjor_kube.py` gains a renderer emitting N clusters/contexts/users (all the placeholder token, each context named after its config `context`), with `current-context` set to the first entry. The entrypoint calls it with the per-cluster servers + the session CA. The existing single-context renderer stays for the legacy path.

7. **Config validation of list entries.**
   Register `broker.kube_clusters` so the security-table validator does not abort on it, and — because `[broker]` typos abort by policy — validate each entry's keys explicitly in `prepare_broker()` (the generic validator handles tables, not array elements): unknown per-entry keys and a missing required `context`/`kube_sa` fail closed with a clear message, so a typo'd `kube_sa` never silently mis-scopes a cluster.

## Risks / Trade-offs

- [All-or-nothing is brittle: one transient mint failure among five clusters yields no broker] → Accepted: the failure names the cluster and is fixable; a partially-provisioned session with a dead context is worse for a security tool. Documented in the config comments.
- [Simultaneous live credentials for N clusters widen the blast radius of one compromised session vs. one-cluster-per-session] → This is exactly what the feature grants; the explicit-list config keeps it a conscious, least-privilege choice (per-cluster SA/ns), and the #57 decision is to build it. Recorded here so it is deliberate.
- [Per-entry `--context` mint depends on each context being present/authauthorized in the host kubeconfig] → A missing/unauthorized context fails that cluster's mint → all-or-nothing disable with the cluster named; no partial state.
- [Origin collision across clusters behind one gateway/LB] → Refused at launch (decision 3a) rather than silently binding one token to a shared origin.

## Migration Plan

No data migration. Additive config and env; a proxy image rebuild (as every release). Rollback is a plain revert; existing single-cluster sessions are unaffected either way. Ships as a minor release once merged.
