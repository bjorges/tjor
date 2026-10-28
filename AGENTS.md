# Working in this repository (for coding agents and humans alike)

tjor runs AI coding agents inside a fail-closed container cage. This file is how changes to tjor
itself are made. The README says what tjor does; `docs/clean-room-charter.md` says why.

## Landing a change

- Work on a branch and open a pull request. Never commit to or push `main`; the pull request's
  CI is the merge gate. Details, including the repository settings that enforce this:
  `CONTRIBUTING.md`.
- Substantial capabilities go through OpenSpec (`openspec/`, the `/opsx:*` commands): the spec
  is the source of truth; project-level decisions become ADRs in `docs/decisions/`.
- Before you say a change is done, run and report the local gates:
  `python -m pytest python/tests -q`, `tests/doc_consistency.sh`, `tests/slides_consistency.sh`,
  `shellcheck --severity=warning` on changed shell files. Regenerate `docs/boundary-matrix.md`
  (`python3 python/gen_boundary_matrix.py`) when a probe changed.
- Releases are PRs too: `VERSION` bump plus a `CHANGELOG.md` section, merged, then the merge
  commit on `main` is tagged. Do not tag from a branch.

## Rules the code already follows

- Pin everything: actions by commit SHA, images by digest, downloads by SHA256. A tag is not a pin.
- Fail closed and degrade loudly. A tier that is absent says so; a config that cannot be parsed
  denies, never allows.
- State limits plainly, in the README, the spec and the slide. A mechanism without a stated
  residual is suspicious, not finished.
- Cite the issue and the charter lesson a change answers.
- Provenance (ADR 0003): never name private reference systems, their owners, hashes or internal
  review events anywhere public. Such notes live only in the local, uncommitted tracker.
- `.dockerignore` is an allowlist; a new `COPY` source needs its `!path` line
  (`tests/doc_consistency.sh` checks it).

## Keeping documentation true

- `README.md` is the operator's contract and carries the honest residuals.
- `docs/boundary-matrix.md` is generated; never edit it by hand.
- `slides/presentations/overview/slides.md` explains every capability, one or more slides per
  problem, each tagged with the spec it describes. A changed spec fails CI until its slide is
  re-read and the pin updated (`slides/agents.md`, "Keeping the deck in sync").
- `CHANGELOG.md` is the release notes: every user-visible change, under `## [Unreleased]`.
