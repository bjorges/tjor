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
            # detect_runtime issues a single combined `docker info` call.
            case "${3:-}" in
                '{{.OperatingSystem}}|{{.Name}}') printf '%s|%s\n' "${MOCK_OS}" "${MOCK_NAME}" ;;
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

# The denial-log check (ADR 0012): the log must be EXACTLY the multiset the
# probes declared. Driven against hand-made files, no docker.
WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT
mk() {  # mk <name> <content…>: a file whose lines are the remaining args
    printf '%s\n' "${@:2}" > "${WORK}/$1"
}
denials_case() {  # denials_case <label> <want-exit> <out-file> <log-file>
    local label="$1" want="$2" got=0
    conformance_denials_match "${WORK}/$3" "${WORK}/$4" >/dev/null 2>&1 || got=$?
    [[ "${got}" == "${want}" ]] && ok "denial check: ${label}" || bad "denial check: ${label} (wanted exit ${want}, got ${got})"
}
T=$'\t'
mk out.ok   "ok   a" "expect-denial${T}a.test${T}host-block" "expect-denial${T}a.test${T}host-block" "expect-denial${T}b.test${T}path-block" "conformance: 3/3 probes passed"
mk log.ok   "a.test${T}host-block${T}t1" "b.test${T}path-block${T}t2" "a.test${T}host-block${T}t3"
mk log.miss "a.test${T}host-block${T}t1" "b.test${T}path-block${T}t2"
mk log.extra "a.test${T}host-block${T}t1" "b.test${T}path-block${T}t2" "a.test${T}host-block${T}t3" "c.test${T}default-deny${T}t4"
mk log.swap "a.test${T}host-block${T}t1" "b.test${T}path-block${T}t2" "b.test${T}path-block${T}t3"
mk out.none "ok   a" "conformance: 1/1 probes passed"
mk log.none
denials_case "exact multiset passes"            0 out.ok   log.ok
denials_case "a missing denial fails"           1 out.ok   log.miss
denials_case "an undeclared denial fails"       1 out.ok   log.extra
denials_case "same total, wrong pair fails"     1 out.ok   log.swap
denials_case "no declarations at all fails"     1 out.none log.none

echo
echo "conformance-runtime: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
