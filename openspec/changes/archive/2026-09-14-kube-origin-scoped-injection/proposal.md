## Why

Brokered-credential injection matches on hostname alone (#49). Under the kube source, any service reachable on the API server's hostname but a *different port* receives the same ServiceAccount token as the intended API server — a plausible leak in real cluster network setups (independent review flagged it "major" for a production-cluster profile). The injection scope should be the exact origin, not the name.

## What Changes

- Broker destination entries gain optional port scoping (`host:6443`, `[2001:db8::1]:6443`); an entry without a port keeps today's any-port behavior (back-compat for pat/github-app configs). Parsing and matching live in `tjor_identity` beside the existing host matcher — one implementation, used by the proxy and the entrypoint alike.
- The proxy injects a brokered credential only when both the host glob AND (if scoped) the port match the request's actual destination; redirects/authority changes are naturally re-evaluated per request.
- The kube source composes its injection entry as the API server's exact origin (`host:port`, https default 443, IPv6 bracketed) via a new pure `tjor_kube.api_origin` helper; the policy-add hint and the SSRF-guard exemption stay hostname-level (they answer different questions).
- The entrypoint's GitHub-coverage check (#47) asks the port-aware question (github/gist on 443) through the same shared matcher.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: "Injection is scoped to the credential's destination" gains optional port scoping; "Kube token is short-lived; injection is scoped to the API server" is strengthened to exact-origin scoping with a negative alternate-port scenario.

## Impact

- `python/tjor_identity.py` (parse + port-aware match), `python/tjor_kube.py` (`api_origin` + CLI `origin`), `proxy/addon.py` (use the pair matcher), `bin/tjor` (kube branch composes the origin entry), `images/agent/entrypoint.sh` (port-aware coverage call; agent-image rebuild).
- Tests: `test_identity.py`, `test_addon_guards.py` (alternate-port negatives), `test_kube.py`, `tests/integration/kube_test.sh` (origin-shaped `TJOR_BROKER_HOSTS`).
- Back-compat: port-less entries behave exactly as before; only the kube source emits scoped entries by default.
