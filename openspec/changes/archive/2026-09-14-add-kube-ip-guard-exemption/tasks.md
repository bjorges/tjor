## 1. Exemption plumbing

- [x] 1.1 `proxy/addon.py`: read `TJOR_KUBE_API_HOST` (canonicalized like the gateway host) and add the scoped exemption clause beside the gateway one in `resolved_addresses_ok` (`"kube-exempt"`). Verify: unit tests below.
- [x] 1.2 `compose.yaml`: pass `TJOR_KUBE_API_HOST` into the proxy service env (egress side, hostname only). Verify: YAML valid.
- [x] 1.3 `bin/tjor`: initialize `TJOR_KUBE_API_HOST=""` with the other broker exports and set it to the derived API host in the kube branch of `prepare_broker`. Verify: shellcheck clean; kube_test assertion below.

## 2. Tests

- [x] 2.1 `python/tests/test_addon_guards.py`: mirror the gateway exemption tests — kube host exempted with a private resolution, other hosts still denied, no exemption when unset. Verify: pytest green.
- [x] 2.2 `tests/integration/kube_test.sh`: assert `prepare_broker` (kube source, mocked kubectl) exports `TJOR_KUBE_API_HOST` equal to the derived API host, and that a non-kube source leaves it empty. Verify: test green.

## 3. Docs

- [x] 3.1 CHANGELOG entry under Unreleased (#45). Verify: entry present, style-consistent.
