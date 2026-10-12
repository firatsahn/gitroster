"""`gitroster --demo`: a throwaway set of sample repos, so the UI can be tried or photographed without
scanning a real machine. Nothing here touches your own folders, settings or processes."""
import atexit
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import procs
from .store import Store

DAY = 86400
ME = ("Demo User", "demo@example.com")

# name, remote, files, [(days ago, message)], extra setup name
REPOS = [
    ("atlas-api", "https://github.com/demo-user/atlas-api.git", {
        "README.md": "# Atlas API\n\nA small REST API that serves product data for the storefront.\n\n```bash\nnpm run dev\n```\n\nOpen http://localhost:3000\n",
        "package.json": '{"name":"atlas-api","scripts":{"dev":"node server.js","start":"node server.js"},"dependencies":{"express":"^4.19.0","zod":"^3.23.0"}}',
        ".gitignore": "node_modules\n.env\n",
        "server.js": "require('express')().listen(3000)\n"},
     [(40, "Add product schema"), (9, "Validate query params"), (2, "Cache product list")], "ahead"),
    ("bookshelf", "https://github.com/demo-user/bookshelf.git", {
        "README.md": "# Bookshelf\n\nTrack the books you read and what you thought of them.\n",
        "requirements.txt": "flask==3.0.3\nsqlalchemy==2.0.30\n",
        "app.py": "print('bookshelf')\n",
        ".gitignore": ".venv\n"},
     [(120, "First version"), (30, "Add ratings"), (5, "Import from CSV")], "work"),
    ("dashboard-ui", "https://github.com/demo-user/dashboard-ui.git", {
        "README.md": "# Dashboard UI\n\nFront end for the Atlas API, built with Vite.\n\nRuns on http://localhost:5173\n",
        "package.json": '{"name":"dashboard-ui","scripts":{"dev":"vite"},"dependencies":{"vite":"^5.2.0","zod":"^3.22.0"}}',
        ".gitignore": "node_modules\n"},
     [(60, "Scaffold with Vite"), (3, "Add chart panel")], None),
    ("rust-notes", "https://github.com/someone/rust-notes.git", {
        "README.md": "# rust-notes\n\nA command line notebook written in Rust.\n",
        "Cargo.toml": '[package]\nname = "rust-notes"\nversion = "0.3.0"\n\n[dependencies]\nclap = "4"\n',
        ".gitignore": "target\n"},
     [(300, "Release 0.3.0")], "clone"),
    ("weather-cli", "https://github.com/demo-user/weather-cli.git", {
        "README.md": "# weather-cli\n\nPrints the weather forecast in your terminal. Forked to add metric units.\n",
        "go.mod": "module example.com/weather\n\ngo 1.22\n",
        "main.go": "package main\nfunc main() {}\n"},
     [(210, "Fork upstream"), (190, "Add metric units")], "fork"),
    ("old-experiment", None, {
        "README.md": "# old experiment\n\nSomething I tried with a camera feed and never finished.\n",
        "main.py": "print('todo')\n",
        "requirements.txt": "opencv-python\n",
        ".env": "CAMERA_KEY=demo\n"},
     [(480, "wip"), (470, "wip 2")], "dirty"),
]

SUMMARIES = {
    "atlas-api": {
        "what": "REST API that serves product data to the storefront.",
        "stack": "Node.js, Express, Zod",
        "run": "npm run dev, then open http://localhost:3000",
        "status": "Active. The last work added caching for the product list.",
        "watch": "Two commits are not pushed yet.",
    },
    "bookshelf": {
        "what": "Small web app to track the books you read, with ratings and CSV import.",
        "stack": "Python, Flask, SQLAlchemy",
        "run": "python3 -m venv .venv, install requirements.txt, then python3 app.py",
        "status": "Was working on CSV import: there are uncommitted changes and a stash.",
        "watch": "Check the stash before starting something new.",
    },
}

NOTES = {"bookshelf": "Finish the CSV import, then deploy to the home server."}

PORTS = [("atlas-api", 3000, "node server.js", "node"), ("dashboard-ui", 5173, "node node_modules/.bin/vite", "node")]


def _git(path, *args, when=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": ME[0], "GIT_AUTHOR_EMAIL": ME[1],
           "GIT_COMMITTER_NAME": ME[0], "GIT_COMMITTER_EMAIL": ME[1]}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{int(when)} +0000"
    subprocess.run(["git", "-C", str(path), "-c", "commit.gpgsign=false", *args], env=env, check=True, capture_output=True)


def _build(root, name, remote, files, commits, extra):
    p = Path(root) / name
    p.mkdir(parents=True)
    _git(p, "init", "-q", "-b", "main")
    _git(p, "config", "user.email", ME[1])
    _git(p, "config", "user.name", ME[0])
    for f, content in files.items():
        (p / f).write_text(content)
    now = time.time()
    for i, (days, msg) in enumerate(commits):
        (p / "CHANGELOG.txt").write_text("\n".join(m for _, m in commits[: i + 1]) + "\n")
        _git(p, "add", "-A", "-f")
        _git(p, "commit", "-q", "-m", msg, when=now - days * DAY)
    if remote:
        _git(p, "remote", "add", "origin", remote)
        if extra == "clone":  # the commits are not yours: your configured email no longer matches the author
            _git(p, "config", "user.email", "me@example.org")
        if extra == "fork":
            _git(p, "remote", "add", "upstream", "https://github.com/original/weather-cli.git")
        _git(p, "update-ref", "refs/remotes/origin/main", "HEAD~2" if extra == "ahead" else "HEAD")
        _git(p, "config", "branch.main.remote", "origin")
        _git(p, "config", "branch.main.merge", "refs/heads/main")
    if extra == "work":
        _git(p, "checkout", "-q", "-b", "csv-import")
        (p / "importer.py").write_text("def load(path):\n    pass\n")
        _git(p, "add", "-A")
        _git(p, "commit", "-q", "-m", "Start CSV importer", when=now - 5 * DAY)
        _git(p, "checkout", "-q", "main")
        (p / "scratch.py").write_text("print('try')\n")
        _git(p, "add", "-A")
        _git(p, "stash", "-q")
        (p / "app.py").write_text("print('bookshelf, edited')\n")
    if extra == "dirty":
        (p / "main.py").write_text("print('half done')\n")
    return p


def setup():
    """Create the sample repos, fake the port list, and return (roots, store)."""
    base = Path(tempfile.mkdtemp(prefix="gitroster-demo-")).resolve()
    atexit.register(shutil.rmtree, base, ignore_errors=True)
    root = base / "projects"
    paths = {}
    for name, remote, files, commits, extra in REPOS:
        paths[name] = _build(root, name, remote, files, commits, extra)
    store = Store(base / "config", base / "state")  # state.parent is `base`, which the page shows as ~
    for name, summary in SUMMARIES.items():
        head = subprocess.run(["git", "-C", str(paths[name]), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        store.update_meta(str(paths[name].resolve()), summary={**summary, "agent": "Demo", "head": head, "at": time.time() - 3600})
    for name, note in NOTES.items():
        store.update_meta(str(paths[name].resolve()), note=note)
    store.update_meta(str(paths["atlas-api"].resolve()), pinned=True)
    ports = [dict(procs._entry(port, "127.0.0.1", 40000 + i, proc, cmd, str(paths[name].resolve()), time.time() - 7200))
             for i, (name, port, cmd, proc) in enumerate(PORTS)]
    procs.listening = lambda: [dict(p) for p in ports]  # never read the real machine's ports
    procs.docker_containers = lambda: []
    return [str(root)], store
