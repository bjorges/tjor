# ADR 0008 — Prebuilt-image trust model

**Date:** 2026-09-06 · **Status:** accepted

v0.5.0 added prebuilt agent images: an *installed* (non-git) copy of tjor
pulls `ghcr.io/bjorges/tjor-agent-<harness>` on first run instead of building
locally (#21). This ADR records the security trade-off that change makes — it
was shipped without one, which this ADR corrects.

**The trust shift.** A local build establishes trust from source you can
audit: an in-repo Dockerfile, base images pinned by digest, and every tool
download SHA256-gated (charter L23). A tag pull replaces that with trust in
**GHCR + the publish pipeline** (a `GITHUB_TOKEN`-authenticated CI job). A
compromised token, pipeline, or registry could serve a different image than
the audited Dockerfile would build, and a bare-tag pull verifies only "the
pull succeeded" — not *what* was pulled.

**Decisions.**
1. **A git checkout always builds locally, unconditionally.** The
   security-conscious / early-adopter path is never silently replaced by a
   pull. Only installed copies pull.
2. **Digest pinning is the verified path and is preferred.** When
   `images.digests.<harness>` is set (a `sha256:...` recorded per release),
   the launcher pulls *by digest* — the image is then exactly what was
   published, independent of the mutable tag, as verifiable as a local build.
3. **A bare-tag pull is allowed but never silent.** Without a configured
   digest the launcher pulls the version tag and prints an explicit integrity
   notice naming the trade-off and how to opt out (`[images] publish=false`,
   or run from a checkout). It is not framed as a mere speed feature.
4. **`safe.directory` is scoped, not `*`.** Mounted repos are trusted by git
   only for the exact paths the operator mounted, limiting the hostile-repo
   git-config surface (see the entrypoint; residual risk bounded by the
   non-root agent + no-egress cage).

**Open question deferred to the maintainer:** whether `publish` should default
to `true` (fast first run, tag-pull trust) or `false` (build-from-source by
default) for a security-focused tool. It currently defaults to `true` with the
notice above; digest pinning is the intended path to make that default fully
defensible. Flipping the default, or requiring digests, is a maintainer
sign-off, recorded here as pending rather than silently chosen.

**Not yet done (follow-ups):** image signing / attestation (cosign), and
automatic per-release digest recording so the digest path is the default
without manual entry.
