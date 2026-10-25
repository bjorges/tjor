#!/usr/bin/env bash
# Slides-consistency lint. The overview deck (slides/presentations/overview)
# explains every capability tjor ships, one or more slides per problem, and it
# must be reviewed whenever a capability's spec changes. This makes that a CI
# invariant rather than a hope, with one mechanism:
#
#   A slide names the spec it describes in its frontmatter as
#       specs: [<capability>@<pin>, ...]
#   where <pin> is the first 8 hex digits of the sha256 of that capability's
#   spec.md as it stood when the slide was last reviewed. So:
#     - every openspec/specs/<capability>/ MUST be tagged by at least one slide
#       (a new capability without a slide fails);
#     - every tag MUST name an existing capability (a renamed or removed spec
#       with a stale slide fails);
#     - every tag's pin MUST equal the spec's current hash (ANY change to the
#       spec file — a requirement added, removed, reworded, a scenario edited —
#       fails until the slide is reviewed and the pin set to the value this
#       check prints).
#   ADR references (`adrs: ['0010']`) must name an existing decision record.
#
# Honest scope: the pin proves the slide was *looked at* after the spec
# changed, not that the review was thorough — a human sets the pin. A spec
# that changes without touching its file (none today) is not seen.
#
# Tags are read from Slidev frontmatter blocks only (the headmatter and each
# slide's `---`-fenced block), never from slide bodies or fenced code, so a
# code sample showing the tag syntax cannot be mistaken for a tag.
#
# Needs bash >= 4 (associative arrays) like tests/doc_consistency.sh, the
# integration tests and bin/tjor itself (README: bash >= 4.4); the stock
# macOS /bin/bash 3.2 is refused with a clear message. No node/pnpm needed:
# this runs in the plain `unit` CI job and in the slides workflow alike. The
# symlinks that give every deck the shared design system are also verified,
# so a checkout that lost them cannot build a drifted deck.
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
    echo "slides-consistency: needs bash >= 4 (found ${BASH_VERSION}); on macOS: brew install bash, then run with that bash" >&2
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPECS_DIR="${ROOT_DIR}/openspec/specs"
ADR_DIR="${ROOT_DIR}/docs/decisions"
DECK="${ROOT_DIR}/slides/presentations/overview/slides.md"
DECK_REL="${DECK#"${ROOT_DIR}"/}"

fail=0
say() { echo "slides-consistency: $*" >&2; }

# First 8 hex digits of a file's sha256 — the pin. sha256sum (coreutils) or
# shasum (macOS, perl); both print "<hex>  <file>".
spec_pin() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -c1-8
}

[[ -f "${DECK}" ]] || { say "FAILED — deck missing: ${DECK_REL}"; exit 1; }

# --- collect tags from frontmatter blocks only ---------------------------------
# Slidev: the file opens with a `---` headmatter block; every later slide starts
# at a `---` separator, optionally followed at once by a `---`-closed frontmatter
# block whose first line is a YAML key. Fenced code (```) is skipped so a `---`
# or a `specs:` sample inside it is never parsed.
declare -A tagged_pins=()    # capability -> space-separated pins seen
declare -A tagged_lines=()   # capability -> line numbers
declare -a adr_refs=()       # "line:id"
line_no=0; in_fence=0; in_fm=0; after_sep=0
while IFS= read -r line || [[ -n "${line}" ]]; do
    line_no=$((line_no + 1))
    if (( ! in_fm )) && [[ "${line}" == '```'* ]]; then in_fence=$((1 - in_fence)); continue; fi
    (( in_fence )) && continue
    if [[ "${line}" == "---" ]]; then
        if (( in_fm )); then in_fm=0; after_sep=0; else after_sep=1; fi
        continue
    fi
    if (( after_sep )); then
        after_sep=0
        if [[ "${line}" =~ ^[A-Za-z_][A-Za-z0-9_-]*: ]]; then in_fm=1; fi
    fi
    (( in_fm )) || continue

    if [[ "${line}" =~ ^specs:[[:space:]]*(.*)$ ]]; then
        body="${BASH_REMATCH[1]}"
        if [[ ! "${body}" =~ ^\[(.*)\]$ ]]; then
            say "FAILED — ${DECK_REL}:${line_no}: specs must be an inline list: specs: [cap@pin, ...] (got: ${body})"
            fail=1; continue
        fi
        IFS=',' read -ra entries <<< "${BASH_REMATCH[1]}"
        for raw in "${entries[@]}"; do
            entry="$(echo "${raw}" | tr -d "[:space:]'\"")"
            [[ -z "${entry}" ]] && continue
            if [[ ! "${entry}" =~ ^([a-z0-9-]+)@([0-9a-f]{8})$ ]]; then
                say "FAILED — ${DECK_REL}:${line_no}: tag '${entry}' is not <capability>@<8-hex pin>"
                fail=1; continue
            fi
            tagged_pins["${BASH_REMATCH[1]}"]+="${BASH_REMATCH[2]} "
            tagged_lines["${BASH_REMATCH[1]}"]+="${line_no} "
        done
    elif [[ "${line}" =~ ^adrs:[[:space:]]*\[(.*)\]$ ]]; then
        IFS=',' read -ra ids <<< "${BASH_REMATCH[1]}"
        for raw in "${ids[@]}"; do
            id="$(echo "${raw}" | tr -d "[:space:]'\"")"
            [[ -n "${id}" ]] && adr_refs+=("${line_no}:${id}")
        done
    fi
done < "${DECK}"

# --- every capability has a slide; every tag names a capability; pins match ---
for spec in "${SPECS_DIR}"/*/spec.md; do
    cap="$(basename "$(dirname "${spec}")")"
    if [[ -z "${tagged_pins[${cap}]:-}" ]]; then
        say "FAILED — capability '${cap}' has no slide: add one to ${DECK_REL} tagged 'specs: [${cap}@$(spec_pin "${spec}")]'"
        fail=1
    fi
done

for cap in "${!tagged_pins[@]}"; do
    spec="${SPECS_DIR}/${cap}/spec.md"
    if [[ ! -f "${spec}" ]]; then
        say "FAILED — slide(s) at line(s) ${tagged_lines[${cap}]}tag '${cap}', but openspec/specs/${cap}/spec.md does not exist (renamed or removed? update the slide)"
        fail=1; continue
    fi
    now="$(spec_pin "${spec}")"
    for pin in ${tagged_pins[${cap}]}; do
        if [[ "${pin}" != "${now}" ]]; then
            say "FAILED — openspec/specs/${cap}/spec.md changed since its slide was reviewed (pin ${pin}, now ${now}; slide at line ${tagged_lines[${cap}]%% *}): re-read the spec, update the slide, then set the tag to '${cap}@${now}'"
            fail=1
        fi
    done
done

# --- ADR references resolve ---
for ref in "${adr_refs[@]:-}"; do
    [[ -z "${ref}" ]] && continue
    at="${ref%%:*}"; id="${ref#*:}"
    if ! compgen -G "${ADR_DIR}/${id}-*.md" >/dev/null; then
        say "FAILED — ${DECK_REL}:${at}: ADR '${id}' has no docs/decisions/${id}-*.md"
        fail=1
    fi
done

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
echo "slides-consistency: every one of ${caps} spec capabilities has a slide reviewed at its current spec; all tags and ADR references resolve"
