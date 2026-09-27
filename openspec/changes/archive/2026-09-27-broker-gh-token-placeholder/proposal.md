# Proposal

## Why

With a GitHub-covering broker, the cage wires a placeholder **git** credential helper so the proxy can swap in the real short-TTL token, and it overrides the `gh auth git-credential` helper so no real token is ever sourced in-cage. The `gh` CLI itself gets nothing: no `GH_TOKEN`, no `hosts.yml`. So `gh api`, `gh pr list/create/view`, `gh issue …` fail with "not logged in" in exactly the sessions where GitHub access is brokered (#65). The only in-cage workaround is `gh auth login`, which mints a real, long-lived token into the session home — the ADR 0007 limitation the broker exists to avoid.

`gh` authenticates with `Authorization: token <t>` toward `api.github.com` (REST and GraphQL), and the proxy already replaces the whole `Authorization` header toward broker destination hosts. The default broker host list (`github.com`, `*.github.com`, `codeload.github.com`) already covers `api.github.com`. The missing piece is a placeholder in `gh`'s hands.

## What Changes

- **A `GH_TOKEN` placeholder when the broker covers `api.github.com:443`.** The entrypoint decides coverage with the shared matcher (`tjor_identity.broker_covers`, the same snippet that decides the git helper today) and, when covered, exports `GH_TOKEN=tjor-broker-placeholder` into the agent environment. `gh` then sends `Authorization: token tjor-broker-placeholder`, which the proxy overwrites with the real credential — nothing proxy-side changes.
- **Not covered means unchanged.** A kube-only broker, a broker whose hosts name `github.com` without a glob, or no broker at all leaves `GH_TOKEN` unset; `gh` keeps its ambient behavior. This follows the existing "placeholder wiring is scoped to brokered destinations" requirement, which is amended to cover `gh`.
- **Precedence, stated.** `GH_TOKEN` takes precedence over a stored `~/.config/gh/hosts.yml`, so an agent-minted token from an earlier session stops being used in a broker session; and `gh auth login` refuses to run while `GH_TOKEN` is set, which removes the easy in-cage path to minting a real token. Honest scope: the agent can `unset GH_TOKEN` and log in — the ADR 0007 limitation is narrowed, not closed, and the ADR says so.
- **Coverage becomes visible.** A proxy unit test proves a `token <placeholder>` header (gh's scheme) is replaced like git's `Basic`; the broker integration test proves the env placeholder is present in a covered session and absent for kube-only and glob-less hosts, and that the secret scan stays clean.
- **Three pre-existing regressions, found by the real-token end-to-end and fixed here** (added scope, called out; each is what stood between "placeholder exported" and "gh works"):
  1. **The proxy keyed every host-scoped decision on the pinned IP.** Since the #41 resolve-and-pin (v0.17.4), mitmproxy reports the pinned upstream IP in `flow.request.host` for tunneled requests, so the broker matcher (and identity injection, the gateway key, the #62 scan, the denial log) never matched a DNS-resolved destination: git's and gh's placeholders were forwarded unsubstituted and GitHub answered 401. Unit tests model flows with a hostname, and the conformance broker probes run with the IP guard off, so nothing caught it. Fixed by keying on the client's SNI — the hostname mitmproxy verifies the upstream certificate against, so a forged `Host` header cannot steer a credential elsewhere — with regression tests for both properties.
  2. **cplt sets `GIT_CONFIG_NOSYSTEM=1` for the sandboxed harness**, so under the kernel-sandbox tier git ignored `/etc/gitconfig`, where tjor wires the placeholder helper, the gh fallback, the SSH→HTTPS rewrites and `safe.directory` tree trust. The uid alignment masked the trust half. Fixed by unsetting it for the child inside the sandbox.
  3. **cplt's Landlock policy denies reading `/etc/gitconfig`** even with the override gone. Fixed with a single `--allow-read /etc/gitconfig` grant.
  4. **The proxy injected `token <t>` toward every covered host, but GitHub's git smart-HTTP endpoint accepts only Basic** (`x-access-token:<token>`; `token …` and `Bearer …` get 401 there, while `api.github.com` accepts all three). So brokered *git* auth never worked against real GitHub — ADR 0007's "GitHub accepts … as `token <t>`" is true for the API only. Fixed by re-issuing the credential in the scheme the client used: git's Basic stays Basic, gh's `token` stays `token`, Bearer stays Bearer.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: "Placeholder wiring is scoped to brokered destinations" — the requirement now covers the `gh` CLI: a `GH_TOKEN` placeholder is exported when the broker covers `api.github.com:443` (shared matcher), left unset otherwise; precedence over a stored `hosts.yml`; `gh auth login` refused while the placeholder is set. Existing scenarios kept; five added.

## Impact

- **Code**: `images/agent/entrypoint.sh` — extend the coverage snippet to also decide `api.github.com:443` and export `GH_TOKEN` when covered; under the kernel-sandbox wrap the child environment is corrected inside the sandbox (`env -u GIT_CONFIG_NOSYSTEM GH_TOKEN=…`) and `/etc/gitconfig` is granted read-only. `proxy/addon.py` — `_logical_host()` (SNI-first) used by every host-scoped decision. `config/tjor.toml` — a comment on `[broker] hosts` that `*.github.com` is what covers `api.github.com` for `gh`.
- **Tests**: `python/tests/test_addon_guards.py` — `_apply_broker` replaces a `token tjor-broker-placeholder` header toward a covered host. `tests/integration/broker_test.sh` (`broker` CI job, live engine) — `GH_TOKEN` is the placeholder in the covered live session and never the secret; direct-entrypoint runs: covered → placeholder, kube-only → unset, `github.com` without a glob → unset while git is still wired.
- **Docs**: README quickstart (a GitHub-covering broker means `gh` and `git` are already authenticated; `gh auth login` is for broker-less sessions), ADR 0007 amendment (the `gh` path; the limitation narrowed, not closed), CHANGELOG `[Unreleased]` (Fixed + Security; behavior change called out: a deliberately different in-cage `gh` login is superseded by the brokered identity).
- **Behavior change**: in a broker session covering the API host, `gh` uses the brokered identity, including where someone had logged `gh` into another account inside the cage. Not breaking. Patch release — but the three regression fixes restore broker git auth, identity injection, the gateway key path and tree trust for wrapped sessions, which had been inert since v0.17.4 / the kernel tier: a Security entry in the CHANGELOG, not a footnote.
- **Out of scope**: wrapping `gh` or blocking the OAuth device-flow endpoints (ADR 0007 follow-up), other CLIs' tokens (#75).
