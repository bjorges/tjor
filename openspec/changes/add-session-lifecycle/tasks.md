# Tasks: add-session-lifecycle

## 1. Discovery

- [ ] 1.1 Add session labels to the agent (and conformance) services in compose, fed from launcher env (`tjor.session`, `tjor.workspace`, `tjor.harness`, `tjor.task`, `tjor.launched-at`, `tjor.role=agent`) — verified by docker inspect assertions in the integration script
- [ ] 1.2 Implement `tjor ls`: enumerate by label, show id/state/agents/workspace/task/age, re-verify each running session's internal-only network and mark DEGRADED loudly — verified by integration script incl. a sabotaged-network degradation case

## 2. Reattach

- [ ] 2.1 Implement `tjor attach [session]`: resolve candidates from labels, fzf or select picker, `docker attach` with detach-hint — verified by integration script attaching and detaching non-interactively

## 3. Multiplexing

- [ ] 3.1 `tjor run --session <name>` (validated name folded into session id derivation); everything downstream keys off the id unchanged — verified by integration script running two named sessions concurrently in one repo and asserting distinct networks, state roots, and TJOR_SESSION_ID values

## 4. Garbage collection

- [ ] 4.1 Implement `tjor gc [--age <hours>] [--dry-run]`: reap exited label-selected agent containers; tear down topologies (containers/networks/volumes, label-selected only) idle past the threshold; never touch state dirs — verified by integration script: dry-run lists, gc reaps, state dir survives, session resumes
- [ ] 4.2 Leave a documented hook point where D2 will revoke session credentials at teardown — verified by comment + design reference in the gc implementation

## 5. Tiered reset

- [ ] 5.1 Implement `tjor reset {cache|sessions|creds|all} [--dry-run]` with tier→path mapping per design; no default tier — verified by integration script exercising every tier against planted canary files and asserting survivors
- [ ] 5.2 Symlink-escape check: planted symlink inside a tier path must not cause deletion outside the session root — verified by integration script canary outside the root surviving a reset

## 6. Integration & CI

- [ ] 6.1 `tests/integration/lifecycle_test.sh` covering all scenarios above, runnable locally and in CI — verified by green run on Colima
- [ ] 6.2 CI job running the lifecycle integration script on the Linux engine — verified by green pipeline
- [ ] 6.3 Docs: README session section gains ls/attach/--session/gc/reset — verified against implemented behavior
