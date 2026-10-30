#!/usr/bin/env bash
# Required-check parity (CONTRIBUTING "Repository settings"): every job of a
# ci.yml run must be a required status check in the ruleset on `main`, and
# every required check must be a job of that run. A job added to ci.yml
# without its ruleset entry could go red without blocking a merge, which is
# exactly what a new job is added to prevent; a stale entry would block every
# merge on a check that never reports. Both directions fail here.
#
# Reads only. Needs `gh` with read access to the repository (in CI: GH_TOKEN
# from github.token, with `actions: read` on the job). Usage:
#   tests/ruleset_consistency.sh [run-id]
# The run defaults to GITHUB_RUN_ID (the current run, in CI) or the latest
# ci.yml run on the current branch (a run's job list is already complete
# while it is in progress: the matrix expands when the workflow starts).
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
run="${1:-${GITHUB_RUN_ID:-}}"
if [[ -z "${run}" ]]; then
    branch="$(git rev-parse --abbrev-ref HEAD)"
    run="$(gh run list --repo "${REPO}" --workflow ci.yml --branch "${branch}" --limit 1 \
        --json databaseId --jq '.[0].databaseId // empty')"
fi
[[ -n "${run}" ]] || { echo "ruleset-consistency: no ci.yml run to compare against" >&2; exit 1; }

jobs="$(gh api "repos/${REPO}/actions/runs/${run}/jobs?per_page=100" --jq '.jobs[].name' | sort -u)"
required="$(gh api "repos/${REPO}/rules/branches/main" \
    --jq '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context' | sort -u)"
[[ -n "${jobs}" ]] || { echo "ruleset-consistency: run ${run} lists no jobs" >&2; exit 1; }
[[ -n "${required}" ]] || { echo "ruleset-consistency: no required status checks on main (the ruleset is missing or inactive)" >&2; exit 1; }

not_required="$(comm -23 <(printf '%s\n' "${jobs}") <(printf '%s\n' "${required}"))"
no_such_job="$(comm -13 <(printf '%s\n' "${jobs}") <(printf '%s\n' "${required}"))"
rc=0
if [[ -n "${not_required}" ]]; then
    echo "ruleset-consistency: ci.yml job(s) NOT required on main (add the exact name to the ruleset):" >&2
    printf '  %s\n' "${not_required}" >&2
    rc=1
fi
if [[ -n "${no_such_job}" ]]; then
    echo "ruleset-consistency: required check(s) on main that no ci.yml job reports (remove or rename in the ruleset):" >&2
    printf '  %s\n' "${no_such_job}" >&2
    rc=1
fi
[[ "${rc}" -eq 0 ]] && echo "ruleset-consistency: all $(printf '%s\n' "${jobs}" | wc -l | tr -d ' ') ci.yml jobs of run ${run} are required on main, and nothing else is"
exit "${rc}"
