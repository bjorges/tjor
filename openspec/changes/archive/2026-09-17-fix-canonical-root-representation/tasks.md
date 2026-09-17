# Tasks — canonical root representation

## 1. Implementation

- [x] 1.1 `bin/tjor`: non-git workspace fallback `pwd` → `pwd -P`
      (resolve_session), and the qualified-id fallback likewise. Verify:
      symlinked-workspace test aborts; shellcheck clean.
- [x] 1.2 `images/agent/entrypoint.sh`: `_norm_root` helper; normalize +
      validate BOTH lists before classification; RO ⊆ SAFE required;
      cross-class ancestry, git-trust registration, and the step-6 wrap
      split all consume the normalized lists. Verify: reviewer's repro
      exits 90; shellcheck clean.

## 2. Tests (multirepo_test.sh)

- [x] 2.1 Symlinked non-git workspace + physical-path `--dir-ro`
      descendant → aborts with the writability-conflict error before
      Docker. Verify: passes.
- [x] 2.2 Entrypoint synthetics → exit 90: trailing-slash RO child (the
      exact repro); trailing-slash RO parent with writable child;
      `..`-segment entry; `//` entry; relative entry; RO root not in
      SAFE. Verify: all pass; the existing trailing-slash NORMALIZATION
      case (writable, no RO) still registers normally.

## 3. Docs + sweep

- [x] 3.1 CHANGELOG `[Unreleased]` Security entry (both bypasses, the
      shared representation fix, the non-git symlinked-workspace
      session-id note). Verify: claims match behavior.
- [x] 3.2 Full sweep: python suite, shellcheck, doc-consistency,
      multirepo + landlock + profile suites green (image rebuilt).
      Verify: all pass locally.
