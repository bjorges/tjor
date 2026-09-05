# Tasks: add-session-identity

## 1. Identity module

- [x] 1.1 Implement the identity matcher/transform beside the policy engine: known-header set, exact-match verification, strip-unknown/mismatched, inject-for-host — verified by unit tests covering every session-identity spec scenario, including the fail-closed missing-identity case
- [x] 1.2 Config schema: `[identity]` with `inject_hosts` (host globs via the existing shared matcher) — verified by config unit tests and a parity case through the shared host matcher

## 2. Launcher plumbing

- [x] 2.1 Derive the identity set at launch (`--task` flag, harness, repo, worktree detection via `git rev-parse --git-common-dir`, `TJOR_PARENT_SESSION` passthrough) and export to the agent service — verified by an in-cage env assertion in the e2e test
- [x] 2.2 Register identity with the proxy (environment at sidecar creation; identity values folded into the config-hash so identity changes recreate the sidecar) — verified by drift test: relaunch with a different `--task` recreates the proxy

## 3. Proxy enforcement

- [x] 3.1 Add the verify/strip/inject stage to the addon request hook (after policy allow, before egress), fail-closed wrapper included — verified by unit tests via the importable transform functions
- [x] 3.2 Loud logging of stripped forgeries (rate-limited) — verified by unit test on the log path

## 4. Integration & conformance

- [x] 4.1 Egress-side echo fixture service (conformance profile only) reflecting received headers — verified by the fixture responding in the conformance topology
- [x] 4.2 Conformance probes: forged `x-agent-session-id` arrives stripped; matching identity passes; injection appears exactly for `inject_hosts` targets and never elsewhere — verified by suite green locally and in CI
- [x] 4.3 Docs: README identity section moves from "roadmap" to shipped for D1; `identity.inject_hosts` documented as an explicit data-sharing decision — verified by README accuracy review against code
