#!/bin/sh
# Run the Wi-Fi TV remote from an iPhone using a-Shell (free on the App Store).
# Limitations on iOS:
#  - a-Shell's Python runs in a sandbox; raw socket / UDP broadcast support
#    is limited, so Wake-on-LAN may fail. Roku HTTP control and Samsung/LG
#    WebSocket control generally work.
#  - If WoL fails, use your router's app to send the magic packet, or ask a
#    friend on the same Wi-Fi to run scripts/termux-run.sh on their Android.
#
# Usage (inside a-Shell):
#   curl -fsSL <raw-url-of-this-file> | sh
set -eu

APP_DIR="${APP_DIR:-$HOME/Documents/Remote-controller}"
REPO_URL="${REPO_URL:-https://github.com/gvhildebrand/remote-controller.git}"
BRANCH="${BRANCH:-claude/wifi-tv-remote-app-yccOS}"

if [ ! -d "$APP_DIR" ]; then
  echo ">> Cloning $REPO_URL ..."
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git checkout "$BRANCH" 2>/dev/null || true
git pull --ff-only origin "$BRANCH" 2>/dev/null || true

echo ">> Installing Python deps..."
pip install -r requirements.txt

echo ">> Starting server. Open http://127.0.0.1:5000 in Safari."
python server.py
