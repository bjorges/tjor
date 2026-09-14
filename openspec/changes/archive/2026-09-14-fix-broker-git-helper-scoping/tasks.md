## 1. Plumbing + gating

- [x] 1.1 `compose.yaml`: pass `TJOR_BROKER_HOSTS` into the agent service env with a comment (hostnames only, no secret; lets the entrypoint scope the placeholder helper). Verify: YAML valid; a broker session's agent env shows the hosts.
- [x] 1.2 `images/agent/Dockerfile`: COPY `python/tjor_policy.py` and `python/tjor_identity.py` to `/opt/tjor/python/`. Verify: rebuilt image contains both files.
- [x] 1.3 `images/agent/entrypoint.sh`: gate the placeholder-helper install on broker-enabled AND GitHub coverage via `tjor_identity.should_inject` (github.com or gist.github.com); otherwise wire the existing `gh` fallback. Verify: shellcheck clean; entrypoint-driven runs show the right helper for covered vs kube-only hosts.

## 2. Tests

- [x] 2.1 `tests/integration/broker_test.sh`: add entrypoint-driven cases on the agent image — (a) `TJOR_BROKER_ENABLED=1` + `TJOR_BROKER_HOSTS=github.com,*.github.com` → placeholder helper for github.com and gist.github.com; (b) `TJOR_BROKER_ENABLED=1` + `TJOR_BROKER_HOSTS=kubeapi.example.com` → `gh` fallback helper (no placeholder); (c) glob-only hosts `*.github.com` (which cover gist.github.com but not the apex, per the shared matcher) still wire the placeholder pair — the pair decision is atomic and uses the proxy's glob semantics. Verify: test green on the fix; pre-fix code fails case (b).

## 3. Docs

- [x] 3.1 CHANGELOG entry under Unreleased (#47). Verify: entry present, style-consistent.
