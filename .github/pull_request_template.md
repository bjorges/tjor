<!-- Title: one line a reader of `git log` understands. Body: what changed and why,
     the way the commit history already reads — on a squash merge this body becomes
     the commit message. -->

## What

## Why

## Checklist

- [ ] Local gates pass: `python -m pytest python/tests -q`, `tests/doc_consistency.sh`,
      `tests/slides_consistency.sh`, shellcheck on changed shell files
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]` (user-visible change)
- [ ] Spec updated under `openspec/specs/` and its slide re-read and re-pinned (`slides/agents.md`)
- [ ] `docs/boundary-matrix.md` regenerated if a probe was added, renamed or removed
- [ ] New actions, images and downloads are pinned (SHA / digest / SHA256), never a mutable tag
- [ ] Limits of the mechanism are stated plainly (README, spec, slide)
- [ ] No private reference systems named (ADR 0003)
