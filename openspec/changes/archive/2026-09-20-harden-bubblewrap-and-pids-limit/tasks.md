# Tasks

## 1. Ship bubblewrap in the agent image

- [x] 1.1 Add `bubblewrap` to the `apt-get install -y --no-install-recommends` package list in `images/agent/Dockerfile` (keep the list sorted/grouped as it is; no sha256 gate — apt repo signing covers it, same tier as the other apt packages). Add a short comment that cplt auto-detects it to enable UNIX-socket `connect(2)` enforcement (#10)

## 2. Bound the agent's process count

- [x] 2.1 Add `agent_pids = 4096` to the `[limits]` block in `config/tjor.toml`, with a comment (DoS/fork-bomb ceiling; generous so real multi-process work is unaffected; tunable)
- [x] 2.2 In `bin/tjor` `export_static_env`, add `TJOR_AGENT_PIDS="$(cfg limits.agent_pids --default 4096)"` beside the `*_MEM` knobs and add it to the `export` line
- [x] 2.3 In `compose.yaml`, add `pids_limit: ${TJOR_AGENT_PIDS:-4096}` to the agent service, next to its `mem_limit`

## 3. Assertions

- [x] 3.1 In `.github/workflows/ci.yml`, extend the agent-image "image contract" step to assert `command -v bwrap` in the built image (fails the build if bubblewrap is missing) — covers all three harness images via the existing matrix
- [x] 3.2 In `tests/doc_consistency.sh`, add a grep-shaped invariant: the agent service in `compose.yaml` carries a `pids_limit` (so the process-count guard can't be silently dropped). Fail with a clear message

## 4. Verification

- [x] 4.1 Local gate (docker-free parts): `shellcheck bin/tjor tests/doc_consistency.sh`, `tests/doc_consistency.sh`, `python -m pytest python/tests -q` (sanity), and confirm `TJOR_AGENT_PIDS` resolves via `cfg` (e.g. `bin/tjor` sources cleanly and `cfg limits.agent_pids` returns 4096). `openspec validate harden-bubblewrap-and-pids-limit`
- [x] 4.2 CHANGELOG entry under `[Unreleased]` (Security/Changed): bubblewrap in the agent image (cplt UNIX-socket enforcement + warning silenced) and the agent `pids_limit`, referencing #10; note #10 stays open
- [x] 4.3 Note for the release watcher: the behavioral gate is CI — the agent-image contract (`bwrap` present) and the live-session jobs (lifecycle, PTY, multi-repo) booting and working with bubblewrap active and under the pid cap. If a heavy job trips the cap, raise `limits.agent_pids` and re-release
