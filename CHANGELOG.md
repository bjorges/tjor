# Changelog

All notable changes to tjor. Versions follow [semver](https://semver.org);
dates are release dates. Pre-1.0: minor versions may carry breaking changes.

## [0.9.2] — 2026-09-05 — Robust safe.directory scoping

### Fixed
- **`TJOR_SAFE_DIRS` is now newline-delimited, not `:`-delimited.** This is the
  list of mounted repos the launcher passes to the entrypoint to scope git's
  `safe.directory` (the workspace + each `--dir`). A colon is legal in a Linux
  directory path, so a `:` separator could mis-split a path containing one —
  trusting a fragment and leaving the real repo untrusted (git would then refuse
  it as dubiously-owned). Not exploitable (it fails closed), but a sharp edge.
  Paths containing a newline — pathological and unrepresentable in a git config
  value — are now refused at launch. Regression-tested: a colon-bearing path
  stays intact in `safe.directory` and is not split.

## [0.9.1] — 2026-09-05 — Security hardening (trust-review + read-only commands)

### Security
- **Terminal-escape injection in `tjor trust` (critical).** The trust review
  piped the untrusted `.tjor` file to the terminal raw, so a hostile config
  could embed ANSI/OSC/bidi escapes to hide or spoof what the operator reviews —
  approving bytes other than what they saw, defeating the content-hash gate. A
  new `tjor_safeprint` renders every C0/C1 control, DEL, and Unicode
  format/bidi code point as a visible token; wired into the trust review **and**
  the denial-log display (a denied hostname is attacker-influenced too), and the
  proxy sanitizes the host as it writes the denial log.
- **Read-only commands no longer mint credentials.** `status`/`down`/`reset`/
  `denials` ran the full launch path just to resolve a session path — so under a
  kube broker source (v0.7.0), `tjor denials` minted a live ServiceAccount token
  and `down` minted one while tearing down. `session_setup` is split into
  `resolve_session` (no side effects) + `session_setup` (resolve + broker); the
  read-only and teardown commands use the former.

### Changed
- `tjor trust` is a genuine two-step gate: `--show` reviews only; approval needs
  interactive confirmation or `--yes`. `tjor policy add` re-approving a *trusted
  repo* policy is now confirmed (or `--yes`), not silent — an agent's suggested
  `policy add` can't quietly re-bless a repo file.
- `tjor policy add` verifies the host actually reached the effective allow-list
  (a regex insert into a preceding multi-line string is valid TOML but a silent
  no-op — now refused loudly); `tjor trust` approve writes the store `0o600`
  atomically (was a write-then-chmod TOCTOU); the denial log is capped per
  session; `--dir` sensitive-path refusal now also covers
  `~/.local/share/keyrings` and `~/.password-store`.

## [0.9.0] — 2026-09-05 — Agent profiles (opt-in, credential-safe)

### Added
- **Agent profiles** (#29): opt a session into your own harness definitions.
  `tjor run --profile-dir ~/.opencode` (ad-hoc) or `--profile <name>` (from a
  `[profiles]` map in config) overlays a host directory of agents/commands/
  skills onto the image's baseline instructions — so a caged session can use
  *your* setup, reused across sessions.
- **Credentials never cross the boundary.** tjor stages only an allow-list of
  definition subdirectories (`agent`/`agents`, `command`/`commands`,
  `skill`/`skills`, `prompt`/`prompts`, `mode`/`modes`) **host-side**, and
  mounts only that staged dir read-only. An `auth.json` / API key sitting
  beside the definitions (as in a real `~/.opencode`) is never copied and
  cannot reach the cage — verified in CI (a secret placed in the source appears
  nowhere in the container). An out-of-tree symlink is refused. The staged
  definitions overlay the baseline (your definition wins on conflict),
  symlink-safe.
- Opt-in *is* the trust decision: a profile is you naming your own directory,
  so `--profile`/`--profile-dir` needs no separate `tjor trust` (unlike a repo's
  `.tjor/`, which rides along with code). A profile carries instructions the
  agent will follow; its content must already be in the active harness's format
  (tjor deploys, it doesn't translate).

## [0.8.0] — 2026-09-05 — Claude Code + Copilot CLI fully wired

### Added
- **All three harnesses are now wired, not just installed** (#24). Previously
  only opencode got instruction cargo + self-update disabled; Claude Code and
  Copilot CLI booted but ran unconfigured. Now the entrypoint deploys the
  cage's neutral instructions into each harness's own dialect path — opencode
  `~/.config/opencode/AGENTS.md`, Claude Code `~/.claude/CLAUDE.md`, Copilot CLI
  `~/.copilot/copilot-instructions.md` — from a single neutral source (no
  content drift), symlink-safe as before. `TJOR_HARNESS` drives it (a comma
  list works for a multi-harness image).
- **In-session self-update is disabled for every harness** so the
  image-pinned version can't drift under the agent: opencode via its config
  (`autoupdate=false`), Claude Code via `DISABLE_AUTOUPDATER`/`DISABLE_UPDATES`,
  Copilot CLI via `COPILOT_AUTO_UPDATE=false` (image ENV).
- Default egress policy adds `claude.ai` and `platform.claude.com` for Claude
  Code's interactive login (API-key / brokered use needs only `api.anthropic.com`,
  already allowed).

### Notes
- CI verifies each harness through the **real entrypoint**: the neutral cargo
  lands at the harness's dialect path and self-update is disabled (per-harness
  matrix). A live "boots + does a real task" check needs model credentials and
  is a documented manual step.
- `pi` (a fourth harness) is deferred — see #34.

## [0.7.0] — 2026-09-05 — Kubernetes credential broker

### Added
- **Kube broker source** (#26): `[broker] source = "kube"` lets a caged agent
  operate a Kubernetes cluster **without ever holding a cluster credential**.
  At each launch tjor mints a short-TTL ServiceAccount token on the host
  (`kubectl create token <kube_sa> -n <kube_namespace> --duration
  <kube_duration>`, using your kubeconfig for cluster auth) and the proxy
  injects it as the bearer token toward the API server host **only** — derived
  from your current context, or pinned via `kube_api_host`. The agent gets a
  placeholder kubeconfig; the real token stays in the proxy sidecar and never
  enters the cage. **RBAC is the action policy**: bind the SA to whatever Role
  fits the session and the cluster rejects anything beyond it, by construction —
  the boundary, not the prompt. Reuses the D2 `pat` injection path (already
  conformance-tested); fail-closed and loud if `kubectl` is absent or minting
  fails. Allow the API host in your egress policy (tjor prints the exact `tjor
  policy add` line at launch).
- The agent image now ships a pinned, checksum-gated `kubectl` (per-arch); the
  entrypoint renders the placeholder kubeconfig with the same tested
  `tjor_kube.py` the launcher uses to derive the API host.

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
