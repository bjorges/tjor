#!/usr/bin/env bash
# Kernel-sandbox tier integration test (#9). Two halves:
#   A. Live session via `tjor run` on a Landlock-capable engine — asserts the
#      tier goes ACTIVE, in-repo dotenv is masked, outside-tree access is
#      kernel-denied, the cage proxy env survives the wrap, and the harness
#      still reaches the proxy (strictly-additive invariant); and, since the
#      /proc grant (#103), that every denial under /proc is a kernel EACCES
#      with a docker-exec control, that the stated residuals hold as stated,
#      and that opencode v2 starts, serves and dies with the container.
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
# Comparisons that never put probe or engine output into shell text (a quote
# in a command line would break out of a bash -c string) and print what was
# seen when they fail (#103 review round 3).
check_is()    { local msg="$1" got="$2" want="$3"; if [[ "${got}" == "${want}" ]]; then ok "${msg}"; else bad "${msg} (got=[${got:0:300}] want=[${want}])"; fi; }
check_has()   { local msg="$1" hay="$2" needle="$3"; if [[ "${hay}" == *"${needle}"* ]]; then ok "${msg}"; else bad "${msg} (got=[${hay:0:300}] needs=[${needle}])"; fi; }
check_lacks() { local msg="$1" hay="$2" needle="$3"; if [[ "${hay}" != *"${needle}"* ]]; then ok "${msg}"; else bad "${msg} (got=[${hay:0:300}] must not contain=[${needle}])"; fi; }
# Bounded host-side engine calls (macOS has no `timeout` without coreutils).
tmo() { if command -v timeout >/dev/null 2>&1; then timeout "$@"; elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$@"; else shift; "$@"; fi; }

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
    ( cd "${HOME}/.tjor/tmp/landlock-wt" 2>/dev/null && "${T}" down --session g5 >/dev/null 2>&1 )
    docker network rm "tjor-${SID:-nope}_internal" >/dev/null 2>&1
    rm -rf "${REPO}" "${SCRATCH}" "${HOME}"/.tjor/sessions/landlock-repo-* "${HOME}"/.tjor/sessions/landlock-wt-* \
        "${HOME}/.tjor/tmp/landlock-wt" "${HOME}/.tjor/tmp/landlock-wtmain"
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
"${T}" build > "${SCRATCH}/build.out" 2>&1 || { echo "FATAL: tjor build failed:" >&2; tail -n 60 "${SCRATCH}/build.out" >&2; exit 1; }
# rc 1 is the probe's own verdict (landlock_create_ruleset failed); any other
# nonzero rc is a failed probe (docker, the image, the entrypoint), reported
# as such and never read as "no Landlock".
LANDLOCK_HERE=0; LANDLOCK_PROBE_RC=0
tmo 120 docker run --rm "${IMAGE}" python3 -c 'import ctypes,sys; l=ctypes.CDLL(None,use_errno=True); l.syscall.restype=ctypes.c_long; sys.exit(0 if l.syscall(444,None,0,1)>=0 else 1)' > "${SCRATCH}/llprobe.out" 2>&1 || LANDLOCK_PROBE_RC=$?
case "${LANDLOCK_PROBE_RC}" in
    0) LANDLOCK_HERE=1; echo "== engine Landlock support: yes" ;;
    1) echo "== engine Landlock support: no (landlock_create_ruleset failed in the image)" ;;
    *) echo "== engine Landlock probe FAILED (rc=${LANDLOCK_PROBE_RC}); this is not 'no Landlock':" >&2; cat "${SCRATCH}/llprobe.out" >&2 ;;
esac

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
    # the workspace, printed by the checks below when one fails. A failed read
    # records its error text too, so a Landlock denial (EACCES) is told apart
    # from a missing file or an I/O error (#103 review round 3).
    R="${REPO}/probe-result.txt"
    sed "s|__REPO__|${REPO}|g" > "${REPO}/probe.sh" <<'PROBE'
#!/bin/sh
REPO="__REPO__"
R="${REPO}/probe-result.txt"
: > "$R"
say() { echo "$1" >> "$R"; }
try() { # name cmd... -> name=OK | name=denied plus name_err=<first stderr line>
    label="$1"; shift
    if err="$(sh -c "$*" 2>&1 >/dev/null)"; then say "${label}=OK"
    else say "${label}=denied"; say "${label}_err=$(printf %s "${err}" | head -1)"; fi
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
# The pid namespace is the container's: PID 1 is cplt and the process list is
# short (a `pid: host` regression would show hundreds of pids).
say "pid1_comm=$(cat /proc/1/comm 2>/dev/null)"
say "npids=$(ls -d /proc/[0-9]* 2>/dev/null | wc -l | tr -d ' ')"
say "ptrace_scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo absent)"
# /proc inside the tier (#103): each direct read paired with its /proc link;
# the tree's own exe/cwd/fd links resolve and keep the target's path rules.
try child_proc_self "sh -c 'cat /proc/self/maps >/dev/null'"
try self_root_allowed "cat /proc/self/root/etc/os-release"
try proc_root "cat /proc/self/root/etc/hostname"
try proc_cwd_escape "cat /proc/self/cwd/../../../../../../../../../../../../etc/hostname"
try self_exe "readlink -v /proc/self/exe"
try self_cwd_allowed "cat /proc/self/cwd/README.md"
try self_fd "exec 3<'${REPO}/README.md'; head -c1 /proc/self/fd/3"
try pid1_cmdline "head -c1 /proc/1/cmdline"
try pid1_environ "head -c1 /proc/1/environ"
try pid1_root "head -c1 /proc/1/root/etc/os-release"
try pid1_cwd "ls /proc/1/cwd"
try pid1_status "head -c1 /proc/1/status"
try pid1_exe "readlink -v /proc/1/exe"
try pid1_fd0 "readlink -v /proc/1/fd/0"
try proc_meminfo "head -c1 /proc/meminfo"
try proc_sys_read "head -c1 /proc/sys/kernel/hostname"
# Read-only: setting the probe's own comm is a write the agent user may do
# outside the wrap (the docker-exec control proves it) and must be refused
# inside. /proc/sys is Docker's read-only mount, refused with or without the
# wrap (a container-root control proves the mount); the CURRENT value is
# written back, so a broken mount would change nothing on the shared kernel.
(echo tjorprobe > /proc/self/comm 2>/dev/null && say "proc_comm_write=OK" || say "proc_comm_write=refused")
v="$(cat /proc/sys/kernel/randomize_va_space 2>/dev/null)"
if [ -n "${v}" ]; then (echo "${v}" > /proc/sys/kernel/randomize_va_space 2>/dev/null && say "proc_sys_write=OK" || say "proc_sys_write=refused"); else say "proc_sys_write=unreadable"; fi
# A same-sandbox peer (a child of the probe): its entries, its links and its
# memory. /proc/<pid>/mem needs ptrace-attach rights: Landlock allows them
# inside one domain, Yama (kernel.yama.ptrace_scope) then limits them to a
# process's own descendants. Opened from a CHILD of the probe (a tool reading
# the harness) and from a sibling of the peer; the ancestor direction is the
# benign one and is recorded, not asserted.
sleep 120 & SIB=$!
try sibling_environ "head -c1 /proc/${SIB}/environ"
try sib_root_allowed "head -c1 /proc/${SIB}/root/etc/os-release"
try sib_root_denied "head -c1 /proc/${SIB}/root/etc/hostname"
try sib_exe "readlink -v /proc/${SIB}/exe"
try sib_cwd "ls /proc/${SIB}/cwd"
try mem_of_harness_from_child "command exec 4</proc/$$/mem"
try mem_of_sibling "command exec 4</proc/${SIB}/mem"
if command exec 4</proc/${SIB}/mem; then say "mem_of_descendant=OK"; exec 4<&-; else say "mem_of_descendant=refused"; fi
# A same-sandbox peer's open files, reopened through its fd links: a pipe
# (its content is read, which drains it) and a granted regular file. The
# harness's stdio and a stdio MCP transport are such pipes.
sh -c 'echo tjor-pipe-content | sh -c "echo \$\$ > __REPO__/pipe.pid; sleep 120"' &
sh -c "exec 3<'${REPO}/README.md'; echo \$\$ > '${REPO}/peer.pid'; sleep 120" &
i=0; while [ "$i" -lt 20 ] && { [ ! -s "${REPO}/pipe.pid" ] || [ ! -s "${REPO}/peer.pid" ]; }; do i=$((i + 1)); sleep 1; done
PP="$(cat "${REPO}/pipe.pid" 2>/dev/null)"; FP="$(cat "${REPO}/peer.pid" 2>/dev/null)"
say "peer_pipe=[$(head -c 17 "/proc/${PP:-0}/fd/0" 2>/dev/null)]"
say "peer_file=[$(head -c 2 "/proc/${FP:-0}/fd/3" 2>/dev/null)]"
# A same-uid process started OUTSIDE the wrap (the test runs it with docker
# exec -u agent) holding a GRANTED workspace file open on fd 3 and a denied
# file on fd 4: both fd targets must be refused (the ptrace rule, not the
# path rules), its environ refused, its command line readable.
i=0; while [ "$i" -lt 90 ] && [ ! -s "${REPO}/holder.pid" ]; do i=$((i + 1)); sleep 1; done
HP="$(cat "${REPO}/holder.pid" 2>/dev/null)"
if [ -n "${HP}" ] && [ -d "/proc/${HP}" ]; then
    try holder_fd_granted "head -c1 /proc/${HP}/fd/3"
    try holder_fd_denied "head -c1 /proc/${HP}/fd/4"
    try holder_environ "head -c1 /proc/${HP}/environ"
    try holder_cmdline "head -c1 /proc/${HP}/cmdline"
else
    for k in holder_fd_granted holder_fd_denied holder_environ holder_cmdline; do say "${k}=absent"; done
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
    # harness tree, holding a granted workspace file (fd 3) and a Landlock-
    # denied file (fd 4) open. Every host-side engine call is bounded and
    # none aborts the suite: a failure reads as a failed check with its value.
    tmo 60 docker exec -d -u agent "${CTR}" sh -c "exec 3<'${REPO}/README.md' 4</etc/hostname; echo \$\$ > '${REPO}/holder.pid'; sleep 600" || true
    for _ in $(seq 1 30); do [[ -s "${REPO}/holder.pid" ]] && break; sleep 1; done
    HOLDER_PID="$(cat "${REPO}/holder.pid" 2>/dev/null || true)"
    # Controls, outside the wrap: the same reads and the same write the wrap
    # refuses succeed for the agent user, so each refusal is Landlock's (the
    # path rules or the ptrace rule), not file permissions; and container
    # root cannot write /proc/sys either, so that one is Docker's mount.
    DAC_READ="$(tmo 60 docker exec -u agent "${CTR}" cat /etc/hostname 2>/dev/null | wc -c | tr -d ' ' || true)"
    DAC_COMM_WRITE="$(tmo 60 docker exec -u agent "${CTR}" sh -c 'echo tjorctl > /proc/self/comm && echo OK' 2>/dev/null || true)"
    DAC_PID1="$(tmo 60 docker exec -u agent "${CTR}" sh -c 'head -c1 /proc/1/environ >/dev/null && readlink /proc/1/exe >/dev/null && ls /proc/1/cwd >/dev/null && readlink /proc/1/fd/0 >/dev/null && head -c1 /proc/1/root/etc/os-release >/dev/null && echo OK' 2>/dev/null || true)"
    DAC_HOLDER="$(tmo 60 docker exec -u agent "${CTR}" sh -c "head -c1 /proc/${HOLDER_PID:-0}/fd/3 >/dev/null && head -c1 /proc/${HOLDER_PID:-0}/environ >/dev/null && echo OK" 2>/dev/null || true)"
    ROOT_SYS_WRITE="$(tmo 60 docker exec -u root "${CTR}" sh -c 'v=$(cat /proc/sys/kernel/randomize_va_space) && { echo "$v" > /proc/sys/kernel/randomize_va_space; } 2>/dev/null && echo OK || echo refused' 2>/dev/null || true)"
    for _ in $(seq 1 600); do grep -qx DONE "${R}" 2>/dev/null && break; sleep 1; done

    field() { { grep "^$1=" "${R}" 2>/dev/null || true; } | head -1 | cut -d= -f2-; }
    dn() { # a denial that is a kernel refusal (EACCES), not a missing file or an I/O error
        local v e; v="$(field "$1")"; e="$(field "$1_err")"
        if [[ "${v}" == denied && "${e}" == *"ermission denied"* ]]; then echo EACCES; else echo "${v}:${e}"; fi
    }

    check "the in-wrap probe finished within the wait" grep -qx DONE "${R}"
    check "launch announced the dotenv masks" grep -q "dotenv mask ${REPO}/.env" "${SCRATCH}/run.out"
    check "launch announced the nested dotenv mask" grep -q "dotenv mask ${REPO}/sub/.env" "${SCRATCH}/run.out"
    AGENT_LOG="$(tmo 60 docker logs "${CTR}" 2>&1 || true)"
    check_has "entrypoint logged kernel-sandbox ACTIVE" "${AGENT_LOG}" "kernel-sandbox: active (landlock ABI"

    # Masking (container-wide): content unreadable, secret absent, immovable.
    check_is "workspace .env reads empty (masked)" "$(field env_dotenv)" "[]"
    check_is "nested sub/.env reads empty (masked)" "$(field env_nested)" "[]"
    check "secret string is absent from the masked file" bash -c "! grep -q '${SECRET}' '${R}'"
    check_has ".env.example (template) is NOT masked" "$(field template)" "TEMPLATE"
    check_is "masked .env cannot be unlinked in-cage" "$(field unlink)" "refused"
    check "secret nowhere in the agent env" bash -c \
        "! docker exec '${CTR}' sh -c env | grep -q '${SECRET}'"

    # Kernel tier (in the wrapped tree): outside-tree denied, workspace usable.
    check_is "outside-tree read is kernel-denied" "$(dn outside_read)" EACCES
    check_is "outside-tree read denial is Landlock's (the file is readable outside the wrap)" "$([[ "${DAC_READ:-0}" != 0 ]] && echo readable || echo "unreadable(${DAC_READ})")" readable
    check_is "outside-tree write is kernel-denied" "$(field outside_write)" denied
    check_is "workspace is writable under the wrap" "$(field workspace_write)" OK

    # /proc inside the tier (#103): cplt's own /proc/self rule covers the first
    # pid only, so without the wrap's /proc grant a forked child cannot read
    # its own maps and every Bun-compiled child (opencode v2's server) aborts.
    # The grant is read-only and subtracts nothing: each direct denial is
    # paired with its /proc link and asserted to be EACCES, the controls show
    # the same reads succeed outside the wrap, and the stated residuals are
    # recorded so a change in either direction is visible.
    NPIDS="$(field npids)"
    check_is "no host process is visible from the wrap (PID 1 is cplt, the pid namespace is the container's)" "$(field pid1_comm):$([[ "${NPIDS:-999}" -lt 100 ]] && echo few || echo "many(${NPIDS})")" "cplt:few"
    check_is "a forked child reads its own /proc/self under the wrap (#103)" "$(field child_proc_self)" OK
    check_is "an allowed path resolves through /proc/self/root (the link is live)" "$(field self_root_allowed)" OK
    check_is "a denied path stays denied through /proc/self/root" "$(dn proc_root)" EACCES
    check_is "a denied path stays denied through a /proc/self/cwd traversal" "$(dn proc_cwd_escape)" EACCES
    check_is "the tree's own exe, cwd and fd links resolve (self and same-sandbox)" "$(field self_exe)/$(field self_cwd_allowed)/$(field self_fd)/$(field sib_exe)/$(field sib_cwd)" "OK/OK/OK/OK/OK"
    check_is "PID 1's command line is readable from the wrap (stated residual)" "$(field pid1_cmdline)" OK
    check_is "PID 1's environ is unreadable from the wrap" "$(dn pid1_environ)" EACCES
    check_is "PID 1's root link is unreadable from the wrap" "$(dn pid1_root)" EACCES
    check_is "PID 1's cwd link is unreadable from the wrap" "$(dn pid1_cwd)" EACCES
    check_is "PID 1's exe and fd targets are unreadable from the wrap" "$(dn pid1_exe)/$(dn pid1_fd0)" "EACCES/EACCES"
    check_is "PID 1's private entries are readable outside the wrap (control: the refusal is Landlock's ptrace rule)" "${DAC_PID1}" OK
    check_is "PID 1's status is readable from the wrap (stated residual)" "$(field pid1_status)" OK
    check_is "kernel-wide /proc status files are readable under the wrap (stated residual)" "$(field proc_meminfo)/$(field proc_sys_read)" "OK/OK"
    check_is "a /proc/self/comm write succeeds outside the wrap (control)" "${DAC_COMM_WRITE}" OK
    check_is "/proc is not writable under the wrap" "$(field proc_comm_write)" refused
    check_is "Docker's read-only /proc/sys holds under the wrap" "$(field proc_sys_write)" refused
    check_is "Docker's /proc/sys mount is read-only even for container root (control)" "${ROOT_SYS_WRITE}" refused
    check_is "a sibling in the same sandbox exposes its environ (stated residual)" "$(field sibling_environ)" OK
    check_is "a same-sandbox process's root link keeps the target's path rules" "$(field sib_root_allowed)/$(dn sib_root_denied)" "OK/EACCES"
    check_is "a same-sandbox peer's pipe and open file are readable through its fd links (stated residual)" "$(field peer_pipe)/$(field peer_file)" "[tjor-pipe-content]/[hi]"
    check_is "an unsandboxed same-uid process's open fds are unreadable from the wrap whatever they point at" "$(dn holder_fd_granted)/$(dn holder_fd_denied)" "EACCES/EACCES"
    check_is "an unsandboxed same-uid process's environ is unreadable from the wrap" "$(dn holder_environ)" EACCES
    check_is "the unsandboxed process's fd and environ are readable outside the wrap (control: the refusal is Landlock's ptrace rule)" "${DAC_HOLDER}" OK
    check_is "an unsandboxed same-uid process's command line is readable from the wrap (stated residual)" "$(field holder_cmdline)" OK
    # Peer memory follows the engine's Yama setting: with ptrace_scope >= 1
    # (Ubuntu's default, the CI runner, Colima) a process may open only its
    # own descendants' memory, so a tool cannot read the harness's; with 0 or
    # no Yama any process in the sandbox may, and the entrypoint must have
    # said so at start. The suite asserts whichever case the engine is in and
    # names the value, so the matrix row states which one was measured.
    YAMA="$(field ptrace_scope)"
    echo "== engine kernel.yama.ptrace_scope: ${YAMA} (peer memory: $(field mem_of_harness_from_child) from a child, $(field mem_of_sibling) from a sibling, $(field mem_of_descendant) from the ancestor)"
    case "${YAMA}" in
        1|2|3)
            check_is "a process in the sandbox cannot open the harness's memory when Yama ptrace_scope is 1 or higher" "$(dn mem_of_harness_from_child)/$(dn mem_of_sibling)" "EACCES/EACCES"
            check_lacks "the entrypoint states the Yama peer-memory residual exactly when it applies" "${AGENT_LOG}" "kernel.yama.ptrace_scope" ;;
        *)
            check_is "a process in the sandbox can open the harness's memory when Yama ptrace_scope is 0 or absent (stated residual)" "$(field mem_of_harness_from_child)" OK
            check_has "the entrypoint states the Yama peer-memory residual exactly when it applies" "${AGENT_LOG}" "kernel.yama.ptrace_scope" ;;
    esac

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
        check_is "opencode v2 standalone starts under the wrap (#103)" "$(field opencode_standalone)" OK
        check_is "the managed opencode config is loaded under the wrap" "$(field managed_config)" OK
        check_is "opencode v2 default mode starts under the wrap (#103)" "$(field opencode_service)" OK
        check_has "the opencode v2 service registration names a live in-container service" "$(field service_cmd)" "opencode serve --service"
        HTTP="$(field service_http)"
        check_is "the opencode v2 service answers on its registered loopback URL" "$([[ "${HTTP}" =~ ^[1-5][0-9][0-9]$ ]] && echo answered || echo "no-answer(${HTTP})")" answered
        check_is "a second opencode v2 invocation reuses the in-container service" "$(field opencode_service2)/$([[ -n "${SVC_ID}" && "${SVC_ID}" == "$(field service_id_after)" ]] && echo same-id || echo "id-changed(${SVC_ID}->$(field service_id_after))")" "OK/same-id"
        for k in opencode_standalone managed_config opencode_service opencode_service2; do
            [[ "$(field "${k}")" == "OK" ]] || { show_err "${REPO}"/probe-*.err; break; }
        done
    fi

    # Strictly additive: proxy env survives the wrap; harness reaches the proxy.
    check_has "HTTP_PROXY survives the wrap" "$(field http_proxy)" ":8080"
    check_has "lowercase http_proxy survives the wrap" "$(field http_proxy_lc)" ":8080"
    check "an allowed host egresses through the proxy" bash -c \
        "field() { grep '^egress=' '${R}' | cut -d= -f2-; }; field | grep -Eq '\[(200|301|302)\]'"

    # The service dies with the container, tied to THIS session's service:
    # docker top reports the engine-side pid of the in-container service
    # (anchored on the opencode binary, so a wrapper or the client never
    # matches), and a throwaway --pid=host container with no capabilities
    # reads that pid's command line from the engine's process table before
    # the session is stopped and after. The inspection prints a sentinel
    # whenever it RAN, so "no survivor" is asserted only on an inspection
    # that ran and found the pid gone; a failed docker run has no sentinel
    # and fails both checks. Works the same on a Linux engine host and inside
    # the Colima VM.
    host_cmdline() { tmo 60 docker run --rm --pid=host --network none --cap-drop ALL --security-opt no-new-privileges -u 65534 --entrypoint sh "${IMAGE}" -c 'p="/proc/'"$1"'/cmdline"; if [ -e "$p" ]; then printf "INSPECTED:"; tr "\0" " " < "$p"; else printf "INSPECTED:gone"; fi'; }
    svc_state() { case "$1" in INSPECTED:*"opencode serve --service"*) echo seen;; INSPECTED:*) echo inspected-absent;; *) echo "no-inspection(${1:0:120})";; esac; }
    HOST_SVC_PID="$(tmo 60 docker top "${CTR}" -o pid,args 2>/dev/null | awk '$2 ~ /(^|\/)opencode$/ && $3 == "serve" && $4 == "--service" {print $1; exit}' || true)"
    if [[ -n "${SVC_ID}" && -z "${HOST_SVC_PID}" ]]; then
        echo "no engine-side pid for 'opencode serve --service'; docker top saw:" >&2
        tmo 60 docker top "${CTR}" -o pid,args >&2 || true
    fi
    SEEN_BEFORE="no-engine-pid"; SEEN_AFTER="no-engine-pid"
    if [[ -n "${HOST_SVC_PID}" ]]; then SEEN_BEFORE="$(host_cmdline "${HOST_SVC_PID}")" || SEEN_BEFORE="inspection-failed(rc=$?):${SEEN_BEFORE}"; fi

    ( cd "${REPO}" && "${T}" down --session ll >/dev/null 2>&1 )

    if [[ -n "${HOST_SVC_PID}" ]]; then SEEN_AFTER="$(host_cmdline "${HOST_SVC_PID}")" || SEEN_AFTER="inspection-failed(rc=$?):${SEEN_AFTER}"; fi
    if [[ -z "${SVC_ID}" ]]; then
        echo "ok   (skipped: no opencode service outlives the container — no service ran)"
    else
        check_is "the engine-side inspection sees the session's service before down (control)" "$(svc_state "${SEEN_BEFORE}")" seen
        check_is "no opencode service outlives the container" "$(svc_state "${SEEN_AFTER}")" inspected-absent
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
        for _ in $(seq 1 180); do grep -qx DONE "${R2}" 2>/dev/null && break; sleep 1; done
        field2() { { grep "^$1=" "${R2}" 2>/dev/null || true; } | head -1 | cut -d= -f2-; }
        NEW_ID="$(field2 new_id)"
        check_is "session state kept the service registration across down (precondition)" "$(field2 stale_id)" "${SVC_ID}"
        check_is "a relaunch with a stale registration starts a fresh in-container service" "$(field2 relaunch_service)/$([[ -n "${NEW_ID}" && "${NEW_ID}" != "${SVC_ID}" ]] && echo fresh-id || echo "stale-id(${NEW_ID})")" "OK/fresh-id"
        [[ "$(field2 relaunch_service)" == "OK" ]] || show_err "${REPO}/probe-relaunch.err"
        ( cd "${REPO}" && "${T}" down --session ll >/dev/null 2>&1 )
    fi
else
    if [[ ${STRICT} == 1 ]]; then
        if [[ ${LANDLOCK_PROBE_RC} == 1 ]]; then
            echo "strict mode: the engine has no Landlock, the live half cannot run" >&2
        else
            echo "strict mode: the Landlock probe itself failed (rc=${LANDLOCK_PROBE_RC}), which is not 'no Landlock'; its output is above" >&2
        fi
        check "entrypoint logged kernel-sandbox ACTIVE" false
    else
        echo "ok   (skipped live-session half: engine has no Landlock, or its probe failed with rc=${LANDLOCK_PROBE_RC})"
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
m3field() { { grep "^$1=" "${M3R}" 2>/dev/null || true; } | head -1 | cut -d= -f2-; }
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
g1field() { { grep "^$1=" "${G1R}" 2>/dev/null || true; } | head -1 | cut -d= -f2-; }
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
g3field() { { grep "^$1=" "${G3R}" 2>/dev/null || true; } | head -1 | cut -d= -f2-; }
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
g5field() { { grep "^$1=" "${G5R}" 2>/dev/null || true; } | head -1 | cut -d= -f2-; }
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
check_has "auto+unavailable degrades to INACTIVE" "${out}" "kernel-sandbox: INACTIVE"
check_has "auto+unavailable still runs the harness" "${out}" "HARNESS-RAN"

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
check_has "off states disabled-by-config" "${out}" "kernel-sandbox: disabled by config"
check_has "off runs the harness unwrapped" "${out}" "HARNESS-RAN"

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
