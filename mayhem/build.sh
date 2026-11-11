#!/usr/bin/env bash
#
# mayhem/build.sh — build bareiron's fuzz harnesses (sanitized), their -standalone reproducers, and a
# normal-flag server binary for mayhem/test.sh. Runs in the commit image as `mayhem` in /mayhem, offline.
set -euo pipefail

[ -n "${SOURCE_DATE_EPOCH:-}" ] || unset SOURCE_DATE_EPOCH

: "${SANITIZER_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer}"
: "${DEBUG_FLAGS:=-g -gdwarf-3}"
: "${CC:=clang}"
: "${LIB_FUZZING_ENGINE:=-fsanitize=fuzzer}"
: "${MAYHEM_JOBS:=$(nproc)}"
: "${COVERAGE_FLAGS=}"
# SanCov coverage on the fuzzed code (the engine at link time only instruments its own TU).
COVFLAGS="-fsanitize=fuzzer-no-link"
export SANITIZER_FLAGS DEBUG_FLAGS CC LIB_FUZZING_ENGINE MAYHEM_JOBS COVERAGE_FLAGS

cd "$SRC"

# include/registries.h and src/registries.c are generated from Mojang's server.jar by upstream's
# build_registries.js; the Dockerfile produced them once, from a pinned jar, into the deps cache.
REG=/opt/toolchains/deps/minecraft-registries-1.21.8
[ -f "$REG/src/registries.c" ] && [ -f "$REG/include/registries.h" ] || { echo "missing $REG" >&2; exit 1; }

OUT=/mayhem
B="$SRC/mayhem/.build"
rm -rf "$B"; mkdir -p "$B/fuzz" "$B/test"

SRCS="globals tools varnum packets procedures serialize structures worldgen crafting main"
INC="-I$SRC/include -I$REG/include"
# main.c holds handlePacket(); its own main() (the socket server loop) is renamed out of the way.
RENAME_MAIN="-Dmain=bareiron_server_main"

# 1) sanitized project objects (fuzzed code is instrumented, DWARF 3)
for s in $SRCS; do
  extra=""
  [ "$s" = main ] && extra="$RENAME_MAIN"
  # worldgen.c:351 shifts by a negative amount for features in negative chunks (benign on x86, hit by
  # every player that spawns); relaxing only this check, only in this file, keeps the rest fuzzable.
  [ "$s" = worldgen ] && extra="-fno-sanitize=shift-exponent"
  # packets.c unpacks the protocol's block position with `pos << 52 >> 52` on a signed int64 (the
  # sign-extension idiom, overflowing shift-base on every dig/use packet); same treatment, this file only.
  [ "$s" = packets ] && extra="-fno-sanitize=shift-base"
  # varnum.c decodes the protocol's VarInt as `(byte & 0x7F) << position` into an int32 (wiki.vg's reference
  # idiom): the fifth group overflows the signed shift by design, so any 5-byte VarInt would halt every run.
  [ "$s" = varnum ] && extra="-fno-sanitize=shift-base"
  $CC $SANITIZER_FLAGS $COVFLAGS $DEBUG_FLAGS -O1 $INC $extra -c "src/$s.c" -o "$B/fuzz/$s.o" &
done
$CC $SANITIZER_FLAGS $COVFLAGS $DEBUG_FLAGS -O1 $INC -c "$REG/src/registries.c" -o "$B/fuzz/registries.o" &
$CC $SANITIZER_FLAGS $DEBUG_FLAGS -c mayhem/lsan_off.c -o "$B/fuzz/lsan_off.o" &
wait

# 2) harnesses: fuzzer binary + standalone reproducer. recv()/send() are mocked at link time.
WRAP="-Wl,--wrap=recv,--wrap=send"
build_target() {
  local name="$1"; shift
  $CC $SANITIZER_FLAGS $COVFLAGS $DEBUG_FLAGS -O1 $INC "$@" -c mayhem/fuzz_packets.c -o "$B/fuzz/$name.o"
  $CC $SANITIZER_FLAGS $DEBUG_FLAGS $LIB_FUZZING_ENGINE $WRAP "$B/fuzz/$name.o" "$B"/fuzz/{globals,tools,varnum,packets,procedures,serialize,structures,worldgen,crafting,main,registries,lsan_off}.o -lm -o "$OUT/$name"
  $CC $SANITIZER_FLAGS $DEBUG_FLAGS $WRAP "$STANDALONE_FUZZ_MAIN" "$B/fuzz/$name.o" "$B"/fuzz/{globals,tools,varnum,packets,procedures,serialize,structures,worldgen,crafting,main,registries,lsan_off}.o -lm -o "$OUT/$name-standalone"
}
build_target fuzz_session
build_target fuzz_play -DPREJOIN

# 3) the real server with the project's normal flags, for the functional oracle in mayhem/test.sh
for s in $SRCS; do
  $CC -O2 $COVERAGE_FLAGS $INC -c "src/$s.c" -o "$B/test/$s.o" &
done
$CC -O2 $COVERAGE_FLAGS $INC -c "$REG/src/registries.c" -o "$B/test/registries.o" &
wait
$CC -O2 $COVERAGE_FLAGS "$B"/test/*.o -lm -o "$OUT/bareiron-server"
rm -rf "$B"
