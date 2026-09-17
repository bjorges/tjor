# Tasks — refuse mixed-writability mount overlaps

## 1. Implementation

- [x] 1.1 `bin/tjor cmd_run`: after resolving both extras lists, refuse
      any cross-class ancestor/descendant pair (read-only vs workspace or
      `--dir`), both directions, component-boundary containment, error
      naming both roots. Verify: multirepo_test.sh refusal checks;
      shellcheck clean at warning severity, zero new findings.
- [x] 1.2 `images/agent/entrypoint.sh`: collect the normalized root list
      first, validate cross-class containment against `TJOR_RO_DIRS`
      before registering any trust, exit 90 on a hit. Verify: synthetic
      docker-run checks in multirepo_test.sh; shellcheck clean.

## 2. Tests (multirepo_test.sh)

- [x] 2.1 Launcher refusals: `--dir P --dir-ro P/n1` aborts (both flag
      orders); `--dir-ro C --dir C/sub` aborts; `--dir-ro <workspace
      subdir>` aborts; each error names the writability conflict.
      Verify: all pass.
- [x] 2.2 Sibling non-conflict: `--dir B --dir-ro B-other` launches
      (component boundary, not string prefix). Verify: passes.
- [x] 2.3 Entrypoint synthetics: RO child under writable parent in
      `TJOR_SAFE_DIRS`/`TJOR_RO_DIRS` → exit 90; writable child under RO
      parent → exit 90; sibling pair → registers normally (starred rw,
      exact ro). Verify: all pass.

## 3. Docs + sweep

- [x] 3.1 README (one sentence in the multi-repo section) + CHANGELOG
      `[Unreleased]` Security/Fixed entry covering all three symptoms and
      the behavior change. Verify: doc_consistency.sh passes; claims
      match behavior.
- [x] 3.2 Full sweep: python suite, shellcheck, doc-consistency, and
      multirepo + landlock + profile integration tests green on the live
      engine (image rebuilt). Verify: all pass locally.
