# Tasks: add-cage-core

## 1. Policy engine (egress-policy)

- [x] 1.1 Implement the matcher module: precedence chain (host blocks → path allows → path blocks → default), normalization, asymmetric encoded-form matching — verified by unit tests covering every egress-policy spec scenario
- [x] 1.2 Implement fail-closed config loading (missing/unparseable/invalid ⇒ deny-all) — verified by unit test feeding corrupt configs and asserting universal denial plus loud error output
- [x] 1.3 Build the shared verdict corpus and parity test harness that will run against every future call site — verified by CI job running the corpus against the module API

## 2. Topology (cage-network)

- [x] 2.1 Write the compose topology: internal-only agent network, CoreDNS sidecar, mitmproxy sidecar; launcher post-up step enforcing egress-first/connect-second sidecar ordering — verified by the launcher's own docker-inspect core check (aborts on non-internal network; abort path tested live) plus the conformance suite
- [x] 2.2 Write the mitmproxy addon embedding the policy module — verified by parity test (call site #2) and live conformance probes of allowed/denied requests through the proxy
- [x] 2.3 Generate CoreDNS zone config from the policy file (allow-zones forward, everything else local NXDOMAIN) — verified by unit tests on zone derivation and a live probe asserting NXDOMAIN + no upstream query for an unlisted zone
- [x] 2.4 Config-hash stamping and recreate-on-drift for both sidecars — verified live: policy change between runs triggered sidecar recreation
- [x] 2.5 Ensure no sidecar admin surface is reachable from the agent network; per-install generated credentials where a component demands one — verified by conformance probe scanning from the agent network (mitmdump/CoreDNS expose no admin surface by construction)
- [x] 2.6 Sidecar teardown on core-guarantee abort — abort now runs compose down before exiting

## 3. Agent image (cage-image)

- [x] 3.1 Dockerfile: non-root user, opencode installed via config-declared version ARGs, self-update disabled, allowlist-style .dockerignore — verified in-cage: uid=host uid, opencode 1.18.28 runs, autoupdate=false merged, instruction cargo deployed
- [x] 3.2 Checksum/digest verification gate for every build-time download; sidecar/base images pinned by digest — verified: build with a tampered sha256 fails before unpacking (no build tokens are used in v0.1; BuildKit secret-mount pattern documented for when one is)
- [x] 3.3 Instruction-deployment entrypoint step: copy image-cargo prompts/skills into harness config dir on every start — deployment verified in-cage; overwrite semantics are unconditional (cp -Rf each start)
- [x] 3.4 Claude Code and Copilot CLI as additional harness build toggles — verified: both variants build (npm exact-version pins) and boot their harness through the entrypoint as non-root

## 4. Launcher (session-launch)

- [x] 4.1 `tjor` launcher: host preflight with named-remediation errors, single config-merge function, per-session state root creation, same-path workspace mounting via git toplevel — merge verified by pytest; same-path mount and state root verified by the in-cage e2e run
- [x] 4.2 Tiered-guarantee reporting: core-guarantee failure aborts; missing add-on prints an explicit inactive-protection statement — abort verified live (sabotaged non-internal network refused); add-on reporting exercised on Colima (AppArmor-available branch)
- [x] 4.3 Launcher policy-preview/debug command using the shared matcher — `tjor policy` wraps the CLI call site covered by the parity suite

## 5. Conformance & acceptance

- [x] 5.1 Conformance test container with probes: direct-egress attempt, DNS exfil via unlisted zone, encoded-path block bypass, encoded-form allow widening, admin-surface scan, CONNECT denial, dot-segment escape, default-deny — 10/10 green on Colima; second runtime (Linux engine) runs in CI (GitHub #13)
- [x] 5.2 End-to-end acceptance: launch a session, have opencode complete a real LLM-driven task in a mounted repo — done 2026-09-05: the user ran real LLM-driven sessions (git inspection/pull workflows) in the cage; infrastructure e2e (same-path mount, TLS-through-proxy, clone through cage, blocked-host denial) verified earlier; GitHub #12 closed by the user. Dogfooding surfaced and fixed the SSH-remote gap (HTTPS rewrite + gh in image)
- [x] 5.3 CI workflow running unit, parity, image-build, and conformance suites — .github/workflows/ci.yml (green run pending first push)

## 6. External review hardening (2026-09-05)

- [x] 6.1 Fail-closed exception guard around every addon decision path (an addon error can never pass a request through) — unit-tested via request_verdict/connect_verdict
- [x] 6.2 Nested-encoding block bypass fixed: percent-decode to fixpoint; a path still decoding after the bound is denied outright (fail-closed:excessive-encoding) — unit + corpus tested at 4–10 and 20+ layers
- [x] 6.3 ReDoS eliminated: regex glob translation replaced with an iterative two-pointer wildcard matcher — semantics + timing tested
- [x] 6.4 Resolved-address guard (DNS-rebind/SSRF): allowed hosts resolving to any non-global address are denied; unresolvable hosts pass (nothing can flow); TJOR_IP_GUARD=off escape hatch for intranet policies — unit-tested with fake resolvers; residual TOCTOU documented in design.md
- [x] 6.5 Symlink-safe instruction deploy in the entrypoint (charter L26): every touched component de-symlinked before root writes; chown failures warn; agent-home writability hard-checked
- [x] 6.6 Session CA now generated constrained (pathlen:0 + EKU serverAuth, charter L25) by the launcher; verified in-cage via openssl
- [x] 6.7 Compose hardening: cap_drop ALL (+minimal cap_add) and no-new-privileges on all services, memory limits, fail-hard sentinel defaults for undiscovered sidecar IPs
- [x] 6.8 Bind-source verification for session dir and workspace (VM-shared-path check) on every launch; conformance cleanup trap; sidecar IP discovery hardened against docker 29's "invalid IP" rendering
- [x] 6.9 CI: actions pinned by commit SHA; agent-image job now a 3-harness matrix with boot checks; tracked __pycache__ purged and ignored
- [x] 6.10 Docs: README/ADR-0005 no longer claim unbuilt D1/D2 features; threat-model boundaries section added to design.md; docstrings on the security-core functions
