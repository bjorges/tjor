# ADR 0003 — Clean-room provenance rules

**Date:** 2026-09-04 · **Status:** accepted

tjor's design is informed by production systems the author has operated or studied, some of which are proprietary or unlicensed. The build is clean-room:

1. **May reuse:** architectural patterns, requirements, failure modes, and operational lessons — knowledge carried from working experience, recorded in [`docs/clean-room-charter.md`](../clean-room-charter.md).
2. **May not reuse:** files, code, scripts, or configuration fragments from proprietary or unlicensed reference systems. OSS dependencies (cplt, mitmproxy, CoreDNS, LiteLLM, Docker/Compose) are used normally and their sources read freely.
3. **When a needed detail is neither in the charter nor re-derivable:** re-derive it from first principles here, documenting the decision — never copy.
4. **Provenance hygiene in public artifacts:** commits, issues, specs, and docs never name private reference systems, their owners, commit hashes, or internal review/audit events. That lineage lives only in the local, uncommitted tracker (ADR 0002).
5. **Time and infrastructure:** all tjor work happens on personal time and personal infrastructure.
