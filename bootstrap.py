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


def refresh_user_site() -> None:
    """Add user-site to sys.path so newly-installed wheels become importable
    without spawning a new Python process (iOS a-Shell blocks os.execv)."""
    try:
        import importlib
        import site
        importlib.invalidate_caches()
        user_site = site.getusersitepackages()
        paths = user_site if isinstance(user_site, list) else [user_site]
        for path in paths:
            if path and path not in sys.path:
                sys.path.insert(0, path)
    except Exception:
        pass


def fetch_source() -> None:
    print(f">> Downloading {TARBALL}")
    with urllib.request.urlopen(TARBALL) as response:
        data = response.read()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(".")
    print(f">> Extracted into ./{DIRNAME}")


def main() -> None:
    newly_installed = install_if_missing()
    if newly_installed:
        refresh_user_site()
    if not os.path.isdir(DIRNAME):
        fetch_source()
    else:
        print(f">> Reusing existing {DIRNAME}")
    os.chdir(DIRNAME)
    print(">> Starting server. Open http://127.0.0.1:5000 in Safari.")
    import runpy
    try:
        runpy.run_path("server.py", run_name="__main__")
    except KeyboardInterrupt:
        print(">> Server stopped.")
    except Exception:
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
