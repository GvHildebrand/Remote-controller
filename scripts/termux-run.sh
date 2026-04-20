#!/data/data/com.termux/files/usr/bin/env bash
# One-shot bootstrap for running the Wi-Fi TV remote from an Android phone via Termux.
# Usage (inside Termux):
#   curl -fsSL <raw-url-of-this-file> | bash
# or, after cloning:
#   bash scripts/termux-run.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/gvhildebrand/remote-controller.git}"
BRANCH="${BRANCH:-claude/wifi-tv-remote-app-yccOS}"
APP_DIR="${APP_DIR:-$HOME/Remote-controller}"

echo ">> Updating Termux packages..."
yes | pkg update >/dev/null
yes | pkg install -y python git >/dev/null

if [ ! -d "$APP_DIR/.git" ]; then
  echo ">> Cloning $REPO_URL ..."
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git fetch origin "$BRANCH" >/dev/null 2>&1 || true
git checkout "$BRANCH" >/dev/null 2>&1 || true
git pull --ff-only origin "$BRANCH" >/dev/null 2>&1 || true

echo ">> Installing Python deps..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo ">> Starting server on http://127.0.0.1:5000"
echo ">> Open that URL in Chrome on THIS phone."
echo ">> Tap Scan, select your TV, tap Power On. Ctrl+C to stop."
exec python server.py
