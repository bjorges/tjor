# Tasks

## 1. Pure server-identity comparison helper

- [x] 1.1 Add `same_server(a, b)` to `python/tjor_kube.py` (normalize both via `normalize_server()`, compare scheme + lowercased hostname + effective port per design decision 1) and a `same <a> <b>` CLI subcommand exiting 0/1; verify with `python3 python/tjor_kube.py same https://api:6443 api:6443` (exit 0) and a differing pair (exit 1)
- [x] 1.2 Unit tests in `python/tests/test_kube.py` covering: bare host vs full https URL equal, implicit vs explicit `:443` equal, hostname case-insensitivity, differing host / differing port / http-vs-https-same-origin unequal, and invalid input raising; verify `pytest python/tests/test_kube.py` passes

## 2. Launcher validation in prepare_broker()

- [x] 2.1 In the kube branch of `prepare_broker()` (`bin/tjor`): when `kube_api_host` is non-empty, also read the active context's server via `kube_server_url()`; if unreadable, `warn` that the override cannot be validated and disable the broker (return 0) before any minting; verify via the new integration branch in task 3.3
- [x] 2.2 When both values are available, run `tjor_kube.py same` on them before `kubectl create token`; on mismatch, `warn` naming both the configured override and the active context's server plus the remedies (`kubectl config use-context …` or fix/remove `broker.kube_api_host`), and disable the broker; verify via the integration branches in tasks 3.1–3.2

## 3. Integration coverage (tests/integration/kube_test.sh, mocked kubectl)

- [x] 3.1 Mismatch branch: config sets `kube_api_host` to a host differing from the mock's `config view` server; assert broker disabled (`TJOR_BROKER_ENABLED` empty), the `create token` argv file was never written (no token minted), and the warning names both servers; verify `tests/integration/kube_test.sh` passes
- [x] 3.2 Equivalent-spelling branch: `kube_api_host` set to the bare `host:port` of the mock's full-URL server; assert broker enabled and `TJOR_BROKER_HOSTS` scoped to the exact origin, unchanged from the happy path; verify `tests/integration/kube_test.sh` passes
- [x] 3.3 Unvalidatable branch: `kube_api_host` set while the mock's `config view` fails; assert broker disabled loudly and no token minted; also confirm the existing unset-override happy path still passes (spec scenario "Unset override keeps existing behavior"); verify `tests/integration/kube_test.sh` passes

## 4. Docs and changelog

- [x] 4.1 Reword the `kube_api_host` comment in `config/tjor.toml`: it is a validated pin of the expected cluster that must match the active context's server (checked at launch; mismatch disables the broker), not a cluster selector — selector/multi-cluster semantics tracked in #57; verify the comment reads correctly and `tests/doc_consistency.sh` passes
- [x] 4.2 Update the README broker section's `kube_api_host` line to the same pin-not-selector wording; verify `tests/doc_consistency.sh` passes
- [x] 4.3 Add a CHANGELOG entry under `[Unreleased]` (Security/Fixed) describing the silent-mismatch risk and the new launch-time validation, referencing #58; verify the entry renders under the correct heading

## 5. Full verification

- [x] 5.1 Run the full local gate — `pytest python/tests/`, `tests/integration/kube_test.sh`, `tests/doc_consistency.sh` — and verify everything is green
