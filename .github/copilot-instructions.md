# Copilot instructions for tjor

Read and follow `AGENTS.md` at the repository root; it is the single source of instructions for
coding agents working on tjor. The essentials:

- Work on a branch and land through a pull request with green CI. Never push `main`.
- Run the local gates before declaring a change done: `python -m pytest python/tests -q`,
  `tests/doc_consistency.sh`, `tests/slides_consistency.sh`, shellcheck on changed shell files.
- Pin actions by SHA, images by digest, downloads by SHA256. State a mechanism's limits plainly.
- A changed spec needs its slide re-read and re-pinned (`slides/agents.md`); a user-visible change
  needs a `CHANGELOG.md` entry. Never name private reference systems (ADR 0003).
