# Tasks: add-kube-broker

## 1. Broker kube source

- [ ] 1.1 `[broker]` config: `source = "kube"` with `kube_sa`, `kube_namespace`, `kube_duration`, and optional `kube_api_host` (else derived) — verified by config tests
- [ ] 1.2 Launcher `prepare_broker` kube case: derive the API server host from kubeconfig (`kubectl config view --minify`), mint the token (`kubectl create token <sa> -n <ns> --duration <ttl>`), write it as a pat-shaped broker.json (0o600) and set `TJOR_BROKER_HOSTS` to the API host; fail-closed + loud if kubectl/mint fails — verified by a unit test of the mint/derive command construction and parsing (mocked kubectl)
- [ ] 1.3 Preflight: kube source requires `kubectl` on the host — verified by the disabled-with-warning path when absent

## 2. In-cage kubectl + kubeconfig

- [ ] 2.1 Agent Dockerfile: pinned, checksum-gated kubectl (per-arch) — verified by an image check that kubectl is present at the pinned version
- [ ] 2.2 Entrypoint: when the kube broker is active, write `~/.kube/config` pointing at the API host with a placeholder bearer token (proxy overwrites) — verified in-cage: kubeconfig holds only the placeholder

## 3. Docs & test

- [ ] 3.1 README/ADR: the RBAC-as-policy model, a `kube` broker config + a `tjor policy add <api-host>` snippet, and the short-TTL/no-refresh + `create token` RBAC note — verified against behavior
- [ ] 3.2 Unit tests (mint/derive/kubeconfig); note that proxy injection reuses the D2 pat path (already conformance-tested) and the real-cluster e2e is a documented manual check — verified green
