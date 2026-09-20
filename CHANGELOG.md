# Changelog

All notable changes to tjor. Versions follow [semver](https://semver.org);
dates are release dates. Pre-1.0: minor versions may carry breaking changes.

## [Unreleased]

Two low-priority, non-blocking review items (v0.18.9 review): an availability
weakness in the resolver negative-cache, and defense-in-depth ordering in the
fail-closed handlers. No security-boundary change; no Critical/High outstanding.

### Fixed
- **Negative-cache no longer gets stuck for a persistently-failing host
  (availability).** `_negative_cache` preserved a transient-failure entry's
  timestamp to stop coalesced waiters from extending the window — but it kept
  re-inheriting the original timestamp even after the window had expired, so a
  persistently black-holed/timing-out host stayed perpetually expired and
  re-resolved on every request, silently weakening (not defeating) the
  resolver-pool DoS guard for that host. The timestamp is now preserved only
  while the prior entry is still within its window; once expired, a fresh window
  starts. Not a security bypass — fail-closed behavior is unchanged.

### Security
- **Fail-closed handlers set the deny action before logging (defense in depth).**
  The exception handlers in `server_connect`, `http_connect`, and `request`
  logged a diagnostic to stderr *before* assigning the fail-closed response/error.
  If stderr I/O itself failed (an operational condition, not attacker-triggerable
  over the network), the fail-closed action would be skipped. Each handler now
  sets the response/error first and logs afterward inside a nested guard, so a
  logging failure can never undo the fail-closed outcome.

## [0.18.9] — 2026-09-20 — Deny hooks fail closed (denial-log bypass)

Closes a Critical review finding in the v0.18.7 wiring: an exception in the
denial-log call could fail a policy denial OPEN. The deny-enforcing hooks now
fail closed like the rest of the addon, and the detector is total by
construction. No boundary change.

### Security
- **The deny-enforcing hooks now fail closed; the denial log can no longer fail a
  denial open (#6 review, Critical).** `_log_denial` (added in v0.18.7) runs
  inside `http_connect` and `request` *before* the 403 is set, and a mitmproxy
  hook exception is logged but does not re-run the hook body — so a throw in
  `_log_denial` would skip the 403 and forward an already-denied request to its
  real destination. `TJOR_DENIAL_LOG` is set by default, so this was live. Both
  hooks now wrap their body in a fail-closed guard (matching `server_connect` and
  the module's stated invariant: an addon exception must never let a request pass
  unfiltered) — any exception yields a 403 (`x-tjor-rule: fail-closed:hook-error`).
  In defense in depth, `_log_denial` is now total (swallows every failure, not
  just `OSError`), and the detector's `redact()`/`contains_secret()` are total by
  construction (a per-pattern guard, so a pathological attacker-controlled input —
  e.g. a multi-KB `BEGIN PRIVATE KEY` opener with no closer that could recurse in
  the regex engine — can never make them raise).

### Fixed
- Detector polish (review nits): the GitHub-token comment now lists the `ghu_`
  variant the regex already matched; `tjor_secrets._main` follows the sibling
  `sys.argv[1:]` convention; added off-by-one boundary tests for the token shapes.

## [0.18.8] — 2026-09-20 — Fail closed on unresolvable (DNS-rebind gap)

Closes a Critical review finding: v0.18.6's resolver bound re-widened the #41
DNS-rebind vector for an already-allowlisted host. The egress guard now fails
closed on an unresolvable host instead of leaving the connection unpinned. No
change to any other boundary.

### Security
- **An unresolvable host now fails closed, closing a re-widened DNS-rebind gap
  (#41 regression from #61; review-driven).** The IP guard permitted an
  unresolvable host and left the connection *unpinned*, so mitmproxy performed
  its own independent, unguarded DNS resolution at connect time — the exact
  resolve-and-pin TOCTOU #41 was built to close. That carve-out was reachable
  only on a genuine fast failure until v0.18.6 bounded the OS resolver
  (`RES_OPTIONS`, #61): a black-holed *allowlisted* host now gives up in ~2s
  (below the addon's 5s guard timeout) and fell into the permit-unpinned branch,
  letting a malicious nameserver silence the guard's lookups and then answer only
  mitmproxy's later, unguarded query with an internal IP. `_validated_addresses`
  now treats an unresolvable host exactly like a resolve-timeout — deny and
  briefly negative-cache — so the guard never permits a connection it cannot pin,
  and the security outcome no longer depends on *which* timeout fires first. The
  negative-cache also stops a black-holed allowlisted host re-consuming a
  resolver worker on every request. `server_connect` no longer has an unpinned
  path: if it ever has no validated address, it kills the connection. A host that
  genuinely does not resolve is now denied with an ip-guard reason rather than
  failing at mitmproxy's own connect — functionally identical (nothing connects),
  and fail-closed. A unit regression proves a fast `OSError` (a black-hole giving
  up quickly) fails closed and is negative-cached.

## [0.18.7] — 2026-09-20 — Discovered-secret scrubbing (design-first)

Establishes the mechanism for discovered-secret scrubbing (#6) design-first: an
ADR fixes the risk framing and the false-positive stance, a small reusable
detector redacts known secret shapes, and it is wired into one low-risk,
tjor-owned sink (the denial log) as proof. The high-yield boundaries are mapped
and deferred to tickets. Additive; no security-boundary change.

### Added
- **Discovered-secret scrubbing, design-first (#6).** A distinct risk from the
  broker/gateway (which protect platform-issued secrets): an *already-existing*
  secret the agent reads from repo content or tool output, quotes, and then
  persists. `docs/decisions/0010-secret-scrubbing.md` records the risk model, the
  three boundaries (tjor-persisted logs/output, the egress inference stream, the
  harness's own memory files), why only the first is wired now, and the
  conservative known-shape detection stance (no entropy). A new stdlib-only
  detector, `python/tjor_secrets.py`, exposes `redact(text)` /
  `contains_secret(text)` — matching provably-secret shapes (AWS/Google keys,
  GitHub/Slack tokens, PEM private-key blocks) and leaving UUIDs, git SHAs,
  base64, and prose untouched — plus a `redact` stdin→stdout CLI. It ships in the
  proxy image.

### Security
- **The session denial log redacts discovered secrets (#6, proof wiring).**
  `_log_denial` now passes the attacker-influenced content it records through
  `tjor_secrets.redact()` before writing, so a secret quoted into a denied value
  is stored as `[redacted:<kind>]` rather than in the clear. Redaction is
  fail-safe and never breaks logging. A denied hostname rarely carries a secret,
  so this fires seldom in practice — it is the single low-risk, tjor-owned sink
  chosen to prove the detector end-to-end; the high-yield sinks — egress bodies
  (#62) and the harness's own memory files (#63) — are deferred to tickets,
  deliberately. No boundary change.

### Fixed
- **Proxy image build context: allowlist the new detector.** The detector was
  added to the proxy Dockerfile COPY but not to the allowlist-style
  `.dockerignore` (`deny *`, re-include each COPY source), so the build context
  dropped it and every image build failed — invisible without a local Docker
  daemon. `.dockerignore` now re-includes `python/tjor_secrets.py`, and
  `tests/doc_consistency.sh` asserts every image-Dockerfile COPY source is
  allowlisted, so this class of build break is caught locally going forward.

## [0.18.6] — 2026-09-20 — Bounded proxy resolver + saturation signal

Closes the disclosed v0.18.4 residual (#61): bound the proxy's OS DNS resolver
so a hung lookup recovers fast (provably, not by assumption), and surface an
operator signal when the resolver cap saturates. No security-boundary change.

### Security
- **The proxy's OS DNS resolver is bounded, and cap saturation is observable
  (#61, closes the v0.18.4 residual).** The v0.18.4 pool hardening assumed a
  hung `getaddrinfo()` eventually gives up; the proxy image never bounded it, so
  a black-holed lookup could hang a worker for the OS default (tens of seconds),
  freeing the resolver cap slowly. The proxy entrypoint now exports a small,
  tunable `RES_OPTIONS` (glibc; default `timeout:1 attempts:2`, override via
  `TJOR_PROXY_RES_OPTIONS`), so a hung/black-holed lookup returns within a
  bounded wall time and its worker frees fast — the cap self-recovers without a
  proxy restart, making the "self-recovering" property provable. And when the
  cap saturates, the proxy emits a rate-limited operator signal to stderr, so a
  sustained many-slow-host condition is visible rather than silent. No
  security-boundary change: still fails closed, and a black-holed *allowed* host
  hits the existing "unresolvable → permitted (nothing can connect)" path fast
  rather than the slower `resolve-timeout` deny (both safe — nothing connects).

## [0.18.5] — 2026-09-20 — Boundary results matrix + review follow-ups

Publishes the adversarial boundary results matrix (#38) — the cage's guarantees
enumerated, generated from the suites and drift-checked — plus the non-blocking
v0.18.4 review follow-ups. Docs and tooling only; no runtime behavior change.

### Added
- **Published adversarial boundary results matrix (#38, builds on #13).** The
  cage's adversarial guarantees are proven by the conformance probes and the
  kernel-sandbox suite, but their results lived only in CI logs. `docs/boundary-matrix.md`
  now enumerates each guarantee, the probe that proves it, its suite, and the
  spec capability it backs — generated from the suite sources by
  `python/gen_boundary_matrix.py` and referenced from the README. A registry
  maps every probe/check and the generator asserts it equals the names parsed
  from source (a new/renamed/removed probe with no mapping, or a stale entry,
  fails), while `tests/doc_consistency.sh` (`--check`) also diffs the committed
  matrix against a fresh render — so it can't drift. Status is coverage (each
  guarantee is backed by a live probe the CI conformance/landlock jobs run),
  not embedded per-run pass/fail.

### Changed
- **v0.18.4 review follow-ups (no behavior change).** A three-lens review of
  v0.18.4 approved it with no critical/high findings; these close the
  non-blocking notes: the resolve-timeout `why` token is a shared constant
  (`_RESOLVE_TIMEOUT_WHY`) so the cache-write and TTL-selection sites can't
  desync via a typo; a re-entrant resolve-timeout preserves the original
  negative-cache timestamp so coalesced waiters can't extend the window past
  `_RESOLVE_NEGATIVE_TTL` (defensive — only reachable under concurrency); the
  kube API-host/origin comma-refusal message now names both `host` and
  `origin` (it previously always blamed the host); and `_env_pos`'s `cast`
  parameter is typed. The disclosed Medium residual (many *distinct* slow-DNS
  hosts can still saturate the cap, fail-closed) is tracked as #61 (bound the
  OS resolver timeout / make cap saturation observable).

## [0.18.4] — 2026-09-19 — Egress-guard DNS availability hardening

Closes the v0.18.2 re-review High: the bounded-resolution fix bounded each call
but not the shared resolver pool, so slow-DNS load could durably deny the guard
(fail-closed). Resolution now coalesces per host, caps concurrent lookups with
fail-fast, and briefly negative-caches timeouts. Bundles the #60 structured-
reason robustness and the #57 api_host comma check from the same review.

### Security
- **Egress guard stays available under slow-DNS load (#59 re-review).** A
  re-review found the v0.18.2 bounded-resolution fix bounded each *call* but not
  the shared resolver pool: a sustained attack on a wildcard-allowed slow-DNS
  host could exhaust the 8-worker pool, after which every subsequent resolution
  was denied until the attack stopped — fail-closed (deny-all, not a bypass),
  but a durable denial of the guard. Hardened, stdlib-only: per-host in-flight
  **coalescing** (concurrent requests to one host share a worker), a **cap** on
  concurrent distinct resolutions that fails closed *fast* instead of queueing a
  backlog, and a brief **negative-cache** of resolve-timeouts so repeat hits
  don't re-consume capacity (this reverses v0.18.2's "timeouts are never
  cached" — recovery is now delayed by the short window instead of instant).
  The resolver bounds are env-tunable (`TJOR_RESOLVE_TIMEOUT`,
  `TJOR_RESOLVE_WORKERS`, `TJOR_RESOLVE_MAX_INFLIGHT`,
  `TJOR_RESOLVE_NEGATIVE_TTL`) and the pool is shut down on teardown. Residual,
  documented: many *distinct* genuinely-hung hosts can still saturate the cap;
  excess fails closed fast and capacity returns as workers hit the OS resolver
  timeout (no proxy restart).

### Changed
- **Egress denial reasons are structured, not free-text (#60 review).**
  `_address_public` now returns a `(ok, reason_class, detail)` shape; the
  agent-facing redaction keys off the stable `reason_class` token instead of
  string-prefix-matching free text, so rewording the detail can never silently
  re-leak the resolved IP. Added an end-to-end test for the `server_connect`
  pin-kill redaction of a non-global reason (the path that had no coverage).
- **`api_host`/origin comma check (#57 review).** A comma in a derived kube API
  host or origin is refused (it would desync the comma-joined env lists),
  parity with the context-name check.

## [0.18.3] — 2026-09-19 — Redacted egress denial reasons

Closes #60: a guard denial no longer hands the in-cage agent the specific
internal address the hostname resolved to — the agent-facing reason is
generalized to its class while the operator denial log keeps the full detail.

### Security
- **Egress guard denials no longer disclose the resolved address to the agent
  (#60).** A guard denial's reason (e.g. `ip-guard:non-global address 10.0.0.5`)
  was returned to the agent in the 403 body and `x-tjor-rule` header (and the
  resolve-and-pin connection-kill error), handing back the concrete internal
  address the hostname resolved to. The agent-facing reason is now generalized
  to its class (`ip-guard:non-global-address`, `ip-guard:unparseable-address`)
  at the response sites, while the operator denial log (`tjor denials`) keeps
  the full detail unchanged. Literal-free reasons (policy blocks, default-deny,
  resolution timeout, exemptions) are shown to the agent unchanged. Low/Info,
  defense-in-depth — the agent resolved the name itself.

## [0.18.2] — 2026-09-19 — Bounded egress-guard DNS resolution

Closes #59: the egress guard resolved hostnames synchronously on mitmproxy's
event loop, so a hung DNS answer could stall a session (self-DoS). Resolution
is now time-bounded and fails closed on timeout.

### Security
- **The egress guard's DNS resolution is time-bounded (#59).** The
  resolved-address guard resolved hostnames with a synchronous `getaddrinfo`
  on mitmproxy's event loop (on a cache miss, from both the verdict path and
  the `#41` `server_connect` pin), so an adversarial in-cage agent could steer
  egress at a hostname whose DNS hangs and stall its own session's event loop
  for the full resolver timeout, wedging every concurrent flow (a self-DoS;
  not cross-tenant, not a boundary bypass). The resolver now runs in a small
  capped worker pool with a `_RESOLVE_TIMEOUT` (5s) bound: a lookup that
  exceeds it fails closed (request denied `ip-guard:resolve-timeout`,
  connection killed) and is not cached, so a transient stall denies only that
  attempt. A *fast* unresolvable host (NXDOMAIN) keeps its existing permitted
  behavior — only exceeding the time bound is treated as a failure.

## [0.18.1] — 2026-09-19 — Multi-cluster review follow-ups

Robustness and spec-conformance follow-ups from a three-lens review of the
v0.18.0 multi-cluster kube broker (no critical/high findings): reject commas in
context names (they could desync the context↔server pairing), fail closed in
the kube injector like the pat path, wire kube broker teardown, and cover the
previously-untested rejection branches. Plus the v0.18.0 CI test-only fix.

### Security
- **Multi-cluster review follow-ups (#57).** From a three-lens review that
  approved v0.18.0 with no critical/high findings, two independently
  cross-confirmed Medium items and several robustness gaps are closed:
  - **Context names are rejected if they contain a comma.** `TJOR_KUBE_CONTEXTS`
    is comma-joined and re-split by the entrypoint, so a comma in a context
    name could desync the context↔server pairing — making `kubectl config
    use-context prod` silently target another cluster's (correctly
    authenticated) API server. No credential leak (the proxy's token map is
    keyed by real origin), but it undermined per-cluster precision.
  - **The kube injector now fails closed like the pat path.** Toward a
    configured cluster origin whose credential is momentarily unavailable,
    `_apply_broker` strips the agent's placeholder `Authorization` rather than
    forwarding it (via a new `KubeMultiBroker.covers()`), matching the
    documented "placeholder is stripped, never forwarded" contract.
  - **Kube broker teardown is wired.** `TjorPolicy.done()` now calls
    `KUBE_BROKER.teardown()` (it was implemented and tested but never invoked),
    satisfying the credential-broker spec's teardown requirement for the kube
    source.
  - Added tests for the duplicate-context-name and comma-in-context rejection
    branches; restored the #58 active-context TOCTOU accepted-risk note for the
    flat/back-compat path (dropped in the multi-cluster rewrite); `zip(strict=True)`
    on the origin/token pairing; and removed the per-call re-import in
    `KubeMultiBroker`. The deferred resolver (#59) and denial-message-IP (#60)
    items now carry inline code breadcrumbs.

### Fixed
- **kube_symlink_test.sh updated for the multi-cluster env vars.** The
  entrypoint's kube placeholder-config regression test (the only coverage of
  the real entrypoint render, docker-gated so it runs in CI only) still set
  the pre-#57 `TJOR_KUBE_SERVER`, so after the multi-cluster change the render
  branch was skipped and the test failed (v0.18.0 CI). It now sets the
  parallel `TJOR_KUBE_CONTEXTS`/`TJOR_KUBE_SERVERS` the launcher exports. The
  shipped v0.18.0 entrypoint and images are correct — `publish-images` was
  green — so this is a test-only fix, no re-release needed.

## [0.18.0] — 2026-09-19 — Multi-cluster kube broker

One caged session can now reach several Kubernetes clusters at once, switching
between them live with `kubectl config use-context` (#57), each cluster's token
isolated to its own API origin. Also fixes a latent kube auth-scheme bug found
during the work: kube tokens are now injected as `Bearer`, the scheme the
Kubernetes API actually requires. Additive — single-cluster sessions are
unchanged.

### Added
- **Multi-cluster kube broker (#57).** One session can now reach several
  Kubernetes clusters at once: list them under `[[broker.kube_clusters]]`
  (each with its own `context`, `kube_sa`, `namespace`, `duration`, and
  optional `api_host` pin), and the agent gets a single kubeconfig with a
  context per cluster — switch between them live with `kubectl config
  use-context`, no restart. Each cluster's short-TTL token is minted against
  its own context (`kubectl create token --context …`) and injected only
  toward that cluster's exact API origin (#49), so one cluster's token never
  reaches another; every cluster API host gets the scoped SSRF-guard
  exemption and resolve-and-pin treatment (#45/#41). Provisioning is
  all-or-nothing and fail-closed: any cluster that can't validate its pin
  (#58, per entry) or mint, or a duplicate API origin, disables the whole
  broker loudly — never a session with a context that has no working token.
  All clusters are provisioned at launch; there is no mechanism to add one to
  a running session (the sealed-cage model is preserved). The deliberate
  trade-off — simultaneous live credentials for N clusters in one session —
  is a conscious, per-cluster-scoped grant, not an ambient one. The existing
  flat single-cluster config keeps working unchanged.

### Security
- **Kube tokens are now injected with the `Bearer` scheme the Kubernetes API
  requires.** The single-cluster kube broker previously injected
  `Authorization: token <sa-token>` (the GitHub scheme, inherited from the
  pat-shaped broker.json), which the API server does not accept as a bearer
  token — a latent bug never caught because the kube path has no live-cluster
  e2e. Both the single- and multi-cluster kube paths now use `Bearer`,
  carried by a `source: "kube"` broker.json handled by a per-origin credential
  map in the proxy. Found while implementing #57.

## [0.17.5] — 2026-09-19 — Review follow-ups & CI de-flake

Non-behavioral hardening after a three-lens review approved v0.17.3 and
v0.17.4 with no blockers: type-safety and DRY cleanups on the egress
guard, docstring/fail-closed-contract affirmations, added `same_server()`
hardening tests, and an accepted-risk note for the `#58` validate→mint
window. Two review findings are tracked as follow-ups (#59, #60). Also
carries the multirepo CI readiness-gate de-flake.

### Changed
- **Review follow-ups for the v0.17.3/v0.17.4 pin patches (no behavior
  change).** From a three-lens review that approved both releases with no
  blockers: the resolved-address guard's cache row is now a `NamedTuple`
  (was a 4-field positional tuple — a miscounted index on the `#41` pin
  path could have defeated the guard rather than errored); the IP-literal
  check is a shared `_is_ip_literal()` helper (was duplicated between the
  verdict path and the `server_connect` pin); `same_server()` and the
  `tjor_kube.py same` CLI now document their fail-closed exit-code contract
  and that userinfo is not part of server identity; and `same_server()`
  gains hardening tests for userinfo and IPv6 zone-id URLs (confirming a
  mismatch can only fail closed, never falsely match two different servers).
  The `#58` validate→mint window is recorded as an accepted, host-side
  residual risk. Two findings are tracked as follow-ups: #59 (bound/offload
  the pin's DNS call to prevent an in-cage self-DoS) and #60 (keep the
  resolved private IP out of the agent-facing denial message).

### Testing
- **multirepo readiness gate probes registered git trust, not buffered
  logs.** The `cda35df` gate waited for the entrypoint's `kernel-sandbox:`
  line via `docker logs | grep`, but a detached container's stdout can sit
  block-buffered: on one CI runner the grep missed for the full 60s window
  while the container was already booted and the harness running (the buffer
  flushed only once the harness produced output), failing a healthy launch
  (v0.17.3 CI). The gate now polls `git config --system --get-all
  safe.directory` over `docker exec` — live state, immune to log buffering —
  and waits until all four mount roots (writable A/B/P, read-only C) are
  registered, proving the trust loop finished rather than just started.

## [0.17.4] — 2026-09-19 — Security: DNS resolve-and-pin

Closes a DNS-rebinding TOCTOU in the egress SSRF guard: the guard validated
a hostname at request time, but mitmproxy re-resolved it at connect time, so
a low-TTL flip could reach a private address the guard never saw. Egress
connections are now pinned to a guard-validated address (#41).

### Security
- **Egress connections are pinned to the address the SSRF guard validated
  (#41).** The resolved-address guard judged a hostname at CONNECT/request
  time, then mitmproxy re-resolved it when opening the upstream socket — two
  separate resolutions, so a low-TTL record flipping between them could point
  `connect()` at a private/loopback/link-local address the guard never saw (a
  DNS-rebinding TOCTOU that turns the dual-homed proxy into a bridge into the
  internal network). The guard's 10 s verdict cache widened the window rather
  than bounding it. A new `server_connect` hook now validates (cache-aware,
  reusing the exact addresses that passed) and pins the connection to a
  validated address, so no second resolution exists to attack; a host that
  fails validation at connect time has the connection killed and the denial
  recorded. Exempt hosts (gateway, kube API), IP literals, and
  `TJOR_IP_GUARD=off` stay unpinned; TLS server-name verification still uses
  the hostname, never the pinned IP. Regression-tested against the real
  mitmproxy hook (the `tjor conformance` topology runs the guard off by
  design, so the rebinding case lives in the guard suite).

## [0.17.3] — 2026-09-19 — Security: kube_api_host validated pin

The kube broker's `kube_api_host` override becomes a validated pin: it is
checked against the active kubectl context's server before any token is
minted, so a minted token and the proxy's injection/allowlist scope can no
longer silently refer to two different clusters (#58). Also carries the
multirepo CI-flake fix.

### Security
- **`kube_api_host` is now a validated pin of the expected cluster (#58).**
  The override never selected the cluster a token was minted for — `kubectl
  create token` always targets the active kubectl context — while injection
  scoping, the egress hint, and the SSRF-guard exemption followed the
  configured string, so a stale or mistyped override silently produced a
  session whose real token and whose allowlisted host referred to two
  different clusters. At launch, an explicit override is now compared
  canonically (scheme, host, effective port) against the active context's
  server *before any token is minted*; a mismatch — or an active context
  whose server cannot be read — disables the broker loudly, naming both
  identities and the remedies. Equivalent spellings (bare `host:port` vs the
  kubeconfig's full URL) still validate as the same server. Cluster
  *selection* remains the active context; multi-cluster semantics are #57.

### Testing
- **multirepo test gates on entrypoint readiness before git assertions.**
  A container reports "running" from PID 1, but the entrypoint registers
  git trust a few seconds later; on a slow CI runner the suite's first
  git checks raced that registration and flaked (three failures at t+0s,
  identical checks passing at t+3s). The test now waits for the
  entrypoint's kernel-sandbox status line — printed after the git-trust
  step — before asserting anything git-dependent.

## [0.17.2] — 2026-09-17 — Security: canonical root representation

Two bypasses of v0.17.1's mixed-writability refusal, found by re-review,
closed with one shared control: every root is judged in one canonical
representation. Affected: non-git workspaces launched through a symlinked
cwd, and direct (non-launcher) container starts with non-canonically
spelled root lists.

### Security
- **Canonical root representation everywhere the overlap boundary is
  judged.** A re-review of v0.17.1 found two bypasses of the
  mixed-writability refusal, both spelled-differently-same-tree: (1) a
  NON-GIT workspace was recorded with logical `pwd` while extras resolve
  physically, so a symlinked working directory and its physical read-only
  descendant never textually overlapped — the launch succeeded and the
  writable workspace mount (with its tree-wide git trust) covered the
  supposedly read-only subtree through the alias; the fallback now
  canonicalizes physically (`pwd -P`), matching git's own toplevel.
  (2) The entrypoint classified read-only membership by exact match
  against the RAW `TJOR_RO_DIRS` while normalizing `TJOR_SAFE_DIRS`, so a
  trailing slash in a hand-provided environment made a read-only child
  writable — verified: it even received its own tree trust. Both env
  lists are now parsed, normalized, and strictly validated into one
  shared representation before read-only classification, overlap
  checking, git-trust registration, AND the kernel-wrap read/write
  split; malformed spellings (relative, `//`, `.`/`..` segments,
  carriage returns) and read-only roots not among the approved roots are
  refused with the boundary exit code. Edge-case behavior change: a
  non-git workspace reached through a symlinked cwd now derives its
  session id from the physical path (git workspaces are unaffected —
  `git rev-parse --show-toplevel` was already canonical).

## [0.17.1] — 2026-09-17 — Security: mixed-writability mount overlaps refused

One policy defect found by a release review of v0.16.0/v0.17.0, three
symptoms, one shared control. Affected layouts: only sessions nesting a
read-only mount inside a writable one or vice versa — such launches now
abort instead of silently weakening their read-only claims.

### Security
- **Mount roots of different writability classes may no longer overlap.**
  A release review of v0.16.0/v0.17.0 found one policy defect with three
  symptoms: the `--dir`/`--dir-ro` conflict check compared exact paths
  only, so a read-only root could nest inside a writable one (the parent's
  `<root>/*` git trust then covered repos inside the read-only child, and
  the kernel tier's additive grants could not subtract the child from the
  parent's write grant) and a writable root could nest inside a read-only
  one (the nested bind stays writable, falsifying the "read-only tree"
  claim while the launch output asserted it). The launcher now refuses
  every cross-class ancestor/descendant pair after canonicalization —
  both directions, either flag order, the workspace included — with
  component-boundary containment (`/a/b` conflicts with `/a/b/c`, never
  `/a/b-other`); the entrypoint independently refuses such a root set
  with the boundary exit code before registering any git trust
  (non-launcher starts). Same-class nesting remains allowed and is now
  spec-pinned as a non-conflict. Behavior change, stated plainly: a
  nested mixed-writability layout that previously launched (silently
  violating its read-only claim) now aborts with an error naming both
  roots.

## [0.17.0] — 2026-09-17 — Scoped prefix git trust (#53)

"Create a worktree, then work in it" now works on the first try, in every
session — trust stays scoped to the operator's writable mounts, never
blanket. Shaped by a four-lens external review of the proposal.

### Fixed
- **Repos and worktrees created mid-session are git-trusted — scoped, never
  blanket (#53).** `safe.directory` registration was launch-time and
  exact-match, so the standard "`git worktree add`, then work in it" first
  step hit a dubious-ownership refusal every session, and a mounted parent
  of many repos bought no git trust for anything inside it. Each WRITABLE
  approved root (workspace, `--dir`) is now registered as a tree —
  `<root>` + `<root>/*`, git ≥ 2.46 scoped prefix semantics, verified
  empirically in the shipped image (2.47.3) — so mid-session worktrees,
  clones, and nested pre-existing repos just work. Read-only roots
  (`--dir-ro`) deliberately keep exact-match trust: git's ownership refusal
  is what stops hostile pre-existing nested `.git/config` (fsmonitor,
  pager, filters, hooks, credential helpers) from executing in unvetted
  read-only content, and nothing new can be created under a `:ro` mount
  anyway. Degenerate roots whose entry would equal blanket trust (`/`,
  literal `*`, trailing `/*` — verified: `safe.directory = /*` trusts every
  path) abort the launch on both the launcher and entrypoint sides;
  trailing slashes are normalized. The git ≥ 2.46 floor is enforced as a
  Dockerfile build assertion (git is the base distro's apt package, not a
  pinned download). Trust tests run under
  `GIT_TEST_ASSUME_DIFFERENT_OWNER=1` with a vacuity-guard baseline —
  git's own-uid short-circuit otherwise makes such tests pass without the
  feature — plus sibling-prefix, symlink-escape, and out-of-root negative
  coverage. Shaped by a four-lens external review of the proposal;
  ADR 0008 §4 amended: "the exact writable trees, read-only paths exactly".

## [0.16.0] — 2026-09-15 — Read-only mounts + project-config neutralization (#43, #44, #46)

The hardened-profile building blocks: a mounted tree the agent structurally
cannot write, project config that structurally cannot execute, and harness
policy the agent structurally cannot override. Each enforced at the
container/mount level on every runtime, with the kernel tier in agreement.

### Added
- **`tjor run --dir-ro <path>`: true read-only repo mounts (#44).** Mounted
  `:ro` at the container level — enforced container-wide (a `docker exec`
  included), on every runtime — while staying a full repo mount otherwise:
  git-trusted (`safe.directory`) and covered by launch-time secret masking.
  When the kernel-sandbox tier is active it grants the tree `--allow-read`
  instead of `--allow-write`, so the kernel and the mount tell the same
  story. Sensitive host paths are refused exactly as for `--dir` (read-only
  still exfiltrates); the same path via both `--dir` and `--dir-ro` aborts
  rather than silently picking a writability. The launcher's
  `TJOR_SAFE_DIRS`/`TJOR_RO_DIRS` env pair now documents the
  operator-approved roots and their writability class as a stable contract
  (groundwork for #53's dynamic git trust).
- **`[landlock] mask_dirs`: structural directory masking (#43).** Extends
  the `/dev/null`-style launch-time masking to directories: each entry — an
  absolute path, or a bare name (e.g. `".opencode"`) discovered recursively
  in every mounted repo — is bind-mounted over with a read-only EMPTY
  directory, so it is structurally empty in-cage on every runtime. This
  closes the project-config execution surface (opencode auto-loads
  `.opencode/plugins`/`.opencode/tools` with full command execution outside
  its permission matcher) by containment, not detection. Applied
  independently of `mask_dotenv` (the #48 lesson, spec-pinned); globs and
  relative paths abort the launch; announcements are escape-sanitized (the
  dir names come from untrusted repos). Documented residual: a directory
  created mid-session is not masked.
- **Managed opencode config tier for profiles (#46).** A profile may stage
  `managed/opencode.json`; the entrypoint deploys it root-owned and
  agent-immutable to `/etc/opencode/opencode.json` (opencode's
  managed-settings path — loads after, and cannot be overridden by, user or
  project config) before the privilege drop. Invalid JSON refuses the launch
  on both sides (launcher preflight and entrypoint, boundary exit code 90);
  with no staged file, a stale managed file is removed. The issue's proposed
  `OPENCODE_CONFIG_DIR` export was verified against the shipped opencode
  1.18.28 bundle and deliberately dropped: it *replaces* the global config
  dir and would displace the baseline instruction cargo and autoupdate pin.

### Testing
- **End-to-end hostile-filename regression test for the dotenv-mask
  escape-injection fix.** The v0.15.0 fix was covered only by the sanitizer's
  own unit tests; the re-review flagged the missing wiring-level check. The
  landlock integration test now plants a `.env.*` file whose NAME carries a
  raw ANSI escape and asserts the real `tjor run` launch announces it
  sanitized (`^[`) with no raw ESC byte on any mask line.
- **Regression test for malformed bracketed-IPv6 broker entries with an
  oversized port.** `[host]:PORT` with a >5-digit suffix (previously verified
  correct only by manual regex tracing) is now locked in: the entry stays
  verbatim — never unbracketed into an any-port glob — covers no request
  host on any port, and leaves well-formed neighbor entries unaffected.

## [0.15.0] — 2026-09-15 — Security-review follow-ups + automated releases

External security review of v0.11.0–v0.14.0 (three specialist passes: security,
shell, Python). Every changelog security claim was verified against the code —
8 of 9 held exactly as stated; the findings below are the gaps it surfaced,
each verified before fixing.

### Security
- **Dotenv-mask status lines are escape-injection safe.** The `+ dotenv mask
  <file>` lines echoed a filename discovered in the mounted (untrusted) repo
  without sanitizing — a repo-planted filename carrying ANSI/OSC escapes or
  bidi overrides could spoof or hide the very line the operator relies on to
  confirm a secret WAS masked. All three mask/deny_paths status lines now
  route through the existing `tjor_safeprint` filter (new launcher `safeprint()`
  helper), the same defense the trust review and denial log already use.
- **Unknown config keys under `[landlock]`/`[broker]` abort the launch (#39
  escalation).** Validation stays warn-only in general, but a typo'd key
  inside a security-enforcing table means the operator believes a stricter
  boundary setting is applied when it is not — and in unattended/CI use nobody
  reads the warning. `tjor_cfg check` now exits nonzero (naming the key and
  source file) and the launcher refuses to start. A misspelled table NAME
  itself still only warns: it cannot claim to configure these tables.

### Fixed
- **A truncated `--session` qualified id is refused, not defaulted (#52
  class).** `<base>-` (trailing dash, empty name — a copy-paste truncation)
  stripped to an empty short name and silently resolved to the DEFAULT
  session, so a teardown aimed at a named session could hit the wrong one. It
  now dies with a "truncated fully-qualified id?" error.
- **Foreign-id disambiguation fails closed when Docker is unreachable (#52
  class).** The "does this qualified-looking id exist?" probe could not tell
  "no such session" from "daemon unreachable", misclassifying a real foreign
  session id as a fresh short name. The state dir is now checked first (no
  daemon needed); if Docker itself must be asked and is unreachable, tjor
  refuses with a clear error instead of guessing.
- **`api_origin()` default port is scheme-aware (#49 follow-up).** The kube
  broker's injection origin hardcoded the https default 443, so an `http://`
  (non-TLS) on-prem API server was scoped to a port it never uses — the token
  silently never injected. Explicit port, else 443 for https / 80 for http.
- **A portless bracketed IPv6 broker entry can actually match (#49
  follow-up).** `[2001:db8::1]` (brackets, no port scope) was kept verbatim,
  and request hosts are never bracketed — the entry could never cover
  anything. It is now unbracketed to the bare literal, covering any port like
  every other portless entry.

### Added
- **GitHub Releases are created automatically on each release tag.** The
  publish-images workflow gains a `release` job: notes extracted from the
  tag's CHANGELOG section, title from its heading, idempotent, independent of
  the image builds (a failed image build never hides the release notes).
  Tagging is now the only manual release step — releases had quietly stopped
  at v0.10.1 because `gh release create` was manual.

### Tests
- **The landlock test's "masking is independent of the kernel tier" block was
  a no-op** — an `if` around a bare `:` behind a comment claiming an
  assertion. Replaced with a real `mode = "off"` launch asserting the dotenv
  mask still applies (and the missing `mo`-session cleanup added to the trap).
- Lifecycle regression checks for the truncated-id refusal (message + nonzero
  exit); unit tests for the scheme-aware origin port, IPv6 unbracketing, and
  the `[landlock]`/`[broker]` hard-fail (236 → 239 passing).

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
