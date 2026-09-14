## Why

The proxy's SSRF IP guard (`[proxy] ip_guard`, default on) denies any allow-listed host that resolves to a non-global address. It has exactly one scoped exemption — the LLM gateway host — and none for the kube broker's API server (#45). A private-endpoint cluster (on-prem, private AKS/EKS) therefore resolves privately and is blocked at the IP-guard layer even though the policy allows it, making `[broker] source = "kube"` non-functional against exactly the clusters it exists for. The only workaround is a global `ip_guard = false`, which drops SSRF protection for every allowed host.

## What Changes

- The kube broker's API host becomes a second scoped IP-guard exemption in the proxy addon, mirroring the gateway pattern: exempt exactly the configured host, only when the kube broker is active, canonicalized with the shared policy host canonicalizer.
- The launcher passes the derived API host to the proxy sidecar as `TJOR_KUBE_API_HOST` (hostname only — no secret; it already flows to the proxy as the injection host).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: new requirement — the kube API host SHALL be exempt from the SSRF IP guard, scoped to exactly that host and only while the kube broker is active (mirrors llm-gateway's "Gateway host is exempt from the SSRF IP guard").

## Impact

- `proxy/addon.py` (exemption clause + env read), `compose.yaml` (proxy env), `bin/tjor` (`prepare_broker` kube branch exports the host; cleared for every other source).
- `python/tests/test_addon_guards.py`: exemption unit tests mirroring the gateway ones; `tests/integration/kube_test.sh`: assert the launcher exports the host.
- Proxy recreation on change is already covered: the config hash includes `TJOR_BROKER_HOSTS`, which equals the API host under the kube source.
