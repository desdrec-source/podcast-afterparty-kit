#!/usr/bin/env bash
# Podcast Afterparty kit installer. Safe to run again: it only installs what is missing.
#   /workspace/.wv   -> yt-dlp + faster-whisper (transcription, downloads)
#   /workspace/.diar -> CPU torch + speechbrain (diarise.py, qa_check.py)
# Override locations with WV=... DIAR=... ; override the interpreter with PYTHON=...
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
WV=${WV:-/workspace/.wv}
DIAR=${DIAR:-/workspace/.diar}
command -v "$PY" >/dev/null || { echo "ERROR: $PY not found (Python 3.11+ needed)"; exit 1; }
"$PY" -c 'import sys; assert sys.version_info>=(3,11), sys.version' || { echo "ERROR: Python 3.11+ needed"; exit 1; }

echo "== checking ffmpeg / ffprobe"
for b in ffmpeg ffprobe; do
  command -v $b >/dev/null || { echo "ERROR: $b not found. macOS: brew install ffmpeg | Debian/Ubuntu: sudo apt install ffmpeg | Windows: winget install ffmpeg"; exit 1; }
done
ffmpeg -hide_banner -filters 2>/dev/null | grep loudnorm >/dev/null || { echo "ERROR: this ffmpeg has no loudnorm filter"; exit 1; }
ffmpeg -hide_banner -encoders 2>/dev/null | grep libmp3lame >/dev/null || { echo "ERROR: this ffmpeg has no libmp3lame encoder"; exit 1; }
ffmpeg -version | head -1

mkvenv() { [ -x "$1/bin/python" ] || "$PY" -m venv "$1"; "$1/bin/python" -m pip install -q --upgrade pip; }

echo "== transcription venv: $WV"
if "$WV/bin/python" -c 'import faster_whisper' 2>/dev/null; then echo "   faster-whisper already installed"; else
  mkvenv "$WV"
  "$WV/bin/pip" install -q "faster-whisper==1.2.1" "av>=15,<16" "ctranslate2==4.8.3"
fi
if command -v yt-dlp >/dev/null || [ -x "$WV/bin/yt-dlp" ]; then echo "   yt-dlp already installed"; else
  "$WV/bin/pip" install -q yt-dlp
fi

echo "== diarisation venv: $DIAR"
if "$DIAR/bin/python" -c 'import torch, torchaudio, speechbrain, sklearn, docx, PIL, faster_whisper, soundfile' 2>/dev/null; then echo "   already installed"; else
  mkvenv "$DIAR"
  "$DIAR/bin/pip" install -q --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1" "torchaudio==2.11.0" \
    || "$DIAR/bin/pip" install -q --index-url https://download.pytorch.org/whl/cpu torch torchaudio
  "$DIAR/bin/pip" install -q "speechbrain==1.1.2" "scikit-learn==1.9.1" "scipy==1.18.1" "numpy==2.5.4" \
    "soundfile==0.14.0" "python-docx==1.2.0" "pillow==12.3.0" "faster-whisper==1.2.1" "av>=15,<16" "requests"
fi

chmod +x tools/*.sh tools/*.py
echo "== smoke test"
"$DIAR/bin/python" -c 'import torch, speechbrain, docx, PIL; print("   torch", torch.__version__, "| speechbrain", speechbrain.__version__)'
"$WV/bin/python" -c 'import faster_whisper; print("   faster-whisper", faster_whisper.__version__)'
YTDLP=$(command -v yt-dlp || echo "$WV/bin/yt-dlp"); echo "   yt-dlp $("$YTDLP" --version)"
echo "== done"
