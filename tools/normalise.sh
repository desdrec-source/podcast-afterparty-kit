#!/usr/bin/env bash
# Gentle loudness normalisation: -16 LUFS integrated, TP <= -1 dBTP, loudnorm kept LINEAR.
# Usage: normalise.sh <in> <out.mp3> [target_I=-16] [target_TP=-1]
# Steps: measure -> static gain + oversampled true-peak limiter (pre-limit) -> measure ->
#        loudnorm linear pass (48 kHz) -> MP3 192k (libmp3lame) -> verify with ebur128 peak=true.
# Falls back to loudnorm dynamic only if linear mode is refused, and says so.
set -euo pipefail
IN="$1"; OUT="$2"; I="${3:--16}"; TP="${4:--1}"
[ -f "$IN" ] || { echo "no input: $IN" >&2; exit 2; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
LTP=$(python3 -c "print($TP-1.0)")          # loudnorm TP target with 1 dB headroom for MP3 overshoot
LIM=$(python3 -c "print($TP-1.5)")          # limiter ceiling (dBTP), below loudnorm target

measure() { # file [filters] -> json of loudnorm pass 1
  ffmpeg -hide_banner -nostats -i "$1" -af "${2:+$2,}loudnorm=I=$I:TP=$LTP:LRA=20:print_format=json" -f null - 2>&1 \
   | python3 -c 'import sys,re,json;t=sys.stdin.read();print(json.dumps(json.loads(re.findall(r"\{[^{}]*\}",t)[-1])))'
}
j() { python3 -c "import json,sys;print(json.loads(sys.argv[1])[sys.argv[2]])" "$1" "$2"; }
ebu() { # file -> "I TP LRA"
  ffmpeg -hide_banner -nostats -i "$1" -af ebur128=peak=true:framelog=quiet -f null - 2>&1 | python3 -c '
import sys,re;t=sys.stdin.read().split("Summary:")[-1]
g=lambda k:re.search(k+r":\s+(-?[\d.]+|-inf)",t).group(1);print(g("I"),g("Peak"),g("LRA"))'
}

M1=$(measure "$IN")
I1=$(j "$M1" input_i); TP1=$(j "$M1" input_tp)
GAIN=$(python3 -c "print(round($I-($I1),2))")
echo "[1] measured: I=$I1 LUFS TP=$TP1 dBTP LRA=$(j "$M1" input_lra) LU  -> static gain ${GAIN} dB"

# [2] gain + true-peak limiter at 4x oversampling (192k), back to 48k float.
#     Iterate the gain (max 4 tries) so the limited file lands within 0.3 LU of target,
#     leaving loudnorm only a tiny offset -> linear mode is possible.
for TRY in 1 2 3 4; do
  ffmpeg -hide_banner -v error -y -i "$IN" -af "aresample=192000,volume=${GAIN}dB,alimiter=limit=$(python3 -c "print(10**($LIM/20))"):attack=1:release=60:level=disabled:asc=1,aresample=48000" \
    -c:a pcm_f32le "$TMP/pre.wav"
  M2=$(measure "$TMP/pre.wav"); I2=$(j "$M2" input_i)
  echo "[2.$TRY] gain ${GAIN} dB + limiter (ceiling ${LIM} dBTP): I=$I2 TP=$(j "$M2" input_tp) LRA=$(j "$M2" input_lra)"
  python3 -c "import sys;sys.exit(0 if abs($I-($I2))<=0.3 else 1)" && break
  GAIN=$(python3 -c "print(round($GAIN+($I-($I2)),2))")
done

# [3] loudnorm linear second pass
LN="loudnorm=I=$I:TP=$LTP:LRA=20:linear=true:measured_I=$(j "$M2" input_i):measured_TP=$(j "$M2" input_tp):measured_LRA=$(j "$M2" input_lra):measured_thresh=$(j "$M2" input_thresh):offset=$(j "$M2" target_offset):print_format=json"
LOG=$(ffmpeg -hide_banner -nostats -y -i "$TMP/pre.wav" -af "$LN,aresample=48000" -c:a pcm_f32le "$TMP/norm.wav" 2>&1)
MODE=$(echo "$LOG" | python3 -c 'import sys,re,json;print(json.loads(re.findall(r"\{[^{}]*\}",sys.stdin.read())[-1])["normalization_type"])')
if [ "$MODE" != "linear" ]; then
  echo "[3] WARNING: loudnorm refused LINEAR mode (got '$MODE'); FALLING BACK TO DYNAMIC loudnorm"
  ffmpeg -hide_banner -v error -y -i "$IN" -af "loudnorm=I=$I:TP=$LTP:LRA=11:linear=false,aresample=48000" -c:a pcm_f32le "$TMP/norm.wav"
  MODE="dynamic (fallback)"
else
  echo "[3] loudnorm second pass: LINEAR mode confirmed"
fi
ffmpeg -hide_banner -v error -y -i "$TMP/norm.wav" -ar 48000 -c:a libmp3lame -b:a 192k "$OUT"

read BI BTP BLRA < <(ebu "$IN"); read AI ATP ALRA < <(ebu "$OUT")
echo
printf "%-8s %12s %12s %10s\n" "" "I (LUFS)" "TP (dBTP)" "LRA (LU)"
printf "%-8s %12s %12s %10s\n" before "$BI" "$BTP" "$BLRA" after "$AI" "$ATP" "$ALRA"
python3 - "$AI" "$ATP" "$I" "$TP" "$MODE" <<'PY'
import sys;ai,atp,ti,tt=map(float,sys.argv[1:5])
ok=abs(ai-ti)<=1 and atp<=tt
print(f"mode={sys.argv[5]}  spec(I {ti}±1, TP<={tt}): {'PASS' if ok else 'FAIL'}");sys.exit(0 if ok else 1)
PY
