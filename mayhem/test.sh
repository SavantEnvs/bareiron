#!/usr/bin/env bash
#
# mayhem/test.sh — behavioral oracle: runs the normal-flag bareiron server (built by mayhem/build.sh) and
# checks what it answers to a real Minecraft 1.21.8 client (status, ping, login, configuration, spawn,
# chunk streaming, chat). If the server binary is neutered or broken the connection checks fail.
set -uo pipefail
[ -n "${SOURCE_DATE_EPOCH:-}" ] || unset SOURCE_DATE_EPOCH
cd "$SRC"

emit_ctrf() {
  local tool="$1" passed="$2" failed="$3" skipped="${4:-0}" pending="${5:-0}" other="${6:-0}"
  local tests=$(( passed + failed + skipped + pending + other ))
  cat > "${CTRF_REPORT:-$SRC/ctrf-report.json}" <<JSON
{
  "results": {
    "tool": { "name": "$tool" },
    "summary": {
      "tests": $tests,
      "passed": $passed,
      "failed": $failed,
      "pending": $pending,
      "skipped": $skipped,
      "other": $other
    }
  }
}
JSON
  printf 'CTRF {"results":{"tool":{"name":"%s"},"summary":{"tests":%d,"passed":%d,"failed":%d,"pending":%d,"skipped":%d,"other":%d}}}\n' \
    "$tool" "$tests" "$passed" "$failed" "$pending" "$skipped" "$other"
  [ "$failed" -eq 0 ]
}

SERVER=/mayhem/bareiron-server
if [ ! -x "$SERVER" ]; then
  echo "missing $SERVER — mayhem/build.sh should have built it" >&2
  emit_ctrf "bareiron-oracle" 0 1 0
  exit 1
fi

out=$(python3 "$SRC/mayhem/oracle.py" "$SERVER" 2>&1)
echo "$out"
passed=$(printf '%s\n' "$out" | grep -c '^PASS ')
failed=$(printf '%s\n' "$out" | grep -c '^FAIL ')
# The oracle always reports at least the status checks; zero results means the oracle itself broke.
if [ $(( passed + failed )) -eq 0 ]; then failed=1; fi
emit_ctrf "bareiron-oracle" "$passed" "$failed" 0
