#!/usr/bin/env bash
# Doc-consistency lint. The README's "shipped" markers and its roadmap table
# drifted three deltas in a row (a section said "(Dn, shipped)" while the
# summary/roadmap still listed Dn as pending). This catches that class
# structurally with one invariant:
#
#   A delta marked "(Dn, shipped)" anywhere MUST NOT appear as a row in the
#   roadmap table (which lists only remaining deltas), and vice-versa.
set -euo pipefail

README="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/README.md"

# Deltas explicitly marked shipped, e.g. "(D2, shipped)".
mapfile -t shipped < <(grep -oE '\(D[1-4], shipped\)' "${README}" | grep -oE 'D[1-4]' | sort -u)
# Deltas still listed as rows in the roadmap table, e.g. "| **D4 — LLM gateway".
mapfile -t roadmap < <(grep -oE '\| \*\*D[1-4] — ' "${README}" | grep -oE 'D[1-4]' | sort -u)

fail=0
for s in "${shipped[@]:-}"; do
    [[ -z "${s}" ]] && continue
    for r in "${roadmap[@]:-}"; do
        if [[ "${s}" == "${r}" ]]; then
            echo "doc-consistency: ${s} is marked '(${s}, shipped)' but still appears in the roadmap table" >&2
            fail=1
        fi
    done
done

if ((fail)); then
    echo "doc-consistency: FAILED — a shipped delta is still listed as roadmap (align README summary + table)" >&2
    exit 1
fi
echo "doc-consistency: shipped markers and roadmap table agree (shipped=[${shipped[*]:-}] roadmap=[${roadmap[*]:-}])"
