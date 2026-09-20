#!/usr/bin/env bash
# Conformance runtime detection + attestation (#13), no docker. Sources bin/tjor
# for its functions (source-guard) and drives detect_runtime against MOCKED
# `docker`/`uname` signals, asserting it classifies each runtime and — crucially
# — reports `unknown` rather than mislabel an unrecognized engine. Also checks
# the probe-count parse the attestation line depends on.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }

# shellcheck source=/dev/null
source "${ROOT}/bin/tjor"   # source-guard keeps main() from running

# Mocked engine signals — detect_runtime reads only these + /proc/version + env.
MOCK_CTX="" MOCK_OS="" MOCK_NAME="" MOCK_UNAME="Linux"
docker() {
    case "${1:-} ${2:-}" in
        "context show")  printf '%s\n' "${MOCK_CTX}" ;;
        "info --format")
            case "${3:-}" in
                '{{.OperatingSystem}}|{{.Name}}') printf '%s|%s\n' "${MOCK_OS}" "${MOCK_NAME}" ;;
                '{{.OperatingSystem}}') printf '%s\n' "${MOCK_OS}" ;;
                '{{.Name}}')            printf '%s\n' "${MOCK_NAME}" ;;
                *) return 0 ;;
            esac ;;
        *) return 0 ;;
    esac
}
uname() { [[ "${1:-}" == "-s" ]] && printf '%s\n' "${MOCK_UNAME}"; return 0; }

expect() {  # expect <label> <ctx> <os> <name> <uname> [wsl_env]
    local want="$1"; MOCK_CTX="$2"; MOCK_OS="$3"; MOCK_NAME="$4"; MOCK_UNAME="$5"
    if [[ -n "${6:-}" ]]; then export WSL_DISTRO_NAME="$6"; else unset WSL_DISTRO_NAME; fi
    local got; got="$(detect_runtime)"
    [[ "${got}" == "${want}" ]] && ok "detect_runtime -> ${want} (ctx=${2:-∅} os=${3:-∅})" \
        || bad "detect_runtime: wanted ${want}, got ${got} (ctx=${2:-∅} os=${3:-∅} name=${4:-∅} uname=${5})"
}

# WSL wins regardless of the docker backend (a host-kernel fact).
expect wsl2           "desktop-linux" "Docker Desktop" "docker-desktop" "Linux" "Ubuntu-22.04"
expect colima         "colima"        "Ubuntu 22.04"   "colima"         "Darwin"
expect docker-desktop "desktop-linux" "Docker Desktop" "docker-desktop" "Linux"
expect docker-desktop "default"       "Docker Desktop 4.30.0" "docker-desktop" "Linux"  # OS-string fallback
expect colima         "default"       "Ubuntu 22.04"   "colima"         "Darwin"          # name fallback
expect linux-engine   "default"       "Ubuntu 22.04.3 LTS" "ci-runner-7" "Linux"          # native engine
expect unknown        "default"       ""               ""               "Darwin"          # no markers, non-Linux

# The attestation line's probe count is parsed from the suite summary, not
# hardcoded — verify the parse against a representative summary line.
probes="$(printf 'ok   x\n\nconformance: 17/18 probes passed\n' \
    | sed -n 's/.*conformance: [0-9][0-9]*\/\([0-9][0-9]*\) probes passed.*/\1/p' | tail -1)"
[[ "${probes}" == "18" ]] && ok "attestation probe count parsed from the suite summary (18)" \
    || bad "probe-count parse: wanted 18, got '${probes}'"

echo
echo "conformance-runtime: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
