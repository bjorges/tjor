# Changelog

All notable changes to tjor. Versions follow [semver](https://semver.org);
dates are release dates. Pre-1.0: minor versions may carry breaking changes.

## [0.6.1] — 2026-09-05 — Security hardening (external review, v0.5 round)

### Security
- **uid-0 root escalation (critical):** `TJOR_AGENT_UID=0` (from `sudo tjor` or
  a root-default container executor) aligned the agent user to uid 0, so `gosu`
  dropped to *nothing* and the harness ran as real root — silently defeating the
  non-root guarantee, with no test coverage. The entrypoint now refuses uid 0
  (keeps the image's built-in non-root uid) behind a hard "agent must never be
  uid 0" invariant; `uid_test.sh` gained uid-0 and non-numeric-uid regression
  cases.
- **`--dir` guardrails:** `tjor run --dir` now refuses sensitive host paths
  (`/`, `/etc`, `/var`, `/usr`, the home directory and its ancestors, and
  credential dirs `~/.ssh` `~/.aws` `~/.kube` `~/.gnupg` `~/.docker` `~/.config`
  `~/.gcloud` `~/.azure`) unless `--unsafe-dir` is given, and dedupes repeated
  `--dir` values — mounting those read-write would dissolve the very boundary
  the cage enforces.

### Changed
- **Prebuilt-image trust (ADR 0008):** a git checkout now *always* builds the
  agent image locally from the audited Dockerfile (never silently replaced by a
  pull); pinning `[images.digests].<harness>` gives a **verified** pull (exactly
  the published image, independent of the mutable tag); a bare-tag pull prints
  an explicit integrity notice instead of being framed as a pure speed feature.
  New `INSTALL.md` and ADR 0008 document the trade-off. `publish = true` stays
  the default, recorded in the ADR as a pending maintainer decision rather than
  silently flipped.
- **`safe.directory` scoped:** git no longer trusts `*` inside the cage — only
  the exact repos the operator mounted (the workspace + each `--dir`, via
  `TJOR_SAFE_DIRS`), narrowing the hostile-repo git-config surface (residual
  risk documented, bounded by the non-root agent + no-egress cage).

## [0.6.0] — 2026-09-05 — Per-repo config + policy ergonomics

### Added
- **Policy ergonomics** (#23): `tjor denials [session]` surfaces what egress a
  session had blocked (host + rule); `tjor policy add <host>` widens the active
  allow-list in one command; `tjor policy <url> --explain` names the active
  policy and the deciding rule. The proxy records each denied egress to a
  session denial log.
- **Per-repo config** (#22): a repo may carry `.tjor/policy.toml` and
  `.tjor/config.toml`, honored **only after `tjor trust`** approves their exact
  content (content-hash pinned; any edit revokes trust) — an unapproved repo
  config is ignored with a warning. `tjor init` scaffolds a starter `.tjor/`.
  When trusted, the repo layer sits most-specific in config/policy resolution.
- README: install-via-brew quickstart, an egress-policy section with the
  deny→`denials`→`policy add` loop, and the per-repo config/trust flow.

## [0.5.0] — 2026-09-05 — Multi-repo sessions + prebuilt images

### Added
- **Multi-repo sessions** (#20): `tjor run --dir <path>` (repeatable) mounts
  additional repositories at their host paths, writable — one agent across
  several repos. The primary workspace still anchors the session (id,
  identity, cwd unchanged).
- **Prebuilt, uid-agnostic agent images** (#21): the agent image no longer
  bakes the host uid — the entrypoint aligns the agent user to the host uid
  at container start, so one image serves any user. A release-tag CI workflow
  publishes multi-arch (amd64+arm64) images to GHCR; an installed copy pulls
  the image for its version on first run instead of building (git checkouts
  and offline still build locally; `[images] publish = false` to force build).

### Changed
- Bind-mounted repos are trusted for git (`safe.directory = *` inside the
  cage) so git works regardless of the uid it runs as.

## [0.4.1] — 2026-09-05 — Security fixes (external review round 5)

### Fixed
- **Broker revoke-on-teardown now actually fires.** `tjor down`/`gc`
  previously force-removed the proxy (SIGKILL), so mitmdump's `done()` hook —
  where credential revocation lives — never ran; auto-expiry was the *only*
  revocation. The proxy is now stopped gracefully (SIGTERM + grace) before
  removal so revocation runs on the normal teardown path.
- **`tjor reset creds` now wipes the broker directory** (the GitHub App
  private key, not just the ~1h token) — previously only `reset all` removed it.
- **`tjor reset` TOCTOU hardened.** With persistent containers a live agent
  could race a symlink swap between the ancestor check and the delete; reset
  now refuses a running session (`tjor down` first, or `--force`).
- `broker.json` is created `0o600` atomically (no brief world-readable window).
- Broker teardown reports revoke success/failure accurately instead of
  always logging "revoked".
- GitHub App token expiry parsed as UTC (`calendar.timegm`), robust to `TZ`.
- `tjor attach` field-parses on the same control separator as `ls`/`gc`.
- README summary reconciled with the roadmap table (D2 shipped); a CI
  doc-consistency lint now enforces this structurally.

## [0.4.0] — 2026-09-05 — Credential broker (D2)
Per-session, short-TTL GitHub credentials injected at the proxy toward
configured hosts only; the agent holds a placeholder and never possesses the
real secret (CI scans a live container to prove it). `github-app` + `pat`
sources, host-scoped and fail-closed, teardown revocation. ADR 0007.

## [0.3.1] — 2026-09-05 — Security fixes (review round 4)
Critical `tjor reset` symlink-escape across nested tiers; IPv4-compatible
IPv6 SSRF form; session-collision guard; threat-model docs (ADR 0006).

## [0.3.0] — 2026-09-05 — Session lifecycle (D3)
`ls` (with live boundary re-check), `attach`, `gc`, tiered `reset`, concurrent
named/detached sessions per repo.

## [0.2.1] — 2026-09-05 — Security fixes (review round 2)
`rawtcp=false` (CONNECT passthrough bypass); version-independent IP guard;
narrowed capabilities.

## [0.2.0] — 2026-09-05 — Session identity (D1)
Vendor-neutral `x-agent-*` schema; proxy verifies/strips forgeries; opt-in
injection toward configured hosts.

## [0.1.1] — 2026-09-05
In-cage `gh auth login` fix (official gh binary); brew-ready launcher.

## [0.1.0] — 2026-09-04 — Cage core
Internal-only network, dual-homed fail-closed egress proxy, DNS zone scoping,
non-root agent, adversarial conformance suite.
