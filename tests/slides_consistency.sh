#!/usr/bin/env bash
# Slides-consistency lint. The overview deck (slides/presentations/overview)
# explains every capability tjor ships, one or more slides per problem, and it
# must be updated whenever functionality is added or changed. This makes that
# a CI invariant rather than a hope, with one mechanism:
#
#   A slide names the spec it describes in its frontmatter as
#       specs: [<capability>@<N>, ...]
#   where <N> is the number of `### Requirement:` headings the capability's
#   spec had when the slide was last reviewed. So:
#     - every openspec/specs/<capability>/ MUST be tagged by at least one slide
#       (new functionality without a slide fails);
#     - every tag MUST name an existing capability (a renamed/removed spec with
#       a stale slide fails);
#     - every tag's <N> MUST equal the spec's current requirement count
#       (changed functionality without a slide review fails — review the
#       slide, then bump the pin to the number this check prints).
#   ADR references (`adrs: ['0010']`) must name an existing decision record.
#
# No node/pnpm needed: this runs in the plain `unit` CI job and in the slides
# workflow alike. The symlinks that give every deck the shared design system
# are also verified, so a checkout that lost them cannot build a drifted deck.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPECS_DIR="${ROOT_DIR}/openspec/specs"
ADR_DIR="${ROOT_DIR}/docs/decisions"
DECK="${ROOT_DIR}/slides/presentations/overview/slides.md"

fail=0
say() { echo "slides-consistency: $*" >&2; }

[[ -f "${DECK}" ]] || { say "FAILED — deck missing: ${DECK#"${ROOT_DIR}"/}"; exit 1; }

# --- collect tags: "specs: [a@1, b@2]" lines (one per slide, inline-list form) ---
declare -A tagged_count=()   # capability -> space-separated pins seen
declare -A tagged_lines=()   # capability -> line numbers
line_no=0
while IFS= read -r line; do
    line_no=$((line_no + 1))
    [[ "${line}" =~ ^specs:[[:space:]]*(.*)$ ]] || continue
    body="${BASH_REMATCH[1]}"
    if [[ ! "${body}" =~ ^\[(.*)\]$ ]]; then
        say "FAILED — ${DECK#"${ROOT_DIR}"/}:${line_no}: specs must be an inline list: specs: [cap@N, ...] (got: ${body})"
        fail=1; continue
    fi
    inner="${BASH_REMATCH[1]}"
    IFS=',' read -ra entries <<< "${inner}"
    for raw in "${entries[@]}"; do
        entry="$(echo "${raw}" | tr -d "[:space:]'\"")"
        [[ -z "${entry}" ]] && continue
        if [[ ! "${entry}" =~ ^([a-z0-9-]+)@([0-9]+)$ ]]; then
            say "FAILED — ${DECK#"${ROOT_DIR}"/}:${line_no}: tag '${entry}' is not <capability>@<requirement-count>"
            fail=1; continue
        fi
        cap="${BASH_REMATCH[1]}"; pin="${BASH_REMATCH[2]}"
        tagged_count["${cap}"]+="${pin} "
        tagged_lines["${cap}"]+="${line_no} "
    done
done < "${DECK}"

# --- every capability has a slide; every tag names a capability; pins match ---
req_count() { grep -c '^### Requirement:' "$1" || true; }

for spec in "${SPECS_DIR}"/*/spec.md; do
    cap="$(basename "$(dirname "${spec}")")"
    if [[ -z "${tagged_count[${cap}]:-}" ]]; then
        say "FAILED — capability '${cap}' has no slide: add one to ${DECK#"${ROOT_DIR}"/} tagged 'specs: [${cap}@$(req_count "${spec}")]'"
        fail=1
    fi
done

for cap in "${!tagged_count[@]}"; do
    spec="${SPECS_DIR}/${cap}/spec.md"
    if [[ ! -f "${spec}" ]]; then
        say "FAILED — slide(s) at line(s) ${tagged_lines[${cap}]}tag '${cap}', but openspec/specs/${cap}/spec.md does not exist (renamed or removed? update the slide)"
        fail=1; continue
    fi
    now="$(req_count "${spec}")"
    for pin in ${tagged_count[${cap}]}; do
        if [[ "${pin}" != "${now}" ]]; then
            say "FAILED — '${cap}' now has ${now} requirements; a slide (line ${tagged_lines[${cap}]%% *}…) was reviewed against ${pin}. Functionality changed: update the slide, then set the tag to '${cap}@${now}'"
            fail=1
        fi
    done
done

# --- ADR references resolve ---
adr_line=0
while IFS= read -r line; do
    adr_line=$((adr_line + 1))
    [[ "${line}" =~ ^adrs:[[:space:]]*\[(.*)\]$ ]] || continue
    IFS=',' read -ra ids <<< "${BASH_REMATCH[1]}"
    for raw in "${ids[@]}"; do
        id="$(echo "${raw}" | tr -d "[:space:]'\"")"
        [[ -z "${id}" ]] && continue
        if ! compgen -G "${ADR_DIR}/${id}-*.md" >/dev/null; then
            say "FAILED — ${DECK#"${ROOT_DIR}"/}:${adr_line}: ADR '${id}' has no docs/decisions/${id}-*.md"
            fail=1
        fi
    done
done < "${DECK}"

# --- the shared design system reaches every deck through symlinks ---
for deck_dir in "${ROOT_DIR}"/slides/presentations/*/; do
    for link in components layouts public; do
        p="${deck_dir}${link}"
        if [[ ! -L "${p}" ]] || [[ "$(cd "${deck_dir}" && cd "$(readlink "${link}")" && pwd)" != "${ROOT_DIR}/slides/shared/${link}" ]]; then
            say "FAILED — ${p#"${ROOT_DIR}"/} must be a symlink to ../../shared/${link} (see slides/agents.md)"
            fail=1
        fi
    done
done

# --- the slides workflow actually runs this check and builds the deck ---
WF="${ROOT_DIR}/.github/workflows/slides.yml"
if [[ ! -f "${WF}" ]] || ! grep -q 'slides_consistency.sh' "${WF}" || ! grep -q 'pnpm build' "${WF}"; then
    say "FAILED — .github/workflows/slides.yml must run tests/slides_consistency.sh and 'pnpm build'"
    fail=1
fi

if ((fail)); then
    say "FAILED — the overview deck is out of step with openspec/specs (see slides/agents.md: 'Keeping the deck in sync')"
    exit 1
fi
caps=$(ls -d "${SPECS_DIR}"/*/ | wc -l | tr -d ' ')
echo "slides-consistency: every one of ${caps} spec capabilities has a reviewed slide; all tags and ADR references resolve"
