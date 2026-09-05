# Design: add-prebuilt-images

## Context

The agent image bakes `AGENT_UID` at build (Dockerfile `useradd -u ${AGENT_UID}`), and the launcher passes `--build-arg AGENT_UID=$(id -u)` — fine for local builds, fatal for a shared published image. The entrypoint already runs as root before `gosu agent`, so it has the privilege to re-align the uid at start. GHCR is the natural registry (Actions `GITHUB_TOKEN` has `packages:write`).

## Goals / Non-Goals

**Goals:** first `tjor run` pulls instead of builds; one image works for any host uid; published images reproducible from the pins; local build still works offline.

**Non-Goals:** image signing/attestation (follow-up), non-GHCR registries, changing the pinned-version source of truth.

## Decisions

- **Align uid at start, not build.** Dockerfile creates `agent` with a fixed default uid (10001, unlikely to collide). The entrypoint, as root: if `TJOR_AGENT_UID` is set and differs from the current agent uid, `usermod -o -u "$TJOR_AGENT_UID" agent` and `groupmod` + reconcile ownership of `/home/agent` (skip the bind-mounted contents chown when a uid-mapping VM makes it unnecessary/slow — the existing `.config/.local` chowns already handle what matters). Then `gosu agent`. `-o` (non-unique) avoids failures when the target uid already exists in the image. *Alternative:* run the container with `--user`; rejected — the entrypoint needs root for CA/cargo/uid setup first.
- **Launcher image resolution.** `resolve_agent_image <harness>`: if `images.publish` is enabled (default) and a version tag exists, try `docker pull ghcr.io/<owner>/tjor-agent-<harness>:<tjor-version>`; on success use it, else fall back to `build_agent`. A dev version (no matching published tag) or offline simply builds. `tjor build` bypasses resolution. The launcher no longer passes `AGENT_UID` as a build-arg for the *published* path; local builds keep working with the default uid + runtime alignment (so even local builds become uid-agnostic — a bonus).
- **Version tag = the tjor version.** Derived from a `VERSION` file / git tag; published images are `:<version>` + `:latest`. A checkout between releases has no published tag and builds locally — correct.
- **Publish workflow** (`publish-images.yml`, on tag push `v*`): buildx multi-arch (amd64+arm64) for each harness + proxy + conformance, push to GHCR, using the same build-args (pins) as the launcher. Login via `GITHUB_TOKEN`. This is separate from the test CI so a failed publish never blocks tests.
- **Reproducibility.** The publish workflow reads the same `config/tjor.toml` pins; the checksum gates in the Dockerfile guarantee the published image installed exactly the pinned tools.

## Risks / Trade-offs

- **INTEGRITY (added post-review; see ADR 0008).** A tag pull trusts GHCR + the publish pipeline rather than the audited local Dockerfile — a compromised token/pipeline/registry could serve a different image, and a bare-tag pull verifies only that the pull succeeded, not *what* was pulled. Mitigations: git checkouts always build locally; digest pinning (`images.digests.<harness>`) gives a verified pull; a bare-tag pull prints an explicit integrity notice. The `publish=true` default is flagged for maintainer sign-off in ADR 0008.
- **First pull is a network dependency** — mitigated by the always-available local-build fallback; offline/private users are unaffected.
- **uid re-alignment cost**: `usermod` is fast; chowning a large bind-mounted home could be slow, so only the image-owned skeleton and the XDG dirs are chowned (as today), not the whole mounted tree.
- **A published image lagging a config pin bump**: the version tag ties an image to a release; a local checkout with newer pins and an older published tag builds locally (version mismatch → no pull), so pins and image never silently diverge.
- **GHCR package visibility** must be public for anonymous pull — a one-time repo setting; documented.

## Verification approach

An integration test that runs the agent image under a **non-default uid** (simulating a different host user) and asserts the agent runs as that uid and can write its home — the core uid-agnostic guarantee, testable without publishing. The publish workflow is exercised on the next real tag; a dry `buildx build --platform amd64,arm64` (no push) in CI proves multi-arch builds succeed.
