# Tasks: add-prebuilt-images

## 1. Runtime uid alignment (uid-agnostic image)

- [x] 1.1 Dockerfile: create `agent` with a fixed default uid (10001); drop the dependency on a host-uid build-arg (keep AGENT_UID accepted but defaulted) — verified by the image building without `--build-arg AGENT_UID`
- [x] 1.2 Entrypoint: as root, if `TJOR_AGENT_UID` differs from the agent user's uid, `usermod -o -u` + `groupmod` and reconcile `/home/agent` ownership before `gosu` — verified by an integration test running the image under a non-default uid: effective uid matches, home writable
- [x] 1.3 Launcher: pass `TJOR_AGENT_UID=$(id -u)` to the agent (env), stop passing it as a build-arg on the published path — verified in-cage: `id -u` == host uid

## 2. Publish workflow

- [x] 2.1 `.github/workflows/publish-images.yml` (on tag `v*`): buildx multi-arch (amd64+arm64) for each harness agent + proxy + conformance, push to `ghcr.io/<owner>/tjor-agent-<harness>` (and tjor-proxy/tjor-conformance) tagged `:<version>` + `:latest`, using the config pins; login via `GITHUB_TOKEN` — verified by a successful run on the next tag
- [x] 2.2 A CI check (test workflow) that a multi-arch `buildx build --platform linux/amd64,linux/arm64` of the agent image succeeds (no push) — verified green

## 3. Pull-or-build launcher

- [x] 3.1 `resolve_agent_image`: with `images.publish` enabled + a version tag, try to pull `ghcr.io/<owner>/tjor-agent-<harness>:<version>`; on success use it, else `build_agent`; `tjor build` always builds — verified by unit-ish tests of resolution logic (published-hit uses pull, miss falls back) and an offline fallback case
- [x] 3.2 Config: `[images] publish`, `registry`, and version source (VERSION file) — verified by config tests

## 4. Docs & test

- [x] 4.1 README/INSTALL note: first run pulls a prebuilt image (or builds if unreachable); GHCR public-visibility one-time setting documented — verified against behavior
- [x] 4.2 `tests/integration/uid_test.sh`: run the agent image under a non-default uid, assert effective uid + home writability (the uid-agnostic guarantee) + CI job — verified green locally and on Linux
