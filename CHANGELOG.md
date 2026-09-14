# Changelog

All notable changes to tjor. Versions follow [semver](https://semver.org);
dates are release dates. Pre-1.0: minor versions may carry breaking changes.

## [0.14.0] — 2026-09-14 — Kube hardening batch (#42, #45, #47, #48, #49, #50)

### Added
- **Exfiltration-conscious investigation-profile guide (#50).**
  `docs/investigation-profiles.md`: the checklist for profiles that grant
  `pods/log` — sinkless strict-allow egress (API origin + inference only),
  view-minus-secrets RBAC with `pods/log` named explicitly, short token TTL,
  teardown denial-recap review — plus a worked policy example and an explicit
  residual-risk statement (the inference endpoint is itself an allowed content
  sink, by design). Referenced from the README's kube section and enforced by
  the doc-consistency lint. Log-volume friction at the proxy is analyzed and
  deliberately deferred (observability-first proposal recorded on #50).
- **Automatic denial recap at `tjor down` (#42).** Teardown now surfaces the
  session's denied egress unprompted — count, top denied hosts, and the
  `tjor denials` / `tjor policy add` hints — so a quietly-blocked session is
  noticed at the moment the operator is looking. Quiet when there were no
  denials; hostnames render through the shared terminal-escape sanitizer.
- **Kube credential injection is scoped to the exact API origin (#49).**
  Brokered-credential destinations matched on hostname alone, so any service
  on the API server's hostname but a different port would receive the same
  ServiceAccount token. Broker destination entries now take an optional port
  (`host:6443`, `[2001:db8::1]:6443`, parsed/matched in `tjor_identity` beside
  the shared host matcher), the proxy matches host AND port per request, and
  the kube source always emits the API server's exact origin (explicit port or
  https default 443). Port-less entries (pat/github-app configs) behave
  exactly as before. Agent images must be rebuilt (port-aware helper-wiring
  check in the entrypoint).
- **Scoped SSRF-guard exemption for the kube broker's API host (#45).** A
  private-endpoint cluster (on-prem, private AKS/EKS) resolves to a non-global
  address and was blocked by `ip_guard` even when the policy allowed it —
  forcing a global `ip_guard = false`. The launcher now passes the derived API
  host to the proxy (`TJOR_KUBE_API_HOST`), which exempts exactly that host
  (only while the kube broker is active) — the same pattern as the LLM gateway
  host. Every other host keeps full SSRF protection.

### Fixed
- **Kube-only broker sessions no longer get a poisoned GitHub git-credential
  helper (#47).** The placeholder helper was wired whenever ANY broker was
  enabled, so a broker scoped to the cluster API host alone made git send the
  literal placeholder to github.com (guaranteed 401) instead of falling back
  to ambient `gh` auth. The entrypoint now wires the placeholder only when the
  broker's hosts actually cover GitHub — decided with the proxy's own host
  matcher (`tjor_policy`/`tjor_identity`, now shipped as agent-image cargo),
  never a second matcher. Agent images must be rebuilt to pick this up.
- **`landlock.deny_paths` no longer silently disabled by `mask_dotenv = false`
  (#48).** The deny-paths masking loop was nested inside the dotenv-discovery
  toggle, so opting out of automatic `.env` masking also dropped every
  explicitly configured deny path — with no warning, in the dangerous
  direction. The two are now independent: `deny_paths` masks apply
  unconditionally; `mask_dotenv` governs only the automatic discovery.

## [0.13.1] — 2026-09-14 — Interactive sessions actually interactive (#51, #52)

### Fixed
- **`--session` accepts what tjor itself displays (#52).** tjor's messages show
  the fully-qualified session id (`<repo>-<hash8>[-<name>]`), but `--session`
  blindly re-prepended the workspace prefix — pasting the displayed id into
  `tjor down --session ...` tore down a doubled phantom id while the real
  session kept running. Resolution is now idempotent (this workspace's
  qualified ids resolve to the same session as their short names), another
  workspace's existing qualified id is honored verbatim by lifecycle commands
  (`down`/`status`/`denials`/`reset` now work from any directory) and refused
  by `tjor run` (never a silent foreign-identity launch), `tjor attach` also
  takes short names, and `tjor down` says so when nothing matched instead of
  silently "succeeding" against a session that never existed.
- **Interactive harnesses get a real PTY (#51).** `compose run -d` decides
  pseudo-TTY allocation from the compose *client's* own fds, and the launcher
  captures its output through command substitution — so the agent container was
  created **without** a PTY even from a real terminal (`tty: true` in
  compose.yaml notwithstanding). The harness then started on pipe-stdin:
  Claude Code fell into `--print` batch mode and errored, opencode's TUI hung
  silently after the startup banner, and the later `docker attach` could never
  repair it (a container's Tty is fixed at creation). The launcher now forces
  PTY allocation at creation whenever its stdin is a terminal, verifies the
  PTY actually materialized (aborts loudly otherwise), and warns loudly when
  no terminal is available (one-shot commands keep working and keep
  propagating exit codes). A new real-PTY integration test
  (`tests/integration/tty_test.sh`, via `script(1)`) drives the actual
  create-detached-then-attach flow — the path `TJOR_ATTACH_DRY` used to skip.

## [0.13.0] — 2026-09-14 — Profile-appended instructions (#C2)

### Added
- **Optional profile instruction append.** A profile may now stage
  `instructions/AGENTS.md`; if present, its content is APPENDED after the
  image's baked-in baseline instruction cargo — never a replacement — before
  that combined text is rendered into each harness's own dialect path
  (opencode `AGENTS.md` / claude `CLAUDE.md` / copilot
  `copilot-instructions.md`). `instructions` was added to the profile
  host-side staging allow-list in `tjor_profile.py`, subject to the exact same
  credential-filename/extension denylist and symlink-escape protection as
  every other allow-listed subdirectory. No profile, or a profile without
  `instructions/AGENTS.md`, behaves exactly as before (baseline only).

## [0.12.0] — 2026-09-13 — Config validation + boundary exit code

Two hardening refinements surfaced while reviewing the fail-closed paths.

### Added
- **Strict config validation (#39).** `tjor_cfg.py check` validates the user and
  trusted-repo config layers against the defaults shape and **warns loudly** on
  unknown keys (naming the file), instead of silently dropping a typo like
  `[landlok]` or `landlock.mask_dotnev` — which for a security tool fails in the
  dangerous direction (a mistyped stricter setting reads as the laxer default).
  The launcher runs it once per launch; open-ended tables (`profiles`,
  `versions`, `images.digests`, `gateway.models`) are exempt. Non-blocking.

### Changed
- **Distinct exit code for a boundary that could not be established (#40).**
  Fail-closed aborts now exit `90` (was a generic `1`), reserved for "a required
  security boundary could not be established, so tjor refused to run the agent" —
  host-side (internal-only network, egress proxy, DNS, session CA) and in-cage
  (non-root guarantee, `[landlock] mode = "require"` unavailable, propagated as
  the container exit code). A degraded-but-safe `auto` session still exits `0`.
  Documented in the README (Exit codes). **Note:** scripts that treated a
  boundary failure as exit `1` should now check for `90`.

## [0.11.0] — 2026-09-13 — Kernel-sandbox tier (Landlock, #9)

A new **hardening add-on** (loud-when-absent, not a core guarantee): inside the
cage, the harness process tree runs under a kernel-enforced Landlock allowlist
via [cplt](https://github.com/navikt/cplt) (MIT), and in-repo secret files are
masked at launch. It narrows what a compromised agent can reach *within* the
container; the container boundary is unchanged. Settles the open question in
issue #9 — Landlock works in an unprivileged container on the default Docker
engine (verified on kernel 6.8, default seccomp, no privilege changes).

### Added
- **`cplt` in the agent image**, version-pinned in `config/tjor.toml`
  (`[versions] cplt`) and sha256-gated at build like `gh`/`kubectl`.
- **`[landlock]` config**: `mode` (`auto` default / `require` / `off`),
  `mask_dotenv` (default true), and `deny_paths` (extra files to mask; only ever
  adds). Flows through the single config merge path.
- **Availability probe + four-way handoff in the agent entrypoint.** Landlock is
  probed in the enforcement context (as the agent user); *any* failure
  (`ENOSYS`/`EOPNOTSUPP`/`EPERM`/…) classifies the tier unavailable. `auto`
  degrades LOUDLY and continues; `require` aborts before the harness starts;
  `off` runs unwrapped. Fail-closed: a passing probe whose wrap then fails aborts
  the start rather than running a session that only *looks* sandboxed. One
  greppable status line (`kernel-sandbox: …`).
- **Launch-time dotenv masking** (`bin/tjor`): each `.env`/`.env.*` in the
  mounted repos (templates excluded) plus each `deny_paths` entry is masked with
  a read-only `/dev/null` bind mount — unreadable and un-unlinkable in-cage, on
  *every* runtime, even where Landlock is unavailable.

### Design note (honesty)
- Landlock is **allowlist-only** — it cannot deny a path inside a granted tree,
  so cplt's own in-workspace `.env` deny is unenforceable in a container (it says
  so at runtime; its bubblewrap fallback needs user namespaces, which the cage's
  seccomp/`cap_drop: ALL` blocks). The `.env` guarantee is therefore delivered by
  the mount masks, not by Landlock. cplt's network and command-guard layers stay
  **off**: the egress proxy remains the sole network/action boundary. Residual,
  documented: a dotenv file created mid-session is not masked.

### Tests
- New `tests/integration/landlock_test.sh` (24 checks): live-session masking +
  outside-tree kernel denial (probed inside the wrapped tree) + proxied-egress
  survival, and the full handoff matrix with Landlock forced unavailable via a
  seccomp profile (`auto` degrades and runs, `require` aborts, `off` unwrapped,
  invalid mode fatal). Checksum-gate-fails-closed verified for the cplt download.
  Full existing suite green (207 unit, 18/18 conformance, doc-consistency).

## [0.10.1] — 2026-09-06 — Gateway review follow-ups

Secret-lifecycle hygiene from an external review of v0.10.0. The core guarantee
(gateway admin surface unreachable by construction) was verified sound —
including a live check of the gateway-host-in-both-allow-and-block case; these
are the follow-ups it flagged.

### Added
- **`tjor gateway rotate-key`** — regenerate the per-install gateway master key
  (new sessions use it; running gateway sessions keep theirs until relaunched).
  The lack of rotation was previously an undocumented gap.

### Changed
- **LiteLLM image digest-pinned** (was a floating `main-stable` tag) — the
  gateway now runs exactly one image (charter L11), like every other pinned
  image.
- **ADR 0009 names the secret-delivery trade-off explicitly:** the master key
  and provider keys reach the sidecars as container env (visible via `docker
  inspect`), unlike the D2 broker's 0600 file — a different exposure surface,
  accepted within the docker-socket-trusted threat model, and forced by
  LiteLLM's env-based key mechanism.
- **`render_config` refuses a literal `api_key`** (must be `os.environ/<VAR>`),
  so an operator paste can't silently write a live secret into the on-disk
  config — enforcing the module's "this file carries no secret" guarantee.
- **`[gateway].host` must be a simple hostname label** — a dotted/real domain
  (e.g. `github.com`) would join `hosts.block` and silently break normal egress;
  now refused.
- Fixed a stale `_apply_gateway` docstring that described the enforcement as
  "path-block" (it is host-block + `paths.allow` carve-out — the exhaustive
  model, not the fragile admin-prefix list the design deliberately avoided).

### Tests
- The gateway-host-in-both-allow-and-block adversarial case is now a permanent
  regression test (block precedence wins); plus literal-key rejection, key
  rotation, and dotted-host refusal.

## [0.10.0] — 2026-09-06 — LLM gateway (D4) — the roadmap is complete

### Added
- **Optional LiteLLM gateway** (#4, D4 — the last roadmap delta). With
  `[gateway] enabled = true`, a LiteLLM sidecar runs on the **egress** network
  and the harness's `base_url` points at it, so the egress policy gains exactly
  **one** host instead of one per provider; LiteLLM fans out to whatever
  providers you configure. Off by default — a session is unchanged unless you
  turn it on.
- **Admin surface unreachable by construction.** The agent's only route to the
  gateway is the proxy, and the policy makes the gateway host **inference-only**
  via host-block + `paths.allow` carve-outs — so the entire LiteLLM management
  API (`/key/*`, `/user/*`, `/model/*`, `/ui`, and any route a future LiteLLM
  adds) is denied with no fragile prefix list, not by a password (charter L30).
- **Generated master key, never in the agent.** A per-install key is generated
  (CSPRNG, 0600, under your config dir — never a session dir, label, or config
  hash) and injected by the proxy toward the gateway host (reusing the D2
  broker path); the agent holds only a placeholder. Provider keys stay
  egress-side (gateway sidecar only). The gateway host is exempted from the SSRF
  IP-guard (it resolves to a private docker IP) — narrowly, only when enabled.
- New `python/tjor_gateway.py` (master key + LiteLLM config render + policy
  augmentation), `[gateway]` config, `litellm` compose service (egress-only),
  ADR 0009, README "LLM gateway" section. Tests: `test_gateway.py`, addon
  gateway tests, and `gateway_test.sh` (host-side wiring: key handling +
  inference-only policy). A live provider round-trip is a documented manual
  check. **All four roadmap deltas (D1–D4) are now shipped.**

## [0.9.4] — 2026-09-06 — Review follow-ups (profile denylist + doc honesty)

### Changed
- **Agent-profile credential denylist broadened** to common cloud-provider
  credential files — `service-account.json`, `application_default_credentials.json`,
  `*-key.json`, `kubeconfig`, `client_secret.json`, and `.crt`/`.cer`/`.pkcs12`
  extensions. Still a denylist *behind* the structural allow-list (definition
  subdirs only), i.e. defense in depth, not the primary boundary. Tested.
- **Doc honesty:** the archived `add-agent-profiles` design.md's "blocklist
  rejected" alternative now records that v0.9.3 shipped exactly such a denylist
  as defense in depth (the structural allow-list stays the primary gate) — so
  the design doc no longer contradicts the shipped code, matching the disclosure
  pattern used for the `add-repo-config` design.md.

## [0.9.3] — 2026-09-05 — Security review (broad re-review of v0.7.0–v0.9.1)

A five-lens external review that broadened scope to the releases that hadn't
been reviewed before surfaced one new High and two Mediums, all now fixed with
regression tests.

### Security
- **High — kube placeholder-config symlink-follow.** The kube broker's
  entrypoint (v0.7.0) renders `~/.kube/config` via a root redirect through a
  `.tmp` intermediate, but de-symlinked only the final `config`, not the `.tmp`.
  A prior session (agent-level access, no root) could plant `~/.kube/config.tmp`
  as a symlink, and the next kube-broker-enabled start would write the fixed
  placeholder *through* it, clobbering any root-reachable file — the one new
  root-write touch point that missed the project's de-symlink discipline
  (charter L26). Both `config` and `config.tmp` are now de-symlinked before the
  write. Regression-tested (a planted `config.tmp` symlink is not followed).
- **Medium — agent-profile nested credential files.** The profile allow-list
  (v0.9.0) filtered top-level directory *names* only, so a credential file
  nested *inside* a definition dir (`agent/auth.json`) was staged into the cage.
  A credential-filename/extension denylist (`auth.json`, `id_rsa`, `*.pem`, …) is
  now applied at any depth; docs corrected to state the precise guarantee
  (structural allow-list **plus** a credential denylist — tjor can't tell a
  secret from a definition by content, so don't hide secrets in a definition
  dir). Tested, including the nested case.
- **Medium — proxy stderr escape sanitization.** The identity-forgery logger
  (`_log_stripped`) printed attacker-influenced hostnames and header names raw
  to the proxy's stderr (visible via `docker logs`); now sanitized with the same
  shared filter as the denial log (v0.9.1). Unit-tested.

### Changed
- The kube broker rejects a `kube_sa`/`kube_namespace` not shaped like a
  Kubernetes DNS name (a leading `-` would be parsed as a `kubectl` flag —
  argument injection) and a malformed `kube_duration`. Secondary defense: these
  come from trust-gated config seen during `tjor trust`.
- Documentation honesty: the archived `add-repo-config` design.md now discloses
  that its sanitizer / two-step-trust / `resolve_session` items were **v0.9.1
  vulnerability fixes**, not original design; the kube design.md names "scoping
  the SA's RBAC is the operator's responsibility" as an explicit risk; the
  `tjor_safeprint` docstring notes Zalgo/homoglyph obscuring is out of scope for
  an escape-injection defense; CHANGELOG v0.9.1 severity tags aligned.

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
- **Read-only commands no longer mint credentials (high).** `status`/`down`/
  `reset`/`denials` ran the full launch path just to resolve a session path — so
  under a kube broker source (v0.7.0), `tjor denials` minted a live
  ServiceAccount token and `down` minted one while tearing down. `session_setup`
  is split into `resolve_session` (no side effects) + `session_setup` (resolve +
  broker); the read-only and teardown commands use the former.

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
- **Definitions, not credentials.** tjor stages only a structural allow-list of
  definition subdirectories (`agent`/`agents`, `command`/`commands`,
  `skill`/`skills`, `prompt`/`prompts`, `mode`/`modes`) **host-side**, and
  mounts only that staged dir read-only — so a credential/config file at the
  profile root (an `auth.json` / API key sitting beside the dirs, as in a real
  `~/.opencode`) is never copied (verified in CI). An out-of-tree symlink is
  refused. The staged definitions overlay the baseline (your definition wins on
  conflict), symlink-safe. *(v0.9.3 additionally skips known credential
  filenames nested inside a definition dir; tjor cannot distinguish a secret
  from a definition by content, so don't place secrets in a definition dir.)*
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
