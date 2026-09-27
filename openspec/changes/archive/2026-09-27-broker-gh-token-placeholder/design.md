# Design

## Context

See proposal.md — Why, and the delta spec. Grounding (observed at v0.20.0):

- `images/agent/entrypoint.sh` step 3 decides `broker_covers_github` with an inline Python snippet over `tjor_identity.parse_broker_hosts` / `broker_covers` (the proxy's own matcher, image cargo), for `github.com:443` or `gist.github.com:443`, and wires the placeholder git helper (`username=x-access-token`, `password=tjor-broker-placeholder`) or the `gh auth git-credential` fallback. `TJOR_BROKER_ENABLED` and `TJOR_BROKER_HOSTS` (hostnames only) reach the agent container via `compose.yaml`.
- The harness is started with `exec gosu agent env HOME=… USER=agent …`, which carries the entrypoint's exported environment through (both the kernel-wrapped and the plain path). An `export` in the entrypoint is therefore visible to `gh`.
- `proxy/addon.py` `_apply_broker` deletes any `authorization` header toward a covered host and sets the real one (`token <t>` for pat/github-app), or strips it fail-closed when no credential is available. It is scheme-agnostic: `Basic …` from git and `token …` from `gh` are treated alike. The unit test only exercises `Basic`.
- Default `[broker] hosts` in `config/tjor.toml` is `["github.com", "*.github.com", "codeload.github.com"]`, so `api.github.com:443` is covered by default; `tests/integration/broker_test.sh` runs a live pat-source session (stub token) and direct-entrypoint coverage cases (`helper_for`).
- `gh` semantics (upstream, to be confirmed live in 5.3): `GH_TOKEN` is preferred over `hosts.yml` for `github.com`; `gh auth login` exits with an error while `GH_TOKEN` is set; `gh auth status` names the variable as the token source.
- `tjor_broker.revoke` is a no-op for the pat source (nothing to revoke server-side), so a live end-to-end with a real host token in the proxy is safe.

## Goals / Non-Goals

**Goals:**
- `gh` works in a GitHub-covering broker session without any in-cage login, through the same placeholder-then-substitute path git uses.
- Nothing new proxy-side; coverage decided by the one shared matcher; scoped exactly like the git helper.
- Narrow the ADR 0007 "agent can mint a real token" limitation where the broker covers the API host, stated honestly.

**Non-Goals:**
- Wrapping `gh`, blocking the device-flow endpoints, or preventing `unset GH_TOKEN` (the environment is the agent's own).
- Tokens for other CLIs (#75) or a `GH_HOST`/GitHub Enterprise story.

## Decisions

1. **Coverage for `gh` is decided separately from git, on `api.github.com:443`.** The existing snippet grows a second verdict (exit code 2 = API covered too, 1 = git only, 0 = neither, or simply two probes). A host list of `["github.com"]` covers git but not `gh`; that is correct scoping, not a bug: the proxy would never inject toward `api.github.com` for that list, so exporting a placeholder would only make `gh` send an unsubstitutable token. Docs say the default glob is what covers both. *Alternative rejected:* treating git coverage as `gh` coverage — would break `gh` exactly in the configurations where the proxy cannot help.
2. **`GH_TOKEN`, not `GITHUB_TOKEN`, with the same placeholder string.** `gh` reads `GH_TOKEN` first; `GITHUB_TOKEN` is also honored by many *other* tools (actions toolkit, octokit), which would then send an unsubstitutable placeholder to hosts the broker does not cover — `gh`-specific is the narrowest correct choice. The value is the existing `tjor-broker-placeholder`, so operators and the secret scan recognize one placeholder. *Alternative rejected:* writing a `hosts.yml` into the session home — a file the agent can edit and that persists across launches; an env var set at every start is the accurate contract.
3. **Export in the entrypoint, in the same block as the git helper.** No launcher or compose change: the agent container already receives `TJOR_BROKER_HOSTS`, and the final `exec … env …` propagates exports. **Found end-to-end:** the kernel-sandbox wrap (cplt, `--inherit-env`) runs an env sanitizer that strips credential-shaped names — the entrypoint already passes the lowercase proxy vars explicitly for that reason — so under the wrap the harness saw `GH_TOKEN` unset while PID 1 (cplt) had it. `--pass-env GH_TOKEN` did not help either (cplt drops the name regardless), so the placeholder is set *inside* the sandbox: the wrapped exec becomes `cplt … exec -- env GH_TOKEN=<placeholder> <harness>`, and `env` runs as the sandboxed child, past cplt's filter. Nothing to protect from the sandbox — it is the placeholder. The unwrapped paths inherit the export directly. Consequence for tests: neither PID 1's environ nor a `docker exec` shell shows what `gh` inherits; the integration test has the harness dump its own environment and asserts on that. `GH_TOKEN` is never *unset* by the entrypoint when not covered, because nothing sets it (compose passes an explicit env list); documented rather than guarded.
4. **Precedence and the login refusal are documented behaviors of `gh`, verified live, not enforced by tjor.** They are stated in the spec because operators rely on them (an agent-minted token stops being used; the easy mint path closes), and the ADR 0007 amendment says plainly that an agent can unset the variable — narrowed, not closed.
5. **Tests at two levels.** Unit: `_apply_broker` with `Authorization: token tjor-broker-placeholder` toward `api.github.com:443` → replaced; toward a non-destination → untouched. Integration (`broker_test.sh`, the `broker` CI job on a live engine): in the running pat-source session, `docker exec … env` shows `GH_TOKEN=tjor-broker-placeholder` and the secret scan still passes; direct-entrypoint runs (the `helper_for` pattern) print `GH_TOKEN` for covered / kube-only / glob-less host lists. The `gh auth login` refusal and `hosts.yml` precedence are verified in the manual end-to-end with a real token in the proxy (pat source, host `gh auth token`), recorded in tasks.md, because they need a reachable GitHub.

6. **Found end-to-end, fixed here: the proxy keys host-scoped decisions on the verified SNI, not `flow.request.host`.** After `server_connect` pins `data.server.address = (ip, port)`, mitmproxy 12 reports that IP in `flow.request.host` for every request inside the tunnel, while `pretty_host` (Host/`:authority`) and `server_conn.sni` keep the hostname. The verdict already used `pretty_url`, so requests were *allowed* — and then `_apply_broker`, `_apply_identity`, `_apply_gateway`, `_scan_request_body` and `_log_denial` all compared the IP. `_logical_host(flow)` returns the SNI when present, else `pretty_host`, else `host`. *Why SNI and not the Host header:* mitmproxy verifies the upstream certificate against the SNI (`ssl_insecure` is off), so a client that CONNECTs to an allowed host A and sends `Host: api.github.com` inside the tunnel cannot attract the credential toward A — the regression test `test_apply_broker_sni_governs_not_a_forged_host_header` pins that. *Why CI never saw it:* the conformance broker probes run with the IP guard off (internal echo host), so no pin happened there. A follow-up conformance probe with the guard on needs a publicly resolvable echo target; noted, not done here.
7. **Found end-to-end, fixed here: the sandboxed child's environment is corrected inside the sandbox.** cplt sets `GIT_CONFIG_NOSYSTEM=1` for the child, which makes git skip `/etc/gitconfig` — the only place tjor wires git. `env -u GIT_CONFIG_NOSYSTEM` runs as the sandboxed child (past cplt's filter), and the same `env` sets `GH_TOKEN` (cplt drops that name even under `--inherit-env` and even with `--pass-env GH_TOKEN`; the first attempt with `--pass-env` proved it). Unwrapped paths inherit the entrypoint's exports directly.
8. **Found end-to-end, fixed here: `--allow-read /etc/gitconfig` on the wrap.** With the override gone, git still reported "unable to access '/etc/gitconfig': Permission denied": cplt's Landlock policy does not grant it. The narrowest grant that works (tested against `--allow-read /etc`) is the single file. It is root-owned tjor cargo written at every start, not host state.

9. **Found end-to-end, fixed here: the credential is re-issued in the client's scheme.** With everything above in place, `gh api user` returned the account and `git ls-remote` still got "invalid credentials": GitHub's git endpoint rejects `token …`/`Bearer …` and accepts only Basic `x-access-token:<token>` (verified with curl from the host: 401/401/200; the API: 200 for all three). `_reissue_authorization(incoming, auth)` keeps the scheme the client sent — Basic → Basic with `x-access-token`, Bearer → Bearer, anything else → the canonical `token` — so each client's protocol expectation is met by the endpoint it talks to. `broker_authorization()` stays the testable seam returning `token <t>`. *Alternative rejected:* choosing the scheme by host (`github.com` → Basic, `api.github.com` → token): a lookup table that is wrong for GitHub Enterprise hostnames and for the many API clients that send Basic; the client already knows what its endpoint wants.

## Risks / Trade-offs

- [Behavior change: an in-cage `gh auth login` to a different account is superseded by the brokered identity] → intended and called out in CHANGELOG; the broker's identity is the session's identity by design (ADR 0005/0007).
- [`gh auth status` may report a failure for a GitHub App installation token] → `GET /user` is not accessible to installation tokens; repo-scoped commands (`gh pr`, `gh api repos/…`) work. Documented in README as source-dependent; not a tjor bug.
- [A host list that covers `github.com` but not `api.github.com`] → `gh` stays unauthenticated by design; the config comment and README point at the default glob.
- [The image must be rebuilt for the entrypoint change] → per release, as for every entrypoint change; local verification bind-mounts the entrypoint into the existing image.
- [The pinned-host fix widens what a request's `Host` header can no longer do] → nothing: decisions now key on the SNI the upstream cert is verified against, which is strictly harder to forge than the Host header the verdict path already trusted.
- [Tree trust under the kernel tier was inert and nobody noticed] → the uid alignment made every mounted repo same-owner, so git never asked; the `--allow-read` restores the wiring for the cases where it matters (a `--dir` owned by another uid, nested repos). Recorded in CHANGELOG as a Security fix, not a footnote.

## Migration Plan

Additive: one export in the entrypoint, tests, docs. Patch release. Rollback: revert; sessions fall back to today's `gh` fallback behavior.

## Open Questions

None that change the specs, approach, or tasks.
