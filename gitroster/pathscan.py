"""Find programs on PATH quickly.

shutil.which stats every command in every PATH folder, which takes seconds on WSL where the
Windows folders are on a slow mount. Listing each folder once and looking names up is much faster.
"""
import os
import sys
import time

WIN = sys.platform == "win32"
_index = {"at": 0.0, "map": {}}


def index():
    if not _index["map"] or time.time() - _index["at"] > 60:
        found = {}
        for d in os.environ.get("PATH", "").split(os.pathsep):
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                full = os.path.join(d, n)
                found.setdefault(n, full)
                stem, ext = os.path.splitext(n)
                if WIN and ext.lower() in (".exe", ".cmd", ".bat", ".com"):
                    found.setdefault(stem.lower(), full)
        _index.update(at=time.time(), map=found)
    return _index["map"]


def which(cmd):
    path = index().get(cmd) or (index().get(cmd.lower()) if WIN else None)
    return path if path and os.path.isfile(path) and os.access(path, os.X_OK) else None
