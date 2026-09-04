# ADR 0002 — Planning stack

**Date:** 2026-09-04 · **Status:** accepted

Three layers, each with one job:

1. **OpenSpec** (`openspec/`) — in-repo source of truth for specs, change proposals, designs, and per-change task lists. Every substantial capability (cage core, D1–D4) enters as an OpenSpec change: propose → apply → verify → archive. Chosen to prevent the documented failure mode of tjor's planning phase: a monolithic design doc revised in place until its head contradicts its body.
2. **GitHub issues** — the public backlog: bugs, roadmap items, discussion. Issues are written pattern-level and provenance-clean (see ADR 0003).
3. **Local dcat** (`.dogcats/`, gitignored, never committed) — private provenance notes only: where a lesson or requirement actually came from, references that must not be published. This is the privacy boundary; if a note can't go in a GitHub issue, it goes here.

Decision records (this directory) capture project-level choices that outlive any single change.
