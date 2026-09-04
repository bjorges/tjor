# Tasks: add-cage-core

## 1. Policy engine (egress-policy)

- [ ] 1.1 Implement the matcher module: precedence chain (host blocks → path allows → path blocks → default), normalization, asymmetric encoded-form matching — verified by unit tests covering every egress-policy spec scenario
- [ ] 1.2 Implement fail-closed config loading (missing/unparseable/invalid ⇒ deny-all) — verified by unit test feeding corrupt configs and asserting universal denial plus loud error output
- [ ] 1.3 Build the shared verdict corpus and parity test harness that will run against every future call site — verified by CI job running the corpus against the module API

## 2. Topology (cage-network)

- [ ] 2.1 Write the compose topology: internal-only agent network, CoreDNS sidecar, mitmproxy sidecar; launcher post-up step enforcing egress-first/connect-second sidecar ordering — verified by `docker inspect` assertions in an integration test
- [ ] 2.2 Write the mitmproxy addon embedding the policy module — verified by parity test (call site #2) and integration test of allowed/denied requests through the live proxy
- [ ] 2.3 Generate CoreDNS zone config from the policy file (allow-zones forward, everything else local NXDOMAIN) — verified by integration test resolving an allowed host and asserting NXDOMAIN + no upstream query for an unlisted zone
- [ ] 2.4 Config-hash stamping and recreate-on-drift for both sidecars — verified by integration test editing policy and asserting sidecar recreation
- [ ] 2.5 Ensure no sidecar admin surface is reachable from the agent network; per-install generated credentials where a component demands one — verified by conformance probe scanning from the agent network

## 3. Agent image (cage-image)

- [ ] 3.1 Dockerfile: non-root user, opencode installed via config-declared version ARGs, self-update disabled, allowlist-style .dockerignore — verified by container-start assertions (UID, harness version, update behavior) in an integration test
- [ ] 3.2 Checksum/digest verification gate for every build-time download; BuildKit secret mounts for any build token; sidecar images pinned by digest — verified by a build test with a corrupted artifact failing, plus an image-filesystem grep for the token
- [ ] 3.3 Instruction-deployment entrypoint step: copy image-cargo prompts/skills into harness config dir on every start — verified by integration test mutating a deployed file, restarting, asserting image version restored
- [ ] 3.4 Claude Code and Copilot CLI as additional harness build toggles — verified by building each variant and booting its harness in the cage

## 4. Launcher (session-launch)

- [ ] 4.1 `tjor` launcher: host preflight with named-remediation errors, single config-merge function, per-session state root creation, same-path workspace mounting via git toplevel — verified by bats tests for preflight/merge and an end-to-end launch test from a repo subdirectory
- [ ] 4.2 Tiered-guarantee reporting: core-guarantee failure aborts; missing add-on prints an explicit inactive-protection statement — verified by launch tests simulating a runtime without LSM support and a broken proxy start
- [ ] 4.3 Launcher policy-preview/debug command using the shared matcher — verified by parity test (call site #3)

## 5. Conformance & acceptance

- [ ] 5.1 Conformance test container with probes: direct-egress attempt, DNS exfil via unlisted zone, encoded-path block bypass, encoded-form allow widening, admin-surface scan, telemetry-endpoint denial with harness still functional — verified by suite green on Colima and one non-Colima runtime (GitHub #13)
- [ ] 5.2 End-to-end acceptance: launch a session, have opencode complete a real edit-build-commit task in a mounted repo, conformance suite green throughout — closes GitHub #12
- [ ] 5.3 CI workflow running unit, parity, build, and conformance suites — verified by green pipeline on the PR
