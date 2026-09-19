# Design

## Context

See proposal.md — Why. The relevant current state:

- `prepare_broker()`'s kube branch (`bin/tjor` ~472–492) runs in this order: config validation → server = `kube_api_host` override, else derived from the active context via `kube_server_url()` → normalize/parse (`tjor_kube.py url|host|origin`) → mint via `kubectl create token` → write `broker.json`, export `TJOR_BROKER_HOSTS` / `TJOR_KUBE_SERVER` / `TJOR_KUBE_API_HOST`.
- When the override is set, `kube_server_url()` is never consulted — the active context's server is simply unknown to the launch, yet it is the cluster the token is minted against.
- Every broker failure branch follows one convention: `warn` + `return 0` — broker disabled, session starts credential-less and says so ("Fail-closed, never silent downgrade" requirement).
- Pure transforms live in `python/tjor_kube.py` (unit-tested in `python/tests/test_kube.py`); bash keeps the `kubectl` invocations. `urllib.parse.urlparse().hostname` already lowercases, and `normalize_server()` already canonicalizes unschemed values to https.
- `tests/integration/kube_test.sh` sources `bin/tjor` and drives `prepare_broker` against a mocked `kubectl`, recording `create token` argv — the natural home for launcher-branch assertions, including "no token was minted".

## Goals / Non-Goals

**Goals:**
- One canonical server-identity comparison, unit-tested in Python, invoked once from bash.
- Validation happens **before** minting, so a token for the wrong cluster never exists.
- The mismatch warning is actionable: it names both the configured override and the active context's server, and points at the two fixes (change context, or fix/remove `kube_api_host`).

**Non-Goals:**
- Making `kube_api_host` a true cluster *selector* (passing `--context` to minting) or any multi-cluster session support — that is #57's design space.
- Changing behavior when the override is unset (derive-from-context path is untouched).
- Any proxy-side change — injection scoping, SSRF-guard exemption, and placeholder-kubeconfig machinery are unchanged; they just can no longer receive a host that contradicts the minted token.

## Decisions

1. **Compare (scheme, effective host, effective port) — not raw strings, not origin-only.**
   New pure function `same_server(a, b)` in `tjor_kube.py`: normalize both via `normalize_server()`, then compare urlparse scheme, hostname (lowercased by urlparse), and `port or scheme-default` (443 https / 80 http). Raw string equality would re-create the spelled-differently-same-server false mismatches that v0.17.2 eliminated elsewhere (`https://api.example:6443` vs bare `api.example:6443` must compare equal). Origin-only comparison (`api_origin(a) == api_origin(b)`) would miss an http-vs-https disagreement on the same host:port — obscure, but including the scheme is free.
   CLI shape: `tjor_kube.py same <a> <b>` exits 0 when they name the same server, 1 otherwise — one subprocess call from bash, same pattern as the existing `url|host|origin` subcommands.

2. **Validate before minting, at the point the server value is resolved.**
   The check slots in right after the override is read (and before `kubectl create token`): if `kube_api_host` was non-empty, also call `kube_server_url()` and run the comparison. A mismatch therefore aborts the branch while no token for the wrong cluster has ever been requested — and the mocked-kubectl test can assert the recorded `create token` argv file was never written.

3. **Override set + unreadable active context ⇒ fail closed.**
   If `kube_server_url()` fails while the override is set, the override cannot be validated — warn and disable the broker. Warn-only-and-proceed was rejected: a missable warning is exactly the silent-mismatch failure mode #58 describes. This is also more honest than today's behavior, where minting proceeds against the same unreadable/absent context and dies with a less specific error.

4. **Mismatch disables the broker; it does not abort the launch.**
   Consistent with every other broker failure branch and with the existing "Fail-closed, never silent downgrade" requirement: the session starts with no injected credential and the reason is printed. A hard launch abort would make this one config error more fatal than a revoked key or a failed mint, with no security payoff — the fail-closed session holds no credential at all.

5. **Warning text names both raw values.**
   The message shows the configured `kube_api_host` and the active context's server as read from the kubeconfig — the two strings the operator can actually find and fix — plus the remedies (`kubectl config use-context …`, or correct/remove `broker.kube_api_host`). Canonical forms stay internal to the comparison.

## Risks / Trade-offs

- [A deliberate alias: the operator points `kube_api_host` at a different published name (e.g. a load-balancer front) for the same cluster the active context mints against] → The canonical compare flags it and disables the broker. Accepted: nothing in the current config model declares "these two names are one cluster", so accepting the mismatch would reopen #58. The config comment documents that the override must name the active context's server; a real aliasing need is #57-adjacent design (an explicit selector/alias), not silent acceptance.
- [Configs that "worked" only by accident (mismatched override, session quietly talking to the active-context cluster while allowlisting another host) now start credential-less] → Intended. CHANGELOG entry plus the explicit two-identity warning make the cause immediately visible.
- [Scheme/port default subtleties in the comparison] → Pinned by unit tests over the equivalence cases: bare host vs full URL, implicit vs explicit `:443`, differing ports, differing schemes on the same origin.

## Migration Plan

No data or config migration. Ships as a patch release: code + tests + docs in one commit; CHANGELOG entry under `[Unreleased]` (Security/Fixed). Rollback is a plain revert — no persisted state changes.
