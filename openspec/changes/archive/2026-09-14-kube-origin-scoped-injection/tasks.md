## 1. Shared matcher + kube origin helper

- [x] 1.1 `python/tjor_identity.py`: add `parse_broker_hosts(raw)` (entries `host[:port]`, bracketed IPv6, port 1–5 digits) and `broker_covers(pairs, host, port)` (host via `tjor_policy.host_matches`; port equality when scoped). Verify: new unit tests in `test_identity.py` green.
- [x] 1.2 `python/tjor_kube.py`: add `api_origin(server)` (explicit port or https default 443; IPv6 bracketed) + CLI verb `origin`; update the module docstring's "port-agnostic" claim. Verify: new unit tests in `test_kube.py` green.

## 2. Consumers

- [x] 2.1 `proxy/addon.py`: parse `TJOR_BROKER_HOSTS` with `parse_broker_hosts`; `broker_authorization(host, port)` and `_apply_broker` match with `broker_covers` against `flow.request.port`. Verify: updated + new `test_addon_guards.py` cases green (alternate-port negative included).
- [x] 2.2 `bin/tjor` kube branch: set the injection entry to `$(tjor_kube.py origin "${server}")`; keep `api_host` for the policy hint and `TJOR_KUBE_API_HOST`. Verify: `kube_test.sh` asserts origin-shaped `TJOR_BROKER_HOSTS` (`api.test.example:6443`; override case defaults to `:443`).
- [x] 2.3 `images/agent/entrypoint.sh`: GitHub-coverage check via `parse_broker_hosts` + `broker_covers(..., 443)`; rebuild the agent image. Verify: `broker_test.sh` entrypoint cases green (port-less pat entries unchanged).

## 3. Docs

- [x] 3.1 CHANGELOG entry under Unreleased (#49). Verify: entry present, style-consistent.
