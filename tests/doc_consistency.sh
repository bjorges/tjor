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

# Investigation-profile guide (#50): granting pods/log must stay a documented,
# conscious trade-off — the guide must exist AND the README's kube section must
# point at it (same drift class as above: a pointer and its target separating).
DOCS_DIR="$(dirname "${README}")/docs"
if [[ ! -f "${DOCS_DIR}/investigation-profiles.md" ]]; then
    echo "doc-consistency: FAILED — docs/investigation-profiles.md is missing (spec: credential-broker, log access is a documented trade-off)" >&2
    exit 1
fi
if ! grep -q 'investigation-profiles.md' "${README}"; then
    echo "doc-consistency: FAILED — README does not reference docs/investigation-profiles.md from the kube section" >&2
    exit 1
fi
echo "doc-consistency: investigation-profile guide present and referenced"

# Boundary results matrix (#38): docs/boundary-matrix.md is regenerated from the
# conformance + kernel-sandbox suites. The generator's --check runs the
# registry<->source cross-check (a new/renamed/removed probe with no mapping
# fails) AND diffs the committed matrix against a fresh render (a stale doc
# fails) — same drift class as above: a probe and its published guarantee row
# separating.
ROOT_DIR="$(dirname "${README}")"
if ! grep -q 'boundary-matrix.md' "${README}"; then
    echo "doc-consistency: FAILED — README does not reference docs/boundary-matrix.md (#38)" >&2
    exit 1
fi
if ! python3 "${ROOT_DIR}/python/gen_boundary_matrix.py" --check; then
    echo "doc-consistency: FAILED — boundary matrix is stale or its registry is out of sync with the suites (#38)" >&2
    exit 1
fi

# Bounded proxy resolver (#61): the proxy entrypoint must set a bounded
# RES_OPTIONS so a hung getaddrinfo recovers within a known wall time (the
# empirical black-hole bound is a manual/CI check; this asserts the bound is
# wired at all). glibc honors RES_OPTIONS.
if ! grep -q 'RES_OPTIONS' "${ROOT_DIR}/proxy/entrypoint.sh"; then
    echo "doc-consistency: FAILED — proxy/entrypoint.sh does not set RES_OPTIONS to bound the resolver (#61)" >&2
    exit 1
fi
echo "doc-consistency: proxy resolver bound (RES_OPTIONS) wired in the entrypoint"
