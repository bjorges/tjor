#!/usr/bin/env bash
# Kernel-sandbox tier integration test (#9). Two halves:
#   A. Live session via `tjor run` on a Landlock-capable engine — asserts the
#      tier goes ACTIVE, in-repo dotenv is masked, outside-tree access is
#      kernel-denied, the cage proxy env survives the wrap, and the harness
#      still reaches the proxy (strictly-additive invariant).
#   B. The entrypoint's four-way handoff driven directly on the image, with a
#      seccomp profile that makes the landlock syscalls fail (EPERM) to
#      simulate a runtime without Landlock — asserts auto degrades LOUDLY and
#      still runs, require aborts before the harness, off runs unwrapped, and
#      masking is independent of the kernel tier.
set -euo pipefail

T="${TJOR_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/tjor}"
IMAGE="${TJOR_AGENT_IMAGE:-tjor-agent-opencode:local}"
REPO="${HOME}/.tjor/tmp/landlock-repo"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/tjor-landlock.XXXXXX")"
SECRET="landlock-secret-$$-do-not-leak"
PASS=0; FAIL=0
# CI runs strict (TJOR_LANDLOCK_TEST_STRICT=1): an engine without Landlock or an
# image without opencode FAILS the suite instead of skipping the live half, so
# a runner that cannot prove the fix never reports green (#103 review).
STRICT="${TJOR_LANDLOCK_TEST_STRICT:-0}"

ok()  { echo "ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL $1" >&2; FAIL=$((FAIL + 1)); }
check() { local msg="$1"; shift; if "$@" >/dev/null 2>&1; then ok "${msg}"; else bad "${msg}"; fi; }

hash8() {
    if command -v sha256sum >/dev/null; then printf %s "$1" | sha256sum | cut -c1-8
    else printf %s "$1" | shasum -a 256 | cut -c1-8; fi
}

# shellcheck disable=SC2329  # invoked via the EXIT trap
cleanup() {
    set +e
    docker ps -aq --filter "label=tjor.workspace=${REPO}" | xargs -r docker rm -f >/dev/null 2>&1
    [[ -n "${SID:-}" ]] && ( cd "${REPO}" 2>/dev/null && "${T}" down --session ll >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session dp >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session mo >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session m3 >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session m4 >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session g1 >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session g2 >/dev/null 2>&1 )
    ( cd "${REPO}" 2>/dev/null && "${T}" down --session g3 >/dev/null 2>&1 )
    docker network rm "tjor-${SID:-nope}_internal" >/dev/null 2>&1
    rm -rf "${REPO}" "${SCRATCH}" "${HOME}"/.tjor/sessions/landlock-repo-*
    return 0
}
trap cleanup EXIT

wait_for_agent() { # session id -> echoes container id
    local ctr
    for _ in $(seq 1 180); do
        ctr="$(docker ps -q --filter "label=tjor.role=agent" --filter "label=tjor.session=$1" --filter status=running | head -1)"
        [[ -n "${ctr}" ]] && { echo "${ctr}"; return 0; }
        sleep 1
    done
    return 1
}

# A seccomp profile that lets everything run EXCEPT the landlock syscalls,
# which return EPERM — a runtime where the probe must classify the tier
# unavailable. (Docker's default profile ALLOWS these three; this overrides.)
DENY="${SCRATCH}/deny-landlock.json"
cat > "${DENY}" <<'JSON'
{
  "defaultAction": "SCMP_ACT_ALLOW",
  "syscalls": [
    { "names": ["landlock_create_ruleset", "landlock_add_rule", "landlock_restrict_self"],
      "action": "SCMP_ACT_ERRNO", "errnoRet": 1 }
  ]
}
JSON

echo "== pre-building images"
"${T}" build >/dev/null 2>&1
LANDLOCK_HERE=0
if docker run --rm "${IMAGE}" python3 -c 'import ctypes,sys; l=ctypes.CDLL(None,use_errno=True); l.syscall.restype=ctypes.c_long; sys.exit(0 if l.syscall(444,None,0,1)>=0 else 1)' >/dev/null 2>&1; then
    LANDLOCK_HERE=1
fi
echo "== engine Landlock support: $([[ ${LANDLOCK_HERE} == 1 ]] && echo yes || echo no)"

# ---- A. live session (only meaningful where the engine supports Landlock) ----
# The kernel tier restricts the HARNESS process tree, not the whole container:
# Landlock is inherited per-process-tree from the cplt-wrapped process, so a
# fresh `docker exec` (an operator action from OUTSIDE that tree) is
# deliberately unrestricted. In-tree assertions therefore run AS the harness
# command — a probe script whose findings land in the bind-mounted workspace,
# which the host reads back. (Mount masks are container-wide, so those hold for
# docker exec too, but we check them from in-tree for a single consistent view.)
if [[ ${LANDLOCK_HERE} == 1 ]]; then
    mkdir -p "${REPO}/sub"
    cd "${REPO}" && git init -q 2>/dev/null
    printf 'API_KEY=%s\n' "${SECRET}" > "${REPO}/.env"
    printf 'NESTED=%s\n' "${SECRET}" > "${REPO}/sub/.env"
    echo 'TEMPLATE=placeholder' > "${REPO}/.env.example"
    echo hi > "${REPO}/README.md"

    # Probe runs inside the wrapped tree, writes key=value findings to R, sleeps
    # so the container stays up for log inspection. Written from a quoted
    # heredoc with __REPO__ substituted, so nothing but the path expands on the
    # host. Every opencode call is bounded by `timeout` and its stderr lands in
    # the workspace, printed by the checks below when one fails.
    R="${REPO}/probe-result.txt"
    sed "s|__REPO__|${REPO}|g" > "${REPO}/probe.sh" <<'PROBE'
#!/bin/sh
REPO="__REPO__"
R="${REPO}/probe-result.txt"
: > "$R"
say() { echo "$1" >> "$R"; }
try() { # name cmd... -> name=OK | name=denied
    label="$1"; shift
    if sh -c "$*" >/dev/null 2>&1; then say "${label}=OK"; else say "${label}=denied"; fi
}
say "env_dotenv=[$(cat "${REPO}/.env" 2>/dev/null)]"
say "env_nested=[$(cat "${REPO}/sub/.env" 2>/dev/null)]"
say "template=[$(cat "${REPO}/.env.example" 2>/dev/null)]"
(rm -f "${REPO}/.env" 2>/dev/null && say "unlink=REMOVED" || say "unlink=refused")
# /etc/hostname is world-readable in the image and outside cplt's system
# grants: a denial here is Landlock's (the docker-exec control proves the
# file-permission half).
try outside_read "cat /etc/hostname"
(touch /opt/tjor/evil 2>/dev/null && say "outside_write=OK" || say "outside_write=denied")
(echo w > "${REPO}/wprobe" 2>/dev/null && say "workspace_write=OK" || say "workspace_write=denied")
# /proc inside the tier (#103): each direct read paired with its /proc link.
try child_proc_self "sh -c 'cat /proc/self/maps >/dev/null'"
try self_root_allowed "cat /proc/self/root/etc/os-release"
try proc_root "cat /proc/self/root/etc/hostname"
try proc_cwd_escape "cat /proc/self/cwd/../../../../../../../../../../../../etc/hostname"
try pid1_cmdline "head -c1 /proc/1/cmdline"
try pid1_environ "head -c1 /proc/1/environ"
try pid1_root "head -c1 /proc/1/root/etc/os-release"
try pid1_cwd "ls /proc/1/cwd"
try proc_meminfo "head -c1 /proc/meminfo"
(echo 0 > /proc/sys/kernel/randomize_va_space 2>/dev/null && say "proc_write=OK" || say "proc_write=refused")
sleep 30 & SIB=$!
try sibling_environ "head -c1 /proc/${SIB}/environ"
kill "${SIB}" 2>/dev/null
# A same-uid process started OUTSIDE the wrap (the test runs it with docker
# exec -u agent) holding a denied file open on fd 3: wait for its pid.
i=0; while [ "$i" -lt 90 ] && [ ! -s "${REPO}/holder.pid" ]; do i=$((i + 1)); sleep 1; done
HP="$(cat "${REPO}/holder.pid" 2>/dev/null)"
if [ -n "${HP}" ] && [ -d "/proc/${HP}" ]; then
    try holder_fd "head -c1 /proc/${HP}/fd/3"
    try holder_environ "head -c1 /proc/${HP}/environ"
    try holder_cmdline "head -c1 /proc/${HP}/cmdline"
else
    say "holder_fd=absent"; say "holder_environ=absent"; say "holder_cmdline=absent"
fi
# opencode v2 (#103): --standalone, the managed config (#46), and the shipped
# default service mode: fresh state, registration, loopback URL, reuse.
if command -v opencode >/dev/null 2>&1; then
    (timeout 90 opencode --standalone session list >/dev/null 2>"${REPO}/probe-standalone.err" && say "opencode_standalone=OK" || say "opencode_standalone=failed")
    (timeout 90 opencode --standalone debug config 2>"${REPO}/probe-config.err" | grep -q "tjor-managed-sentinel" && say "managed_config=OK" || say "managed_config=missing")
    (timeout 90 opencode session list >/dev/null 2>"${REPO}/probe-service.err" && say "opencode_service=OK" || say "opencode_service=failed")
    SJ="${HOME}/.local/state/opencode/service.json"
    SP="$(jq -r '.pid // empty' "${SJ}" 2>/dev/null)"; SU="$(jq -r '.url // empty' "${SJ}" 2>/dev/null)"
    say "service_id=$(jq -r '.id // empty' "${SJ}" 2>/dev/null)"
    say "service_pid=${SP:-none}"
    say "service_cmd=[$(tr '\0' ' ' < "/proc/${SP:-0}/cmdline" 2>/dev/null)]"
    say "service_url=${SU:-none}"
    say "service_http=$(curl --noproxy '*' -s -o /dev/null -m 10 -w '%{http_code}' "${SU:-http://127.0.0.1:0}/" 2>/dev/null)"
    (timeout 90 opencode session list >/dev/null 2>"${REPO}/probe-service2.err" && say "opencode_service2=OK" || say "opencode_service2=failed")
    say "service_id_after=$(jq -r '.id // empty' "${SJ}" 2>/dev/null)"
else
    for k in opencode_standalone managed_config opencode_service opencode_service2; do say "${k}=absent"; done
fi
say "http_proxy=[${HTTP_PROXY}]"
say "http_proxy_lc=[${http_proxy}]"
say "egress=[$(curl -fsS -o /dev/null -w %{http_code} https://github.com 2>/dev/null)]"
say "DONE"
sleep 600
PROBE
    chmod +x "${REPO}/probe.sh"

    # A hardened profile carrying only a managed file: the entrypoint deploys
    # it root-owned to /etc/opencode, and the probe must see its key under the
    # wrap (the directory is outside cplt's system grants; #103 review).
    PROFILE="${SCRATCH}/profile"
    mkdir -p "${PROFILE}/managed"
    printf '{"$schema":"https://opencode.ai/config.json","username":"tjor-managed-sentinel"}\n' > "${PROFILE}/managed/opencode.json"

    SID="landlock-repo-$(hash8 "${REPO}")-ll"
    "${T}" run --detach --session ll --profile-dir "${PROFILE}" -- sh "${REPO}/probe.sh" > "${SCRATCH}/run.out" 2>&1
    CTR="$(wait_for_agent "${SID}")" || { echo "FATAL: session never started"; cat "${SCRATCH}/run.out"; exit 1; }
    # The unsandboxed same-uid process: an operator's docker exec, outside the
    # harness tree, keeping a Landlock-denied file open on fd 3.
    docker exec -d -u agent "${CTR}" sh -c "exec 3</etc/hostname; echo \$\$ > '${REPO}/holder.pid'; sleep 600"
    DAC_READ="$(docker exec -u agent "${CTR}" cat /etc/hostname 2>/dev/null | wc -c | tr -d ' ')"
    for _ in $(seq 1 240); do grep -q DONE "${R}" 2>/dev/null && break; sleep 1; done

    field() { grep "^$1=" "${R}" 2>/dev/null | head -1 | cut -d= -f2-; }

    check "launch announced the dotenv masks" grep -q "dotenv mask ${REPO}/.env" "${SCRATCH}/run.out"
    check "launch announced the nested dotenv mask" grep -q "dotenv mask ${REPO}/sub/.env" "${SCRATCH}/run.out"
    check "entrypoint logged kernel-sandbox ACTIVE" bash -c \
        "docker logs '${CTR}' 2>&1 | grep -q 'kernel-sandbox: active (landlock ABI'"

    # Masking (container-wide): content unreadable, secret absent, immovable.
    check "workspace .env reads empty (masked)" test "$(field env_dotenv)" = "[]"
    check "nested sub/.env reads empty (masked)" test "$(field env_nested)" = "[]"
    check "secret string is absent from the masked file" bash -c "! grep -q '${SECRET}' '${R}'"
    check ".env.example (template) is NOT masked" bash -c "field() { grep '^template=' '${R}' | cut -d= -f2-; }; field | grep -q TEMPLATE"
    check "masked .env cannot be unlinked in-cage" test "$(field unlink)" = "refused"
    check "secret nowhere in the agent env" bash -c \
        "! docker exec '${CTR}' sh -c env | grep -q '${SECRET}'"

    # Kernel tier (in the wrapped tree): outside-tree denied, workspace usable.
    check "outside-tree read is kernel-denied" test "$(field outside_read)" = "denied"
    check "outside-tree read denial is Landlock's (the file is readable outside the wrap)" test "${DAC_READ}" != "0"
    check "outside-tree write is kernel-denied" test "$(field outside_write)" = "denied"
    check "workspace is writable under the wrap" test "$(field workspace_write)" = "OK"

    # /proc inside the tier (#103): cplt's own /proc/self rule covers the first
    # pid only, so without the wrap's /proc grant a forked child cannot read
    # its own maps and every Bun-compiled child (opencode v2's server) aborts.
    # The grant is read-only and subtracts nothing: each direct denial is
    # paired with its /proc link, and the stated residuals are recorded so a
    # change in either direction is visible.
    check "a forked child reads its own /proc/self under the wrap (#103)" test "$(field child_proc_self)" = "OK"
    check "an allowed path resolves through /proc/self/root (the link is live)" test "$(field self_root_allowed)" = "OK"
    check "a denied path stays denied through /proc/self/root" test "$(field proc_root)" = "denied"
    check "a denied path stays denied through a /proc/self/cwd traversal" test "$(field proc_cwd_escape)" = "denied"
    check "PID 1's command line is readable from the wrap (stated residual)" test "$(field pid1_cmdline)" = "OK"
    check "PID 1's environ is unreadable from the wrap" test "$(field pid1_environ)" = "denied"
    check "PID 1's root link is unreadable from the wrap" test "$(field pid1_root)" = "denied"
    check "PID 1's cwd link is unreadable from the wrap" test "$(field pid1_cwd)" = "denied"
    check "kernel-wide /proc status files are readable under the wrap (stated residual)" test "$(field proc_meminfo)" = "OK"
    check "/proc is not writable under the wrap" test "$(field proc_write)" = "refused"
    check "a sibling in the same sandbox exposes its environ (stated residual)" test "$(field sibling_environ)" = "OK"
    check "an unsandboxed same-uid process's open fd to a denied file is unreadable from the wrap" test "$(field holder_fd)" = "denied"
    check "an unsandboxed same-uid process's environ is unreadable from the wrap" test "$(field holder_environ)" = "denied"
    check "an unsandboxed same-uid process's command line is readable from the wrap (stated residual)" test "$(field holder_cmdline)" = "OK"

    # opencode v2 under the real wrap (#103), offline: --standalone, the
    # managed config (#46) and the shipped default service mode. A failing
    # call prints the stderr the probe captured.
    show_err() { local f; for f in "$@"; do [[ -s "${f}" ]] && { echo "---- $(basename "${f}")" >&2; head -c 2000 "${f}" >&2; echo >&2; }; done; return 0; }
    SVC_ID="$(field service_id)"
    if [[ "$(field opencode_standalone)" == "absent" ]]; then
        if [[ ${STRICT} == 1 ]]; then
            echo "strict mode: the image has no opencode, the #103 launch cannot be proven" >&2
            check "opencode v2 standalone starts under the wrap (#103)" false
        else
            echo "ok   (skipped opencode checks: image has no opencode)"
        fi
    else
        check "opencode v2 standalone starts under the wrap (#103)" test "$(field opencode_standalone)" = "OK"
        check "the managed opencode config is loaded under the wrap" test "$(field managed_config)" = "OK"
        check "opencode v2 default mode starts under the wrap (#103)" test "$(field opencode_service)" = "OK"
        check "the opencode v2 service registration names a live in-container service" bash -c "grep -q 'opencode serve --service' <<<'$(field service_cmd)'"
        check "the opencode v2 service answers on its registered loopback URL" bash -c "[[ '$(field service_http)' =~ ^[1-5][0-9][0-9]$ ]]"
        check "a second opencode v2 invocation reuses the in-container service" bash -c "[[ -n '${SVC_ID}' && '${SVC_ID}' == '$(field service_id_after)' && '$(field opencode_service2)' == OK ]]"
        for k in opencode_standalone managed_config opencode_service opencode_service2; do
            [[ "$(field "${k}")" == "OK" ]] || { show_err "${REPO}"/probe-*.err; break; }
        done
    fi

    # Strictly additive: proxy env survives the wrap; harness reaches the proxy.
    check "HTTP_PROXY survives the wrap" bash -c "field() { grep '^http_proxy=' '${R}' | cut -d= -f2-; }; field | grep -q ':8080'"
    check "lowercase http_proxy survives the wrap" bash -c "grep '^http_proxy_lc=' '${R}' | grep -q ':8080'"
    check "an allowed host egresses through the proxy" bash -c \
        "field() { grep '^egress=' '${R}' | cut -d= -f2-; }; field | grep -Eq '\[(200|301|302)\]'"

    ( cd "${REPO}" && "${T}" down --session ll >/dev/null 2>&1 )

    # The service dies with the container: on a Linux engine host the
    # container's processes are visible to pgrep; through Colima, inside the
    # VM. The bracket keeps the pattern from matching its own shell.
    survivor="unknown"
    if [[ "$(uname -s)" == "Linux" ]]; then
        if pgrep -f 'opencode serve --servic[e]' >/dev/null 2>&1; then survivor=yes; else survivor=no; fi
    elif command -v colima >/dev/null 2>&1; then
        if colima ssh -- pgrep -f 'opencode serve --servic[e]' >/dev/null 2>&1; then survivor=yes; else survivor=no; fi
    fi
    if [[ -z "${SVC_ID}" ]]; then
        echo "ok   (skipped: no opencode service outlives the container — no service ran)"
    elif [[ "${survivor}" == "unknown" ]]; then
        echo "ok   (skipped: no opencode service outlives the container — engine host not inspectable from here)"
    else
        check "no opencode service outlives the container" test "${survivor}" = "no"
    fi

    # Relaunch with the stale registration: the session home persists across
    # down, so service.json still names the dead service; the client must
    # register a fresh one (a new id) inside the new container.
    if [[ -n "${SVC_ID}" ]]; then
        R2="${REPO}/probe2-result.txt"
        sed "s|__REPO__|${REPO}|g" > "${REPO}/probe2.sh" <<'PROBE2'
#!/bin/sh
REPO="__REPO__"
R="${REPO}/probe2-result.txt"
: > "$R"
SJ="${HOME}/.local/state/opencode/service.json"
echo "stale_id=$(jq -r '.id // empty' "${SJ}" 2>/dev/null)" >> "$R"
(timeout 90 opencode session list >/dev/null 2>"${REPO}/probe-relaunch.err" && echo "relaunch_service=OK" || echo "relaunch_service=failed") >> "$R"
echo "new_id=$(jq -r '.id // empty' "${SJ}" 2>/dev/null)" >> "$R"
echo "DONE" >> "$R"
sleep 600
PROBE2
        "${T}" run --detach --session ll --profile-dir "${PROFILE}" -- sh "${REPO}/probe2.sh" > "${SCRATCH}/run2.out" 2>&1
        wait_for_agent "${SID}" >/dev/null || { echo "FATAL: relaunch never started"; cat "${SCRATCH}/run2.out"; exit 1; }
        for _ in $(seq 1 120); do grep -q DONE "${R2}" 2>/dev/null && break; sleep 1; done
        field2() { grep "^$1=" "${R2}" 2>/dev/null | head -1 | cut -d= -f2-; }
        check "session state kept the service registration across down (precondition)" test "$(field2 stale_id)" = "${SVC_ID}"
        check "a relaunch with a stale registration starts a fresh in-container service" bash -c "[[ '$(field2 relaunch_service)' == OK && -n '$(field2 new_id)' && '$(field2 new_id)' != '${SVC_ID}' ]]"
        [[ "$(field2 relaunch_service)" == "OK" ]] || show_err "${REPO}/probe-relaunch.err"
        ( cd "${REPO}" && "${T}" down --session ll >/dev/null 2>&1 )
    fi
else
    if [[ ${STRICT} == 1 ]]; then
        echo "strict mode: the engine has no Landlock, the live half cannot run" >&2
        check "entrypoint logged kernel-sandbox ACTIVE" false
    else
        echo "ok   (skipped live-session half: engine has no Landlock)"
    fi
fi

# ---- A2. deny_paths is independent of mask_dotenv (#48) ----------------------
# The deny-paths loop used to be nested inside the mask_dotenv gate, so
# mask_dotenv = false silently dropped every explicitly configured deny path.
# Launcher-side masking decision — needs no Landlock support on the engine.
mkdir -p "${REPO}"
( cd "${REPO}" && git init -q 2>/dev/null || true )
printf 'API_KEY=%s\n' "${SECRET}" > "${REPO}/.env"
echo "deny-me-${SECRET}" > "${REPO}/denyme.txt"
USERCFG="${SCRATCH}/usercfg"
mkdir -p "${USERCFG}/tjor"
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mask_dotenv = false
deny_paths = ["${REPO}/denyme.txt"]
CFG
( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session dp -- true < /dev/null > "${SCRATCH}/dp.out" 2>&1 || true )
check "deny_paths mask applied with mask_dotenv=false (#48)" \
    grep -q "dotenv mask ${REPO}/denyme.txt (deny_paths)" "${SCRATCH}/dp.out"
check "mask_dotenv=false skips automatic dotenv discovery" bash -c \
    "! grep -q 'dotenv mask ${REPO}/.env\$' '${SCRATCH}/dp.out'"
( cd "${REPO}" && "${T}" down --session dp >/dev/null 2>&1 )

# ---- A3. mask_dirs: project config dirs structurally empty (#43) -------------
# Launcher-side mount masking — needs no Landlock support, runs on any engine.
# mask_dotenv=false alongside proves the independence guarantee (#48 class).
mkdir -p "${REPO}/.opencode/plugins" "${REPO}/subx/.opencode/tools"
printf 'EVILCODE-%s\n' "${SECRET}" > "${REPO}/.opencode/plugins/evil.js"
printf 'EVILTOOL\n' > "${REPO}/subx/.opencode/tools/t.js"
# A hostile PARENT dir name: the announced mask path must reach the terminal
# escape-sanitized (same discipline as the dotenv lines).
HD="${REPO}/$(printf '\033')[31mX"
mkdir -p "${HD}/.opencode"
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mode = "off"
mask_dotenv = false
mask_dirs = [".opencode"]
CFG
M3R="${REPO}/m3-result.txt"
( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session m3 -- sh -c "
    R='${M3R}'; : > \"\$R\"
    echo \"top=[\$(ls -A '${REPO}/.opencode' 2>/dev/null | tr '\n' ' ')]\" >> \"\$R\"
    echo \"nested=[\$(ls -A '${REPO}/subx/.opencode' 2>/dev/null | tr '\n' ' ')]\" >> \"\$R\"
    (cat '${REPO}/.opencode/plugins/evil.js' >/dev/null 2>&1 && echo 'read=OK' || echo 'read=denied') >> \"\$R\"
    (touch '${REPO}/.opencode/w' 2>/dev/null && echo 'write=OK' || echo 'write=refused') >> \"\$R\"
    rm -rf '${REPO}/.opencode' 2>/dev/null
    ([ -d '${REPO}/.opencode' ] && echo 'unlink=refused' || echo 'unlink=REMOVED') >> \"\$R\"
    echo DONE >> \"\$R\"
" < /dev/null > "${SCRATCH}/m3.out" 2>&1 || true )
m3field() { grep "^$1=" "${M3R}" 2>/dev/null | head -1 | cut -d= -f2-; }
check "launch announced the .opencode mask" grep -q "dir mask ${REPO}/.opencode" "${SCRATCH}/m3.out"
check "launch announced the nested .opencode mask" grep -q "dir mask ${REPO}/subx/.opencode" "${SCRATCH}/m3.out"
check "hostile parent dir name announced escape-sanitized" \
    grep -q 'dir mask .*\^\[\[31mX/\.opencode' "${SCRATCH}/m3.out"
check "no raw ESC byte on any dir-mask line" bash -c \
    "! grep 'dir mask' '${SCRATCH}/m3.out' | grep -q \"\$(printf '\033')\""
check "masked .opencode lists empty in-cage" test "$(m3field top)" = "[]"
check "nested .opencode lists empty in-cage" test "$(m3field nested)" = "[]"
check "plugin file unreadable at its path" test "$(m3field read)" = "denied"
check "write into the masked dir refused" test "$(m3field write)" = "refused"
check "masked dir cannot be removed in-cage" test "$(m3field unlink)" = "refused"
check "plugin content nowhere in the probe result" bash -c "! grep -q 'EVILCODE' '${M3R}'"
check "mask_dirs applied with mask_dotenv=false (independence)" bash -c \
    "! grep -q 'dotenv mask ${REPO}/.env' '${SCRATCH}/m3.out'"
( cd "${REPO}" && "${T}" down --session m3 >/dev/null 2>&1 )
rm -rf "${HD}"

# Invalid entry (neither absolute nor a bare name) aborts the launch.
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mask_dirs = ["foo/bar"]
CFG
if ( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session m4 -- true < /dev/null > "${SCRATCH}/m4.out" 2>&1 ); then
    bad "invalid mask_dirs entry aborts the launch"
else
    ok "invalid mask_dirs entry aborts the launch"
fi
check "invalid mask_dirs error names the key" grep -qi "mask_dirs" "${SCRATCH}/m4.out"
( cd "${REPO}" && "${T}" down --session m4 >/dev/null 2>&1 )

# ---- A4. git metadata masks (#71): hooks dir masked, config pin opt-in -------
# Launcher-side mount masking — runs on any engine. Layout: the repo carries a
# HOST-installed pre-commit hook that writes a marker when it fires, a nested
# repo, and a linked worktree whose common dir is the repo's own .git.
rm -rf "${REPO}/.opencode" "${REPO}/subx" "${HD}" 2>/dev/null || true
( cd "${REPO}" && git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m base >/dev/null 2>&1 || true )
MARK="${REPO}/hook-fired.txt"; rm -f "${MARK}"
mkdir -p "${REPO}/.git/hooks"
printf '#!/bin/sh\necho fired > "%s"\n' "${MARK}" > "${REPO}/.git/hooks/pre-commit"; chmod +x "${REPO}/.git/hooks/pre-commit"
mkdir -p "${REPO}/nested"; ( cd "${REPO}/nested" && git init -q >/dev/null 2>&1 )
( cd "${REPO}" && git worktree add -q "${REPO}/wt" >/dev/null 2>&1 || true )
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mode = "off"
CFG
G1R="${REPO}/g1-result.txt"
( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session g1 -- sh -c "
    R='${G1R}'; : > \"\$R\"
    echo \"hooks=[\$(ls -A '${REPO}/.git/hooks' 2>/dev/null | tr '\n' ' ')]\" >> \"\$R\"
    (touch '${REPO}/.git/hooks/evil' 2>/dev/null && echo 'write=OK' || echo 'write=refused') >> \"\$R\"
    echo \"nested=[\$(ls -A '${REPO}/nested/.git/hooks' 2>/dev/null | tr '\n' ' ')]\" >> \"\$R\"
    echo \"wt=[\$(ls -A \"\$(git -C '${REPO}/wt' rev-parse --path-format=absolute --git-path hooks 2>/dev/null)\" 2>/dev/null | tr '\n' ' ')]\" >> \"\$R\"
    (cd '${REPO}' && git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m incage >/dev/null 2>&1 && echo 'commit=OK' || echo 'commit=failed') >> \"\$R\"
" < /dev/null > "${SCRATCH}/g1.out" 2>&1 || true )
g1field() { grep "^$1=" "${G1R}" 2>/dev/null | head -1 | cut -d= -f2-; }
check "git hooks: launch announced the workspace hooks mask" grep -q "dir mask ${REPO}/.git/hooks (git hooks)" "${SCRATCH}/g1.out"
check "git hooks: launch announced the nested repo hooks mask" grep -q "dir mask ${REPO}/nested/.git/hooks (git hooks)" "${SCRATCH}/g1.out"
check "git hooks: workspace hooks dir lists empty in-cage" test "$(g1field hooks)" = "[]"
check "git hooks: write into the masked hooks dir refused" test "$(g1field write)" = "refused"
check "git hooks: nested repo hooks dir lists empty in-cage" test "$(g1field nested)" = "[]"
check "git hooks: worktree common-dir hooks list empty in-cage" test "$(g1field wt)" = "[]"
check "git hooks: in-cage commit still succeeds" test "$(g1field commit)" = "OK"
check "git hooks: a host-installed pre-commit hook does not fire in-cage" test ! -e "${MARK}"
( cd "${REPO}" && "${T}" down --session g1 >/dev/null 2>&1 )
rm -f "${MARK}"

# Opt-out: the host hook is visible (and would fire) again.
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mode = "off"
mask_git_hooks = false
CFG
G2R="${REPO}/g2-result.txt"
( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session g2 -- sh -c "
    echo \"hooks=[\$(ls -A '${REPO}/.git/hooks' 2>/dev/null | tr '\n' ' ')]\" > '${G2R}'
" < /dev/null > "${SCRATCH}/g2.out" 2>&1 || true )
check "git hooks: mask_git_hooks=false announces no hooks mask" bash -c "! grep -q '(git hooks)' '${SCRATCH}/g2.out'"
check "git hooks: mask_git_hooks=false leaves the host hook visible" bash -c "grep -q 'pre-commit' '${G2R}'"
( cd "${REPO}" && "${T}" down --session g2 >/dev/null 2>&1 )

# Opt-in config pin: writes fail, reads and commits work, host file unchanged.
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mode = "off"
protect_git_config = true
CFG
CFG_BEFORE="$(hash8 "$(cat "${REPO}/.git/config")")"
G3R="${REPO}/g3-result.txt"
( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session g3 -- sh -c "
    R='${G3R}'; : > \"\$R\"
    (cd '${REPO}' && git config x.y z 2>/dev/null && echo 'cfgwrite=OK' || echo 'cfgwrite=refused') >> \"\$R\"
    (cd '${REPO}' && git remote add o https://example.invalid/r 2>/dev/null && echo 'remoteadd=OK' || echo 'remoteadd=refused') >> \"\$R\"
    (cd '${REPO}' && git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m incage2 >/dev/null 2>&1 && echo 'commit=OK' || echo 'commit=failed') >> \"\$R\"
    (cd '${REPO}' && git config --list >/dev/null 2>&1 && echo 'cfgread=OK' || echo 'cfgread=failed') >> \"\$R\"
" < /dev/null > "${SCRATCH}/g3.out" 2>&1 || true )
g3field() { grep "^$1=" "${G3R}" 2>/dev/null | head -1 | cut -d= -f2-; }
check "config pin: launch announced the pin" grep -q "config pin ${REPO}/.git/config (protect_git_config)" "${SCRATCH}/g3.out"
check "config pin: git config write refused in-cage" test "$(g3field cfgwrite)" = "refused"
check "config pin: git remote add refused in-cage" test "$(g3field remoteadd)" = "refused"
check "config pin: commit still succeeds" test "$(g3field commit)" = "OK"
check "config pin: config stays readable" test "$(g3field cfgread)" = "OK"
check "config pin: host config file unchanged" test "$(hash8 "$(cat "${REPO}/.git/config")")" = "${CFG_BEFORE}"
( cd "${REPO}" && "${T}" down --session g3 >/dev/null 2>&1 )
( cd "${REPO}" && git worktree remove --force "${REPO}/wt" >/dev/null 2>&1 || true )

# ---- A5. worktree workspace (#79): the common dir is mounted, masked, git works
# Layout: a main repository OUTSIDE the workspace (carrying its own pre-commit
# hook that writes a marker), and a linked worktree launched as the
# workspace. Before #79 the agent container died at the entrypoint's first
# git call (exit 128); now the common dir rides along, kernel-granted and
# git-trusted, with its hooks masked.
WTMAIN="${HOME}/.tjor/tmp/landlock-wtmain"; WTWS="${HOME}/.tjor/tmp/landlock-wt"
rm -rf "${WTMAIN}" "${WTWS}"
git init -q "${WTMAIN}"; ( cd "${WTMAIN}" && git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m base )
WTMARK="${WTMAIN}/hook-fired.txt"; mkdir -p "${WTMAIN}/.git/hooks"
printf '#!/bin/sh\necho fired > "%s"\n' "${WTMARK}" > "${WTMAIN}/.git/hooks/pre-commit"; chmod +x "${WTMAIN}/.git/hooks/pre-commit"
git -C "${WTMAIN}" worktree add -q "${WTWS}" -b feat
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mode = "auto"
CFG
G5R="${WTWS}/g5-result.txt"
( cd "${WTWS}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session g5 --allow-worktree-mount -- sh -c "
    R='${G5R}'; : > \"\$R\"
    (git status --short --branch >/dev/null 2>&1 && echo 'status=OK' || echo 'status=failed') >> \"\$R\"
    (git log --oneline -1 >/dev/null 2>&1 && echo 'log=OK' || echo 'log=failed') >> \"\$R\"
    (git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m incage-wt >/dev/null 2>&1 && echo 'commit=OK' || echo 'commit=failed') >> \"\$R\"
    echo \"commonhooks=[\$(ls -A '${WTMAIN}/.git/hooks' 2>/dev/null | tr '\n' ' ')]\" >> \"\$R\"
    echo \"common=\$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)\" >> \"\$R\"
" < /dev/null > "${SCRATCH}/g5.out" 2>&1 || true )
g5field() { grep "^$1=" "${G5R}" 2>/dev/null | head -1 | cut -d= -f2-; }
check "worktree: launch announced the common dir mount" grep -q "worktree common dir ${WTMAIN}/.git (for ${WTWS}" "${SCRATCH}/g5.out"
check "worktree: launch announced the common dir hooks mask" grep -q "dir mask ${WTMAIN}/.git/hooks (git hooks)" "${SCRATCH}/g5.out"
check "worktree: git status works in-cage from a worktree workspace" test "$(g5field status)" = "OK"
check "worktree: git log works in-cage from a worktree workspace" test "$(g5field log)" = "OK"
check "worktree: git commit works in-cage from a worktree workspace" test "$(g5field commit)" = "OK"
check "worktree: the in-cage commit landed in the main repository" bash -c "git -C '${WTWS}' log --oneline -1 | grep -q incage-wt"
check "worktree: the common dir's hooks list empty in-cage" test "$(g5field commonhooks)" = "[]"
check "worktree: the main repository's pre-commit hook did not fire" test ! -e "${WTMARK}"
check "worktree: git resolves the common dir at its host path in-cage" test "$(g5field common)" = "${WTMAIN}/.git"
( cd "${WTWS}" && "${T}" down --session g5 >/dev/null 2>&1 )
rm -rf "${WTWS}" "${WTMAIN}"

# ---- B. handoff branches on the image, Landlock forced unavailable -----------
# auto + unavailable: LOUD degradation, still runs.
out="$(docker run --rm --security-opt seccomp="${DENY}" -e TJOR_LANDLOCK=auto \
        "${IMAGE}" sh -c 'echo HARNESS-RAN' 2>&1)"
check "auto+unavailable degrades to INACTIVE" bash -c "grep -q 'kernel-sandbox: INACTIVE' <<<'${out}'"
check "auto+unavailable still runs the harness" bash -c "grep -q 'HARNESS-RAN' <<<'${out}'"

# require + unavailable: abort BEFORE the harness, with the documented
# boundary exit code (#40, TJOR_EXIT_BOUNDARY=90), not a generic failure.
req_code=0
docker run --rm --security-opt seccomp="${DENY}" -e TJOR_LANDLOCK=require \
        "${IMAGE}" sh -c 'echo SHOULD-NOT-RUN' > "${SCRATCH}/req.out" 2>&1 || req_code=$?
check "require+unavailable aborts with the boundary exit code 90" test "${req_code}" -eq 90
check "require+unavailable did NOT run the harness" bash -c "! grep -q 'SHOULD-NOT-RUN' '${SCRATCH}/req.out'"
check "require+unavailable states FATAL with the reason" grep -q "FATAL: kernel-sandbox required" "${SCRATCH}/req.out"

# off: unwrapped, disabled statement.
out="$(docker run --rm -e TJOR_LANDLOCK=off "${IMAGE}" sh -c 'echo HARNESS-RAN' 2>&1)"
check "off states disabled-by-config" bash -c "grep -q 'kernel-sandbox: disabled by config' <<<'${out}'"
check "off runs the harness unwrapped" bash -c "grep -q 'HARNESS-RAN' <<<'${out}'"

# invalid mode: FATAL, nonzero.
if docker run --rm -e TJOR_LANDLOCK=always "${IMAGE}" sh -c 'echo SHOULD-NOT-RUN' > "${SCRATCH}/inv.out" 2>&1; then
    bad "invalid mode aborts (exit nonzero)"
else
    ok "invalid mode aborts (exit nonzero)"
fi
check "invalid mode names the bad value" grep -q "invalid TJOR_LANDLOCK mode 'always'" "${SCRATCH}/inv.out"

# ---- C. masking is independent of the kernel tier ----------------------------
# Launcher-side mount masks hold even with the tier forced off — needs no
# Landlock support on the engine, so this always runs.
# Escape-injection regression (v0.15.0 security fix): a dotenv FILENAME planted
# in the (untrusted) repo carrying a raw ANSI escape must reach the operator's
# terminal sanitized (ESC rendered visibly as ^[ by tjor_safeprint) through the
# REAL launch path — the sanitizer's own unit tests don't cover the wiring.
EVIL="${REPO}/.env.$(printf '\033')[31mEVIL"
printf 'PWNED=%s\n' "${SECRET}" > "${EVIL}"
cat > "${USERCFG}/tjor/config.toml" <<CFG
[landlock]
mode = "off"
CFG
( cd "${REPO}" && XDG_CONFIG_HOME="${USERCFG}" "${T}" run --session mo -- true < /dev/null > "${SCRATCH}/mo.out" 2>&1 || true )
check "dotenv mask applied with landlock mode=off" \
    grep -q "dotenv mask ${REPO}/.env" "${SCRATCH}/mo.out"
check "hostile dotenv filename is announced escape-sanitized" \
    grep -q 'dotenv mask .*\.env\.\^\[\[31mEVIL' "${SCRATCH}/mo.out"
check "no raw ESC byte on any dotenv-mask line" bash -c \
    "! grep 'dotenv mask' '${SCRATCH}/mo.out' | grep -q \"\$(printf '\033')\""
( cd "${REPO}" && "${T}" down --session mo >/dev/null 2>&1 )

echo
echo "landlock: ${PASS} passed, ${FAIL} failed"
exit "$((FAIL > 0 ? 1 : 0))"
