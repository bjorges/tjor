# Proposal

## Why

`[broker] kube_api_host` reads as "pin the target cluster" but selects nothing: `kubectl create token` always mints against the host's currently-active kubectl context (it takes no context/kubeconfig flag in our invocation), while the override only changes the host string used for proxy injection scoping, the egress hint, and the SSRF-guard exemption. Nothing validates that the two agree (#58). A stale or copy-pasted override silently produces a session whose minted token and whose injection/allowlist scope refer to two different clusters — at best a confusing broker no-op, at worst an operator believing they are talking to the cluster named in config while the real token belongs to another.

## What Changes

- At launch, when `kube_api_host` is explicitly set, `prepare_broker()` SHALL also read the active context's server and validate the two refer to the same API server **before minting any token**. Comparison is canonical (scheme + host + effective port), in line with the v0.17.2 "one canonical representation" approach — `https://api.example:6443` and a bare `api.example:6443` override compare equal.
- On mismatch, the launch warns loudly (showing both canonical identities) and disables the broker — the existing fail-closed convention for every broker error branch. No token is minted for the wrong cluster.
- When the override is set but the active context's server cannot be read, validation is impossible: fail closed the same way (warn + broker disabled) instead of proceeding unvalidated.
- The comparison lives as a pure, unit-tested helper in `python/tjor_kube.py` (like `api_host`/`api_origin`), not ad-hoc string comparison in bash.
- Docs (`config/tjor.toml` comment, README) are reworded: the override is a validated **pin** of the expected cluster, not a cluster **selector**. True selector semantics (minting against a named context) are #57's design space and out of scope here.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: ADDED requirement — an explicit `kube_api_host` override SHALL be validated against the active kubectl context's server at launch; on mismatch or when validation is impossible, the broker is disabled loudly before any token is minted.

## Impact

- **Code**: `bin/tjor` `prepare_broker()` kube branch (around lines 472–492); `python/tjor_kube.py` gains a pure server-identity comparison helper.
- **Tests**: `python/tests/test_kube.py` (helper semantics); `tests/integration/kube_test.sh` (mocked-kubectl launcher branches: mismatch disables, equivalent spellings pass, unreadable context fails closed).
- **Docs/config**: `config/tjor.toml` `[broker]` comments, README broker section, CHANGELOG entry.
- **Behavior change**: launches that previously proceeded silently with a mismatched override now start without an injected credential and say so. Correct configurations (override unset, or matching the active context) are unaffected. Closes #58.
