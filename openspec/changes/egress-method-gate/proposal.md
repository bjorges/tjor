# Proposal

## Why

Egress rules match host and path only: `tjor_policy.evaluate(policy, url)` never sees the HTTP method, and a rule entry has exactly the keys `host` and `path` (#66). Two consequences follow for anyone who brokers a credential into the cage. A token whose server-side scope is broader than the session needs — most SaaS API tokens carry the user's full permissions — cannot be narrowed to reads at the proxy, which is the one place tjor controls (ADR 0007: the agent holds a placeholder, the proxy holds the secret, so the proxy is where "read-only" has to be enforced). And "read-only" is not even expressible for APIs that query by POST (search endpoints commonly do): adding a method to the existing path rules would not help, because path allow carve-outs only rescue a host-blocked host and stage-2 path blocks have no exception mechanism. The result today is that a brokered credential is as powerful inside the cage as it is outside, and the only lever is to not broker it.

## What Changes

- **A method gate in the egress policy.** A new top-level `methods` section with two rule kinds: `[[methods.restrict]]` (`host`, `allow = [<METHOD>, …]`) denies every method on a matching host that is not listed; `[[methods.except]]` (`host`, `path`, `methods = [<METHOD>, …]`) lets a listed method through on exactly that path, matched like an allow rule (every encoded and decoded form of the path must match, charter L22). The gate is a fourth evaluation stage: it runs after the host and path stages and before any allow is returned, and it can only deny — a request the gate admits is decided by the existing stages exactly as today, so a `methods` section never widens a policy, and an absent one yields today's verdicts for every well-formed method.
- **The method is part of every verdict.** `evaluate` takes the method; there is no default at the API, so a call site that forgets it fails loudly instead of evaluating a POST as a GET. The method is upper-cased and must match `^[A-Z]{1,16}$`; anything else is denied before any rule is consulted. `evaluate_connect` is unchanged: the method is inside the tunnel, so CONNECT is decided on the host alone and the inner request carries the method to the full evaluation once TLS is terminated.
- **Every call site passes the method, and the parity suite checks it.** The proxy addon passes the request's method; `tjor policy <url>` gains `--method <M>` (default `GET`, so today's invocations keep their meaning); the shared corpus gains method cases and the parity test runs each at all three call sites (charter L4). A method denial is logged in the session denial log as `method-block:<METHOD>` so `tjor denials` shows which method was refused, and the 403 the agent sees names the rule the same way.
- **Policy tooling keeps the section intact.** The gateway's policy augmentation regenerates the session policy from the parsed base policy; it re-emits the `methods` rules so enabling the gateway cannot silently drop a method restriction. `tjor policy add` inserts into `hosts.allow` only, never into a restrict rule's `allow` list that happens to follow it.
- **Docs and proof.** A read-only-API example in the README and the packaged default policy (commented out, so the default verdicts do not change); conformance probes for the gate on the Linux engine; the egress-policy and policy-ergonomics specs amended and their slides re-read.

Not breaking for operators: a policy without a `methods` section evaluates as before, and `tjor policy <url>` without `--method` evaluates `GET` as it effectively always did. Breaking for the Python API only: `evaluate` and `check` require a method, which is deliberate (see above); every in-repo caller is updated.

## Capabilities

### New Capabilities
<!-- none: the gate is one more stage of the existing egress policy -->

### Modified Capabilities
- `egress-policy`: the precedence requirement gains the method gate as the stage after path blocks, with its deny-only property; a new requirement states the gate's semantics (restrict denies unlisted methods on a host, an exception admits a listed method on a path only when every form of the path matches, the method is validated and normalised before evaluation, a malformed `methods` section fails the whole policy closed, CONNECT is unaffected); the parity requirement's shared corpus explicitly carries the method.
- `policy-ergonomics`: `tjor policy <url>` accepts `--method`, defaulting to `GET`, and the denial log records the refused method for a method denial.

## Impact

- `python/tjor_policy.py`: parser (`methods` key, `restrict`/`except` rule lists, method-token validation), `Policy` fields, `evaluate(policy, url, method)`, `check`, CLI `--method`; `python/tests/test_policy.py` (new gate tests and a deny-only property test over the corpus); `python/tests/fixtures/parity-policy.toml` and `corpus.json` (method rules and cases); `python/tests/test_parity.py` (method passed to all three call sites).
- `proxy/addon.py`: `decide(url, method)`, `request_verdict(url, host, method)`, the `request` hook passes `flow.request.method`; `python/tests/test_addon_guards.py` updated for the signature.
- `python/tjor_gateway.py` `augment_policy` carries `methods` through (test in `python/tests/test_gateway.py`); `python/tjor_policy_edit.py` insertion anchored to the `[hosts]` table (test in `python/tests/test_config_ergonomics.py`).
- `bin/tjor`: `cmd_policy` parses `--method`; `usage` line.
- `images/conformance/probes.py` and `images/conformance/policy.toml`: three or four probes for the gate (restricted method denied, allowed method passes, an exception admits only its path and method, encoding cannot widen an exception); `python/gen_boundary_matrix.py` registry and `docs/boundary-matrix.md` regenerated.
- Docs: README "Egress policy" (the example, the residual: the gate sees the method, not what a request does — a POST exception is as wide as its path), `config/policy.toml` commented example, `CHANGELOG.md` under `[Unreleased]`, the three slides tagged `egress-policy` and the one tagged `policy-ergonomics` re-read and re-pinned.
- Not affected: `evaluate_connect` and the DNS sidecar (`gen_corefile.py` reads hosts only), the broker and identity modules (host matcher only), the images.
