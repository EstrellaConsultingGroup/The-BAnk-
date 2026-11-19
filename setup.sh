#!/usr/bin/env bash
# Prompt 1: install ffmpeg, yt-dlp, scenedetect and faster-whisper (+ Python deps). Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null; then
  if command -v apt-get >/dev/null; then sudo -n true 2>/dev/null && SUDO=sudo || SUDO=""
    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq ffmpeg fonts-inter || $SUDO apt-get install -y -qq ffmpeg
  elif command -v brew >/dev/null; then brew install ffmpeg
  else echo "Install ffmpeg manually: https://ffmpeg.org/download.html"; exit 1; fi
fi

python3 -m pip install -q --upgrade pip
python3 -m pip install -q -r requirements.txt

# Bundle a bold font so thumbnails/labels look the same everywhere
mkdir -p assets/fonts
if [ ! -f assets/fonts/Inter-Black.otf ]; then
  for f in /usr/share/fonts/opentype/inter/Inter-Black.otf /Library/Fonts/Inter-Black.otf; do
    [ -f "$f" ] && cp "$f" assets/fonts/ && break
  done
fi
[ -f assets/fonts/Inter-Black.otf ] || echo "Optional: put a heavy font at assets/fonts/Inter-Black.otf (https://rsms.me/inter/)"

[ -f .env ] || { cp .env.example .env; echo "Created .env — fill it in (see CONNECT.md). Never paste keys into chat."; }
python3 -m pipeline doctor || true
