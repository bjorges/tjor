# Tasks

## 1. Pure helpers (python/tjor_kube.py)

- [x] 1.1 Add a multi-context kubeconfig renderer (N clusters/contexts/users, each with the placeholder token, `current-context` = first entry) and a `configs`/`multiconfig` CLI subcommand taking `(context,server)` pairs + ca path; verify with unit tests asserting N contexts, the placeholder-only token in each, first-as-current, and valid JSON
- [x] 1.2 Add a helper (or `--context` argument) to read a specific context's server, mirroring `kube_server_url` but for a named context; verify via unit test of the argument shaping (the pure part) — the `kubectl` call itself stays in the launcher
- [x] 1.3 Unit tests in `python/tests/test_kube.py` for 1.1/1.2, including duplicate-context and empty-list edge cases; verify `pytest python/tests/test_kube.py` passes

## 2. Multi-credential broker state (python/tjor_broker.py)

- [x] 2.1 Support a `source:"kube"` config carrying `clusters:[{origin,token},…]`: build an origin→token map and expose a per-origin `authorization(origin)` lookup (pat/github-app `BrokerState` and the legacy single-cluster pat path unchanged); verify with unit tests in `python/tests/test_broker.py` (right token per origin, None for unknown origin)
- [x] 2.2 A new atomic 0600 writer for the v2 broker.json shape (or extend `write_broker_json`), never emitting a real token to a world-readable file; verify perms + shape in a unit test

## 3. Launcher: mint-per-cluster (bin/tjor prepare_broker)

- [x] 3.1 Read `broker.kube_clusters` (JSON array via `cfg`, like `broker.hosts`); when present take the multi path, else the unchanged legacy path; validate each entry's keys and required `context`/`kube_sa` (fail closed on unknown/missing — `[broker]` is a security table); verify via the integration branches in task 5
- [x] 3.2 For each entry: read its context server (`--context`), validate a pinned `api_host` against it with `same_server` (#58) before minting, then mint with `kubectl create token <sa> --context <ctx> --namespace <ns> --duration <ttl>`; reuse the existing DNS-name/duration argument-injection validation per entry; verify via task 5
- [x] 3.3 Compute each cluster's exact origin (`api_origin`); refuse duplicate origins (fail closed, broker disabled, naming the collision); assemble the v2 broker.json and export `TJOR_KUBE_SERVERS`, `TJOR_KUBE_API_HOSTS`, and `TJOR_BROKER_HOSTS` (all cluster origins); print one `tjor policy add <host>` hint per cluster; verify via task 5
- [x] 3.4 All-or-nothing: any per-cluster validation/mint failure or duplicate origin disables the whole broker loudly (no partial provisioning, no injected credentials); verify via task 5

## 4. Proxy: per-origin injection + set-based guard (proxy/addon.py)

- [x] 4.1 Load the v2 kube broker into an origin→token map; make `broker_authorization`/`_apply_broker` select the token by the request's canonical origin (exact host+port, #49), stripping when no origin matches; keep the pat/github-app single-credential path intact; verify via `python/tests/test_addon_guards.py`
- [x] 4.2 Generalize the SSRF exemption to a set: parse `TJOR_KUBE_API_HOSTS`, and change the single-host checks in `resolved_addresses_ok` and the `server_connect` pin (#41) from `== KUBE_API_HOST` to membership in the set; verify existing gateway/kube exemption + pin tests still pass and add a two-host exemption test
- [x] 4.3 Tests: cross-cluster injection isolation (A's origin gets A's token, never B's; non-cluster host gets none), multi-host exemption, and the pin leaving all cluster hosts unpinned; verify `pytest python/tests/test_addon_guards.py` passes

## 5. Integration (tests/integration/kube_test.sh, mocked kubectl)

- [x] 5.1 Extend the mock kubectl to answer `config view --minify --context <ctx>` per context and record per-context `create token` argv; add a two-cluster happy path asserting both tokens minted against the right contexts, v2 broker.json has both origins, `TJOR_KUBE_API_HOSTS`/`TJOR_KUBE_SERVERS` list both, and one policy hint per cluster; verify `tests/integration/kube_test.sh` passes
- [x] 5.2 Per-cluster #58 pin validation: a mismatched `api_host` on one entry disables the whole broker before any mint (no `create token` argv recorded for any cluster); verify passes
- [x] 5.3 All-or-nothing + duplicate origin: one cluster's mint failing disables the broker entirely; and two entries with the same origin are refused; verify passes
- [x] 5.4 Back-compat: the existing flat single-cluster config still produces the pat-shaped broker.json and single-valued env, unchanged; verify the existing single-cluster assertions still pass

## 6. Entrypoint + config + compose

- [x] 6.1 `images/agent/entrypoint.sh`: render the multi-context kubeconfig from `TJOR_KUBE_SERVERS` (multi path) or the single-context config (legacy), and wire the exemption for all `TJOR_KUBE_API_HOSTS`; verify the render branch by unit-testing the renderer (task 1) and a shellcheck/syntax pass
- [x] 6.2 `python/tjor_cfg.py`: register `broker.kube_clusters` so the security-table validator accepts it; verify `pytest python/tests/test_cfg_and_corefile.py` passes and a typo'd top-level broker key still aborts
- [x] 6.3 `compose.yaml`: plumb `TJOR_KUBE_API_HOSTS`/`TJOR_KUBE_SERVERS` (replacing/augmenting the single-valued vars); verify `compose config` renders and the conformance/kube tests still pass

## 7. Conformance probe

- [x] 7.1 Add a probe asserting cross-cluster token isolation at the boundary (a request toward cluster B's origin never carries cluster A's token), fitting the existing broker-probe pattern; note any topology limits in the probe/log if a live two-cluster fixture is impractical, and cover the isolation in the addon suite as the authoritative check; verify the probe runs under `tjor conformance` (or is documented why it lives in the unit suite, as with #41)

## 8. Docs and changelog

- [x] 8.1 `config/tjor.toml`: document `[[broker.kube_clusters]]` (per-entry fields, static-at-launch, all-or-nothing, back-compat with the flat form); verify `tests/doc_consistency.sh` passes
- [x] 8.2 README kube section: multi-cluster usage (config + `kubectl config use-context` switching + one `tjor policy add` per cluster); verify `tests/doc_consistency.sh` passes
- [x] 8.3 CHANGELOG entry under `[Unreleased]` describing the feature, referencing #57 and the deliberate simultaneous-multi-cluster posture; verify it renders under the correct heading

## 9. Full verification

- [x] 9.1 Run the full local gate — `pytest python/tests/` (mitmproxy installed), `tests/integration/kube_test.sh`, `tests/doc_consistency.sh`, and `openspec validate add-kube-multi-cluster-broker` — and verify everything is green
