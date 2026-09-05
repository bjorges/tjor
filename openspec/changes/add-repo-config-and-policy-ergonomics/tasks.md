# Tasks: add-repo-config-and-policy-ergonomics

## 1. Repo config + trust

- [x] 1.1 `tjor_cfg`: add the repo `.tjor/config.toml` layer (nearest via git toplevel) to the merge, gated by a trust check (approved content hash in `~/.config/tjor/trusted.toml`); unapproved repo config excluded, warned — verified by config unit tests (trusted layers, untrusted excluded, changed re-untrusted)
- [x] 1.2 `policy_file`: prefer an approved repo `.tjor/policy.toml` over the packaged default (after the user policy) — verified by a resolution test
- [x] 1.3 `tjor trust [--show]` and `tjor init` — verified by an integration case: init scaffolds, trust approves, a subsequent launch honors; edit → untrusted again

## 2. Policy ergonomics

- [x] 2.1 `tjor policy <url> --explain` (surface the engine's rule + pattern) — verified by unit/CLI test
- [x] 2.2 `tjor policy add <host>` appends to the active policy allow list (repo-if-trusted else user) — verified: add then the host is allowed
- [x] 2.3 Session denial log: proxy appends denied decisions (host, rule, ts) to a session-dir log; `tjor denials [session]` reads it — verified by a conformance/integration case that a denied request appears in the log

## 3. README & docs

- [x] 3.1 README pass: sharpen the quickstart; add a config-layering section (defaults → user → trusted repo → flag), the deny→`denials`→`policy add` loop, `tjor init`/`trust`, and a troubleshooting list — verified against implemented behavior and the doc-consistency lint

## 4. Tests

- [x] 4.1 Unit tests for the trust store + repo-config layering + `--explain`/`add`; an integration test for `init`/`trust`/`denials` end to end + CI — verified green locally and on Linux
