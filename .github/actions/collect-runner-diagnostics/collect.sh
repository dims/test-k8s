#!/usr/bin/env bash

set -o nounset
set -o pipefail

artifacts_dir="${1:?artifacts dir is required}"
primary_log_path="${2:-}"
diagnostics_dir="${artifacts_dir}/runner-diagnostics"

mkdir -p "${diagnostics_dir}"

run_capture() {
  local name="$1"
  shift

  {
    echo "### ${name}"
    echo "\$ $*"
    "$@"
  } >"${diagnostics_dir}/${name}.txt" 2>&1 || true
}

run_shell_capture() {
  local name="$1"
  shift

  {
    echo "### ${name}"
    echo "\$ $*"
    bash -lc "$*"
  } >"${diagnostics_dir}/${name}.txt" 2>&1 || true
}

{
  echo "captured_at=$(date -Iseconds)"
  echo "runner_name=${RUNNER_NAME:-}"
  echo "runner_os=${RUNNER_OS:-}"
  echo "runner_arch=${RUNNER_ARCH:-}"
  echo "github_repository=${GITHUB_REPOSITORY:-}"
  echo "github_run_id=${GITHUB_RUN_ID:-}"
  echo "github_run_attempt=${GITHUB_RUN_ATTEMPT:-}"
  echo "github_job=${GITHUB_JOB:-}"
  echo "workspace=${GITHUB_WORKSPACE:-}"
  echo "runner_temp=${RUNNER_TEMP:-}"
  echo "runner_tool_cache=${RUNNER_TOOL_CACHE:-}"
  echo "home=${HOME:-}"
  echo "pwd=$(pwd)"
  echo "tmpdir=${TMPDIR:-}"
  echo "artifacts_dir=${artifacts_dir}"
  echo "primary_log_path=${primary_log_path}"
} >"${diagnostics_dir}/context.txt"

if command -v go >/dev/null 2>&1; then
  {
    echo "### go-env"
    go env GOCACHE GOMODCACHE GOPATH GOROOT GOVERSION GOTMPDIR 2>/dev/null
  } >"${diagnostics_dir}/go-env.txt" 2>&1 || true
fi

run_shell_capture os-release 'uname -a; echo; if command -v lsb_release >/dev/null 2>&1; then lsb_release -a; else cat /etc/os-release; fi; echo; uptime'
run_shell_capture env 'env | sort | grep -E "^(ARTIFACTS|CI|GITHUB_|GOMODCACHE|GOCACHE|GOPATH|HOME|PATH|RUNNER_|TMPDIR|USER)=" || true'
run_shell_capture df 'df -h; echo; df -i'
run_shell_capture mounts 'lsblk -o NAME,TYPE,SIZE,FSTYPE,FSAVAIL,FSUSE%,MOUNTPOINTS,ROTA,MODEL,SERIAL 2>/dev/null || true; echo; findmnt -A -o TARGET,SOURCE,FSTYPE,OPTIONS,SIZE,USED,AVAIL 2>/dev/null || true; echo; mount'
run_shell_capture swap-memory 'swapon --show --bytes 2>/dev/null || true; echo; free -h'
run_shell_capture cpu-memory 'nproc; echo; lscpu 2>/dev/null || true; echo; vmstat 1 10 2>/dev/null || vmstat 2>/dev/null || true'
run_shell_capture io 'iostat -xz 1 10 2>/dev/null || iostat -x 1 10 2>/dev/null || iostat 2>/dev/null || true'
run_shell_capture net 'ss -lntup 2>/dev/null || netstat -lntup 2>/dev/null || true'
run_shell_capture processes 'ps -eo pid,ppid,stat,pcpu,pmem,etimes,comm,args --sort=-pcpu | head -n 120'
run_shell_capture systemd 'systemctl --no-pager --full status docker containerd 2>/dev/null || true; echo; systemctl list-units --state=failed --no-pager 2>/dev/null || true'
run_shell_capture dmesg 'sudo dmesg -T | tail -n 200 2>/dev/null || dmesg -T | tail -n 200 2>/dev/null || true'
run_shell_capture journal 'sudo journalctl --no-pager -b -n 400 2>/dev/null || journalctl --no-pager -b -n 400 2>/dev/null || true'
run_shell_capture proc-snapshot 'cat /proc/loadavg; echo; cat /proc/uptime; echo; cat /proc/meminfo; echo; for file in /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory; do echo "### ${file}"; cat "${file}" 2>/dev/null || true; echo; done; echo "### /proc/diskstats"; cat /proc/diskstats; echo; echo "### /proc/vmstat"; cat /proc/vmstat; echo; echo "### /proc/mounts"; cat /proc/mounts'

{
  echo "### artifact tree"
  find "${artifacts_dir}" /tmp/_artifacts -maxdepth 4 -mindepth 1 -print 2>/dev/null | sort
} >"${diagnostics_dir}/artifacts-tree.txt" 2>&1 || true

paths=(
  "${GITHUB_WORKSPACE:-}"
  "${artifacts_dir}"
  "${RUNNER_TEMP:-}"
  "${TMPDIR:-/tmp}"
  "/tmp"
  "${HOME:-}"
)

{
  echo "### key path mount layout"
  for path in "${paths[@]}"; do
    if [ -n "${path}" ] && [ -e "${path}" ]; then
      echo
      echo "## ${path}"
      df -h "${path}" 2>/dev/null || true
      echo
      findmnt -T "${path}" -o TARGET,SOURCE,FSTYPE,OPTIONS,SIZE,USED,AVAIL 2>/dev/null || true
      echo
      stat -c 'path=%n device=%D inode=%i mode=%A uid=%u gid=%g' "${path}" 2>/dev/null || stat -f 'path=%N device=%d inode=%i mode=%Sp uid=%u gid=%g' "${path}" 2>/dev/null || true
    fi
  done
} >"${diagnostics_dir}/path-layout.txt" 2>&1 || true

log_candidates=()
if [ -n "${primary_log_path}" ] && [ -f "${primary_log_path}" ]; then
  log_candidates+=("${primary_log_path}")
fi

while IFS= read -r candidate; do
  if [ -n "${candidate}" ]; then
    log_candidates+=("${candidate}")
  fi
done < <(find "${artifacts_dir}" /tmp/_artifacts -type f \( -name '*integration*.log' -o -name '*.log' -o -name 'junit*.xml' \) 2>/dev/null | sort -u)

chosen_log=""
for candidate in "${log_candidates[@]}"; do
  if [ -f "${candidate}" ]; then
    chosen_log="${candidate}"
    break
  fi
done

if [ -n "${chosen_log}" ]; then
  {
    echo "chosen_log=${chosen_log}"
    echo "size_bytes=$(wc -c <"${chosen_log}")"
  } >"${diagnostics_dir}/log-source.txt"

  startup_regex='Generated self-signed cert|retrying of unary invoker failed|PostStartHook|timed out waiting for the condition|context deadline exceeded|connect: connection refused|apiserver was unable to write a JSON response|Handler timeout|StartTestServer|TestCRD/|TestDRA/'

  grep -En "${startup_regex}" "${chosen_log}" >"${diagnostics_dir}/integration-startup-signals.txt" 2>/dev/null || true
  head -n 120 "${diagnostics_dir}/integration-startup-signals.txt" >"${diagnostics_dir}/integration-startup-signals-head.txt" 2>/dev/null || true
  tail -n 120 "${diagnostics_dir}/integration-startup-signals.txt" >"${diagnostics_dir}/integration-startup-signals-tail.txt" 2>/dev/null || true

  {
    echo "generated_self_signed_cert=$(grep -Ec 'Generated self-signed cert' "${chosen_log}" 2>/dev/null || true)"
    echo "etcd_retrying=$(grep -Ec 'retrying of unary invoker failed' "${chosen_log}" 2>/dev/null || true)"
    echo "post_start_hook_failures=$(grep -Ec 'PostStartHook' "${chosen_log}" 2>/dev/null || true)"
    echo "timeout_waiting_for_condition=$(grep -Ec 'timed out waiting for the condition' "${chosen_log}" 2>/dev/null || true)"
    echo "context_deadline_exceeded=$(grep -Ec 'context deadline exceeded' "${chosen_log}" 2>/dev/null || true)"
    echo "connection_refused=$(grep -Ec 'connect: connection refused' "${chosen_log}" 2>/dev/null || true)"
    echo "handler_timeout=$(grep -Ec 'Handler timeout|http: Handler timeout' "${chosen_log}" 2>/dev/null || true)"
  } >"${diagnostics_dir}/integration-startup-counts.txt"
fi
