# Tasks: add-landlock-tier

## 1. Config and launcher plumbing

- [x] 1.1 Add the `[landlock]` section (`mode = "auto"`, `deny_paths = []`) to `config/tjor.toml` with threat-model comments matching the file's style, and defaults in `python/tjor_cfg.py`; verify with a `python/tests` unit test that the merge path yields the defaults and honors a user override of `mode`.
- [x] 1.2 Pin cplt in `config/tjor.toml`: `[versions] cplt = "<current release tag>"` and `[versions.sha256] cplt_linux_arm64` / `cplt_linux_amd64` taken from the release's `SHA256SUMS`; verify each value by downloading both assets and running `sha256sum -c` locally.
- [x] 1.3 Export `TJOR_LANDLOCK` (mode) from `bin/tjor` through the agent service environment in `compose.yaml` (with launcher-side pre-validation of the mode value), add the `mask_dotenv` config default, and keep `deny_paths` launcher-side for the mount masks; verify with `docker inspect` on a launched agent that `TJOR_LANDLOCK` carries the configured mode.

## 2. Agent image

- [x] 2.1 Add the sha256-gated cplt install block to `images/agent/Dockerfile` (ARGs `CPLT_VERSION`, `CPLT_SHA256_ARM64`, `CPLT_SHA256_AMD64`; assets `cplt-{aarch64,x86_64}-unknown-linux-gnu.tar.gz`), wired to the config pins in the launcher's build-arg assembly in `bin/tjor`; verify the image builds and `docker run --rm --entrypoint cplt <image> --version` prints the pinned version.
- [x] 2.2 Verify the checksum gate fails closed: build once with a deliberately wrong `CPLT_SHA256_*` build arg and confirm the build aborts before unpacking (cage-image "Tampered cplt download" scenario).

## 3. Entrypoint: probe, wrap, degrade

- [x] 3.1 Add the Landlock availability probe to `images/agent/entrypoint.sh` (python3 ctypes `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)` run via `gosu agent`, any error → unavailable, capturing errno and ABI version); verify by running the entrypoint in the built image and observing the `kernel-sandbox:` status line report ABI on a Landlock-capable engine.
- [x] 3.2 Resolve the exact cplt invocation for an FS-only wrap against the pinned release (design decision 2: `--no-proxy --no-gh-guard --no-git-guard --inherit-env --pass-env` lowercase proxy vars, `--allow-port <proxy port> --allow-localhost-any`, home + extra-repo grants, `exec --`); verified in the built image: outside-tree read/write kernel-denied, proxy env intact under the wrap, `opencode`/`gh` run normally. Landlock in-tree denies confirmed UNENFORCEABLE (drove the hybrid revision).
- [x] 3.3 Implement the four-way handoff in entrypoint step 5 per design decision 2 (active wrap / auto-degraded / off / require-abort), emitting the contract status lines (`kernel-sandbox: active (landlock ABI <n>)` / `INACTIVE — <reason>` / `disabled by config`), rejecting unknown `TJOR_LANDLOCK` values with a FATAL abort; verify each branch by launching with each mode (simulate unavailability by running with a seccomp profile that denies the landlock syscalls) and checking `docker logs`.
- [x] 3.4 Implement launch-time dotenv masking in `bin/tjor` `run_agent` per design decision 2b (`mask_dotenv` gate, `.env`/`.env.*` glob excluding example/sample/template and `.git`, plus existing `deny_paths` entries → `--volume /dev/null:<path>:ro` per match, loud `+ dotenv mask` line); verify in a live session that a workspace `.env` reads empty, cannot be unlinked, and the mask line appears at launch.

## 4. Conformance and integration tests

- [x] 4.1 Add kernel-sandbox coverage to the agent-side checks: with the tier active, an in-cage outside-tree access fails, a launch-masked workspace `.env` reads empty and cannot be unlinked, and the `kernel-sandbox: active` status line is present in the agent container logs; verify green on a Landlock-capable engine.
- [x] 4.2 Add degradation-path coverage to `tests/integration`: `auto` + unavailable runtime leaves the session running with the `INACTIVE` statement in logs, `require` + unavailable aborts before the harness starts, `off` runs unwrapped with the disabled statement, masking holds when the kernel tier is unavailable, and the wrap preserves proxied egress (kernel-sandbox "strictly additive" scenarios); verify the integration suite passes.
- [x] 4.3 Run the full existing test suite (`python/tests`, `tests/integration`, conformance, `tests/doc_consistency.sh`) under default `auto` mode to confirm no regression in broker, identity, gateway, or launch flows; verify all green.

## 5. Docs and release

- [x] 5.1 Document the tier: README section (what it denies, the three modes, the status lines, how to read a degraded launch) and `INSTALL.md` note on runtime support; verify `tests/doc_consistency.sh` passes.
- [x] 5.2 Update `CHANGELOG.md` (0.11.0 entry + VERSION bump), and comment on + close issue #9 referencing the v0.11.0 release notes.
