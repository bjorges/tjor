# Proposal: add-prebuilt-images

## Why

Every user builds the agent image on their first `tjor run` — apt plus downloading opencode/gh, minutes of wait, and the single most likely place a fresh `brew install` fails. Publishing prebuilt, digest-pinned images turns first-run into a fast pull. This is the highest-leverage adoption fix.

A blocker must be removed first: the agent image bakes `AGENT_UID=$(id -u)` at **build** time, so an image built on one machine has the wrong uid for another user. A published image must be **uid-agnostic** — the agent user's uid is aligned at container **start**, from the host uid the launcher passes.

## What Changes

- **Runtime uid alignment.** The agent image is built with a fixed default uid; the entrypoint (as root) aligns the `agent` user to `TJOR_AGENT_UID` (the launcher passes `$(id -u)`) before dropping privileges, and chowns its home if the uid changed. This makes the image portable across users — and removes the per-uid local rebuild.
- **Published images.** A release-triggered CI workflow builds each harness image (opencode/claude/copilot) multi-arch (amd64+arm64) and pushes to `ghcr.io/bjorges/tjor-agent-<harness>`, tagged by the tjor version, with a `latest` moving tag. Proxy and conformance images too.
- **Pull-or-build launcher.** With a published registry configured (default: the project's GHCR), `tjor run` uses the published image for the current tjor version if present, pulling it; otherwise it builds locally (today's behavior). `tjor build` still forces a local build; a config/flag can prefer local.
- Published images remain reproducible from the pinned tool versions/digests in `config/tjor.toml` — the registry is a cache of the build, not a second source of truth.

Out of scope: signing/attestation of published images (a follow-up), and a non-GHCR registry.

## Capabilities

### New Capabilities

- `image-distribution`: uid-agnostic agent images, a published multi-arch registry, and a launcher that prefers a published image for the current version, falling back to a local build.

### Modified Capabilities

- `cage-image`: the agent user's uid is aligned at runtime rather than baked at build (the non-root and cargo requirements are unchanged).

## Impact

- Code: entrypoint (uid alignment), Dockerfile (default uid; drop the host-uid build-arg dependency), launcher (image resolution: published-by-version vs local build), a publish CI workflow, config keys for the registry, and an integration test that a uid-agnostic image runs correctly under a non-default uid.
- No breaking changes for existing users: without a reachable published image, everything builds locally as today.
