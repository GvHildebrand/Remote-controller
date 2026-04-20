"""One-command recovery for iOS a-Shell (and any Python environment).

Paste this into a-Shell to install deps, fetch the latest code, and start
the server in one step:

    python3 -c "import urllib.request;exec(urllib.request.urlopen('https://raw.githubusercontent.com/gvhildebrand/Remote-controller/claude/wifi-tv-remote-app-yccOS/bootstrap.py').read())"

After it prints "Running on http://127.0.0.1:5000", open that URL in Safari.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import urllib.request

REPO = "gvhildebrand/Remote-controller"
BRANCH = "claude/wifi-tv-remote-app-yccOS"
TARBALL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.tar.gz"
DIRNAME = f"Remote-controller-{BRANCH.replace('/', '-')}"
REQUIREMENTS = ["flask", "requests", "websocket-client"]


def install_if_missing() -> bool:
    """Return True if any package was newly installed (caller should re-exec)."""
    missing: list[str] = []
    for module, pkg in (
        ("flask", "flask"),
        ("requests", "requests"),
        ("websocket", "websocket-client"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)
    if not missing:
        print(">> Dependencies already installed.")
        return False
    print(f">> Installing {', '.join(missing)}...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *missing]
    )
    return True


def fetch_source() -> None:
    print(f">> Downloading {TARBALL}")
    with urllib.request.urlopen(TARBALL) as response:
        data = response.read()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(".")
    print(f">> Extracted into ./{DIRNAME}")


def main() -> None:
    install_if_missing()
    if not os.path.isdir(DIRNAME):
        fetch_source()
    else:
        print(f">> Reusing existing {DIRNAME}")
    os.chdir(DIRNAME)
    print(">> Starting server. Open http://127.0.0.1:5000 in Safari.")
    # Hand off to a fresh Python process so newly-installed user-site
    # packages are picked up by sys.path (pip install in the current
    # process does not refresh the running interpreter's module cache).
    os.execv(sys.executable, [sys.executable, "server.py"])


if __name__ == "__main__":
    main()
