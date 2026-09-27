# Tasks

## 1. Entrypoint: the gh placeholder

- [x] 1.1 In `images/agent/entrypoint.sh` step 3, extend the coverage snippet so it also decides whether `api.github.com:443` is covered (shared matcher, port-aware) and set `broker_covers_gh_api=1` when it is; when set, `export GH_TOKEN=tjor-broker-placeholder` with a comment stating the contract (placeholder only; proxy substitutes; unset when not covered; precedence over hosts.yml; `gh auth login` refused while set — narrowed ADR 0007 limitation). Verify: `shellcheck --severity=warning images/agent/entrypoint.sh` clean; direct runs of the bind-mounted entrypoint in the local image print the placeholder for `github.com,*.github.com`, nothing for `kubeapi.example.com`, nothing for `github.com` alone (task 3.2 automates these)
- [x] 1.2 `config/tjor.toml`: a comment on `[broker] hosts` that `*.github.com` is what covers `api.github.com` (the `gh` CLI) and `codeload.github.com` (archive downloads). Verify: comment present; `python3 python/tjor_cfg.py check` passes

## 2. Proxy unit test

- [x] 2.1 `python/tests/test_addon_guards.py`: add `test_apply_broker_replaces_gh_token_scheme` — a flow toward `api.github.com:443` with `authorization: token tjor-broker-placeholder` is replaced with the real `token tok-123`; and a flow toward a non-destination host keeps its `token …` header untouched. Verify: `uvx --python 3.14 --with 'mitmproxy==12.1.2' pytest python/tests/test_addon_guards.py -q` passes

## 3. Broker integration test (live engine, `broker` CI job)

- [x] 3.1 `tests/integration/broker_test.sh`: in the running covered session assert `docker exec … env` has `GH_TOKEN=tjor-broker-placeholder` and that the existing secret-scan checks still pass (the placeholder is not the secret). Verify: test file updated; runs green locally on colima (needs the rebuilt image, task 5.2)
- [x] 3.2 Add direct-entrypoint checks with a `gh_token_for()` helper (mirrors `helper_for`): `github.com,*.github.com` → placeholder; `kubeapi.example.com` → unset; `github.com` alone → unset while `helper_for 'github.com' github.com` still shows the git placeholder (independent decisions). Verify: `check` lines pass locally

## 4. Docs

- [x] 4.1 README quickstart: replace "authenticate once inside the session: `gh auth login`" with: in a GitHub-covering broker session `git` and `gh` are already authenticated through the proxy (no login, no token in the cage; `gh auth status` may show a failure for an App installation token because `/user` is not accessible to it, while repo commands work); `gh auth login` remains the path for broker-less sessions. Verify: `tests/doc_consistency.sh` passes; text reads correctly
- [x] 4.2 ADR 0007: amend the first known limitation — with a broker covering `api.github.com`, `gh` holds a placeholder via `GH_TOKEN`, `gh auth login` refuses while it is set, so the easy mint path is closed in those sessions; the agent can still unset the variable, so the limitation is narrowed, not closed. Verify: paragraph present
- [x] 4.3 CHANGELOG `[Unreleased]` — Fixed: `gh` works in broker sessions (#65), the coverage rule, precedence, the login refusal, the behavior change for an in-cage login to another account, the App-token `/user` caveat. Verify: entry present, references #65

## 6. Regressions found end-to-end (added scope, fixed here)

- [x] 6.1 `proxy/addon.py`: add `_logical_host(flow)` (SNI → `pretty_host` → `host`) and key `_apply_broker`, `_apply_identity`, `_apply_gateway`, `_scan_request_body`, `_pods_log_pod` and the request hook's verdict/denial on it (design D6). Verify: `test_apply_broker_matches_logical_host_after_pin` and `test_apply_broker_sni_governs_not_a_forged_host_header` pass; full suite green
- [x] 6.2 `images/agent/entrypoint.sh`: under the wrap, exec the harness through `env -u GIT_CONFIG_NOSYSTEM [GH_TOKEN=…]` inside the sandbox, and grant `--allow-read /etc/gitconfig` (design D7/D8). Verify: `broker_test.sh` 2b/2c — harness env has the placeholder and no `GIT_CONFIG_NOSYSTEM`; git in the harness resolves the placeholder helper from `/etc/gitconfig`
- [x] 6.3 `proxy/addon.py`: `_reissue_authorization()` — re-issue the broker credential in the incoming header's scheme (Basic `x-access-token:<t>` / Bearer / `token`), used by `_apply_broker` (design D9). Verify: `test_apply_broker_replaces_placeholder` now expects Basic; `..._keeps_bearer_scheme` and `..._no_incoming_header_defaults_to_token_scheme` pass; end-to-end `git ls-remote` on a private repo prints a sha
- [x] 6.4 CHANGELOG: a Security entry for the four regressions (what was inert since when, why CI missed it, the fix, the follow-up conformance probe). Verify: entry present

## 7. Verification

- [x] 7.1 Local gate: `uvx … pytest python/tests -q`, `tests/doc_consistency.sh`, `shellcheck --severity=warning images/agent/entrypoint.sh tests/integration/broker_test.sh`, `npx --yes @fission-ai/openspec@latest validate broker-gh-token-placeholder`. Verify: all green
- [x] 7.2 Rebuild the local agent image (`./bin/tjor build`) so the live tests run the new entrypoint; run `bash tests/integration/broker_test.sh` on the local engine. Verify: broker test green
- [x] 7.3 Manual end-to-end with a real token (**observed 2026-09-27 on colima, macOS, from inside the wrapped harness**: `gh auth status` → "Logged in to github.com account bjorges (GH_TOKEN)"; `gh api user` → the host account; with a bogus `hosts.yml` seeded, `GH_TOKEN` stayed the active account and `gh api user` still succeeded; `gh auth login` → "The value of the GH_TOKEN environment variable is being used for authentication. To have GitHub CLI store credentials instead, first clear the value from the environment."; `git ls-remote` on a private repository printed its HEAD sha; the real token appeared nowhere in the run output or the session home; `tjor down` cleaned up) (pat source, `pat_env` fed from the host's `gh auth token`; the pat source revokes nothing at teardown): in the session `gh auth status` reports the token from `GH_TOKEN`; `gh api user` returns the host account's login; with a pre-seeded `~/.config/gh/hosts.yml` holding a bogus token `gh` still uses `GH_TOKEN`; `gh auth login` refuses naming `GH_TOKEN` (record the exact message); the real token appears nowhere in the agent env, filesystem, or process cmdlines; `tjor down` cleans up. Record the observations in tasks.md. Verify: observations recorded
