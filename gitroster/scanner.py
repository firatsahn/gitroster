"""Filesystem scan: git repos, virtual envs, reclaimable folders, big files."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import procs

PRUNE = {
    "node_modules", ".cache", ".git", "__pycache__", ".npm", "site-packages",
    ".local", "snap", ".cargo", ".rustup", ".gradle", ".m2", "dist", "build",
    "Library", "AppData", ".Trash", "target", "$RECYCLE.BIN", "Application Data",
}
MAX_DEPTH = 6
GENERIC_NAMES = {"project", "src", "app", "code", "repo", "main", "web", "backend", "frontend"}
RECLAIMABLE = ["node_modules", ".next", ".nuxt", ".turbo", ".parcel-cache", "dist", "build"]
BIG_FILE = 50 * 1024 * 1024
VENV_NAMES = (".venv", "venv", "env")
WIN = sys.platform == "win32"
BIN = "Scripts" if WIN else "bin"
PY = "python" if WIN else "python3"
SEP = "\\" if WIN else "/"
ENTRY_FILES = ("main.py", "app.py", "run.py", "server.py")


def run(cmd, timeout=10, cwd=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=cwd).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def read(path, limit=6000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def walk_size(path, deadline):
    total = 0
    stack = [str(path)]
    while stack:
        if time.time() > deadline:
            return None
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir():
                            stack.append(e.path)
                        else:
                            total += e.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def dir_size(path, timeout=20):
    if shutil.which("du"):
        out = run(["du", "-sk", str(path)], timeout)
        try:
            return int(out.split()[0]) * 1024
        except (IndexError, ValueError):
            return None
    return walk_size(path, time.time() + timeout)  # Windows has no du


def walk(roots):
    """Return (repos, envs). repos: [(Path, is_tool)], envs: [(Path, kind)]."""
    repos, envs, seen = [], [], set()
    for root in roots:
        root = Path(root).expanduser().resolve()
        base = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            p = Path(dirpath)
            if len(p.parts) - base >= MAX_DEPTH:
                dirs[:] = []
                continue
            kind = "venv" if "pyvenv.cfg" in files else "conda" if "conda-meta" in dirs else None
            if kind:
                if p not in seen:
                    seen.add(p)
                    envs.append((p, kind))
                dirs[:] = []
                continue
            if (".git" in dirs or ".git" in files) and p not in seen:
                seen.add(p)
                rel = p.relative_to(root).parts
                tool = bool(rel) and rel[0].startswith(".")
                repos.append((p, tool))
                if tool:
                    dirs[:] = []
                    continue
            dirs[:] = [d for d in dirs if d not in PRUNE and not (d.startswith(".") and d not in VENV_NAMES)]
    return repos, envs


def git_info(path):
    info = {"branch": "", "dirty": False, "ahead": 0, "behind": 0, "remote": "", "last_commit": None}
    out = run(["git", "-C", str(path), "status", "--porcelain=v1", "-b"], 8).splitlines()
    if out:
        m = re.match(r"## (?:No commits yet on |Initial commit on )?(.+?)(?:\.\.\.| \[|$)", out[0])
        info["branch"] = m.group(1) if m else ""
        a = re.search(r"ahead (\d+)", out[0])
        b = re.search(r"behind (\d+)", out[0])
        info["ahead"], info["behind"] = int(a.group(1)) if a else 0, int(b.group(1)) if b else 0
        info["dirty"] = len(out) > 1
    info["remote"] = run(["git", "-C", str(path), "remote", "get-url", "origin"], 5).strip()
    last = run(["git", "-C", str(path), "log", "-1", "--format=%ct"], 5).strip()
    info["last_commit"] = int(last) if last.isdigit() else None
    info["kind"] = repo_kind(path, info["remote"])
    return info


def repo_kind(path, origin):
    """local (no remote) / fork (has an upstream remote) / mine (you authored commits) / clone."""
    remotes = run(["git", "-C", str(path), "remote"], 5).split()
    if not remotes:
        return "local"
    if "upstream" in remotes:
        return "fork"
    email = run(["git", "-C", str(path), "config", "user.email"], 5).strip()
    if email and run(["git", "-C", str(path), "log", "-1", "--fixed-strings", f"--author={email}", "--format=%H"], 8).strip():
        return "mine"
    return "clone"


def readme(path):
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        text = read(Path(path) / name, 20000)
        if text:
            lines = [l.strip() for l in text.splitlines()]
            title = next((l.lstrip("# ").strip() for l in lines if l.startswith("#")), "")
            para = next((l for l in lines if len(l) > 30 and not l.startswith(("#", "!", "[", "<", "`", "|", "-", "=", "*"))), "")
            cmds = []
            for block in re.findall(r"```(?:bash|sh|shell|console|zsh)?\n(.*?)```", text, re.S):
                for line in block.splitlines():
                    line = line.strip().lstrip("$ ").strip()
                    if re.match(r"(python3?|npm|npx|pnpm|yarn|docker|uv|pip3?|make|cargo|go|bash|\./)\b", line) and len(line) < 120:
                        cmds.append(line)
            ports = sorted({int(x) for x in re.findall(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})", text)})[:4]
            return {"title": title, "summary": para[:220], "cmds": list(dict.fromkeys(cmds))[:5], "expected_ports": ports}
    return {"title": "", "summary": "", "cmds": [], "expected_ports": []}


def detect(path):
    """Deterministic stack + command detection. `{py}` marks the Python to use."""
    p = Path(path)
    stack, setup, runs = [], [], []
    if (p / "package.json").exists():
        stack.append("node")
        pm = "pnpm" if (p / "pnpm-lock.yaml").exists() else "yarn" if (p / "yarn.lock").exists() else "npm"
        if not (p / "node_modules").exists():
            setup.append(f"{pm} install")
        try:
            scripts = json.loads(read(p / "package.json", 200000)).get("scripts", {})
        except ValueError:
            scripts = {}
        for k in ("dev", "start", "serve", "preview"):
            if k in scripts and re.fullmatch(r"[\w:.-]+", k):
                runs.append(f"{pm} run {k}")
    if any((p / f).exists() for f in ("pyproject.toml", "requirements.txt", "setup.py", "Pipfile")):
        stack.append("python")
    if (p / "manage.py").exists():
        runs.append("{py} manage.py runserver")
    for entry in ENTRY_FILES:
        if (p / entry).exists():
            runs.append("{py} " + entry)
            break
    if (p / "Cargo.toml").exists():
        stack.append("rust")
        runs.append("cargo run")
    if (p / "go.mod").exists():
        stack.append("go")
        runs.append("go run .")
    if (p / "pubspec.yaml").exists():
        stack.append("flutter")
        runs.append("flutter run")
    if (p / "Makefile").exists():
        stack.append("make")
        for t in re.findall(r"^([a-zA-Z][\w-]*):", read(p / "Makefile"), re.M):
            if t in ("run", "dev", "start", "serve"):
                runs.append(f"make {t}")
    if any((p / f).exists() for f in ("docker-compose.yml", "compose.yaml", "docker-compose.yaml", "compose.yml")):
        stack.append("docker")
        runs.append("docker compose up")
    if any((p / f).exists() for f in ("wrangler.toml", "wrangler.jsonc", "wrangler.json")):
        stack.append("cloudflare")
        runs.append("npx wrangler dev")
    return stack, setup, list(dict.fromkeys(runs))


def find_reclaimables(path):
    p = Path(path)
    return [{"path": str(p / n), "kind": n} for n in RECLAIMABLE if (p / n).is_dir()]


def big_files(path, limit=5):
    found, total = [], 0
    for dirpath, dirs, files in os.walk(path):
        if "pyvenv.cfg" in files or "conda-meta" in dirs:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for f in files:
            fp = os.path.join(dirpath, f)
            try:
                st = os.lstat(fp)
            except OSError:
                continue
            if st.st_size >= BIG_FILE and not os.path.islink(fp):
                total += st.st_size
                found.append((st.st_size, os.path.relpath(fp, path)))
    found.sort(reverse=True)
    return total, [{"path": f, "size": s} for s, f in found[:limit]]


SECRET_FILES = re.compile(r"(^|/)(\.env(\.(?!example|sample|template)[\w.-]+)?|id_rsa|id_ed25519|[^/]+\.(pem|key|p12|pfx))$")


def ignored(path, name):
    return subprocess.run(["git", "-C", str(path), "check-ignore", "-q", name], capture_output=True).returncode == 0


def health(path):
    """Cheap local checks, no network: secrets that git tracks, .env files nobody ignores."""
    p, issues = Path(path), []
    tracked = run(["git", "-C", str(p), "ls-files"], 10).splitlines()
    leaked = [f for f in tracked if SECRET_FILES.search(f)]
    if leaked:
        issues.append({"kind": "tracked-secret", "text": "secret-looking files are tracked by git", "files": leaked[:5]})
    loose = [f for f in (".env", ".env.local") if (p / f).is_file() and f not in tracked and not ignored(p, f)]
    if loose:
        issues.append({"kind": "unignored-env", "text": ".env exists but is not in .gitignore", "files": loose})
    if tracked and not (p / ".gitignore").exists() and any(x in detect(p)[0] for x in ("node", "python")):
        issues.append({"kind": "no-gitignore", "text": "no .gitignore", "files": []})
    return issues


def subprojects(path, limit=8):
    """Projects living in subfolders of a repo (monorepos, nested apps)."""
    found = []
    try:
        dirs = sorted(d for d in Path(path).iterdir() if d.is_dir())
    except OSError:
        return found
    for d in dirs:
        if d.name in PRUNE or d.name.startswith("."):
            continue
        stack, _, runs = detect(d)
        if not stack:
            continue
        if runs:
            found.append({"path": str(d), "name": d.name, "stack": stack, "run": runs})
    return found[:limit]


def env_python_version(v):
    m = re.search(r"^version(?:_info)?\s*=\s*(\S+)", read(Path(v) / "pyvenv.cfg"), re.M)
    return m.group(1) if m else ""


def display_name(p):
    return f"{p.parent.name}/{p.name}" if p.name.lower() in GENERIC_NAMES else p.name


def analyze_repo(p, tool):
    p = Path(p)
    stack, setup, runs = detect(p)
    r = {
        "name": display_name(p), "path": str(p), "tool": tool,
        "stack": stack, "setup": setup, "run": runs, "envs": [], "ports": [],
        "reclaimable": find_reclaimables(p),
    }
    r.update(git_info(p))
    r.update(readme(p))
    r["health"] = health(p)
    r["subprojects"] = subprojects(p)
    r["size"] = dir_size(p)
    r["big_total"], r["big_files"] = big_files(p)
    for item in r["reclaimable"]:
        item["size"] = dir_size(item["path"], 15)
    return r


def owner(path, items):
    """Item with the longest `path` that contains `path`."""
    best = None
    for c in items:
        cp = c["path"]
        if path == cp or path.startswith(cp + os.sep):
            if best is None or len(cp) > len(best["path"]):
                best = c
    return best


def install_cmds(path):
    """Commands that rebuild what `park` removes (deps, venv)."""
    p, cmds = Path(path), []
    if (p / "package.json").exists():
        pm = "pnpm" if (p / "pnpm-lock.yaml").exists() else "yarn" if (p / "yarn.lock").exists() else "npm"
        cmds.append(f"{pm} install")
    pip = f".venv{SEP}{BIN}{SEP}pip"
    if (p / "requirements.txt").exists():
        cmds += [f"{PY} -m venv .venv", f"{pip} install -r requirements.txt"]
    elif (p / "pyproject.toml").exists():
        cmds += [f"{PY} -m venv .venv", f"{pip} install -e ."]
    return cmds


def finalize(repo):
    """Fill in `{py}` and Python setup steps once envs are linked."""
    py = PY
    venvs = [e for e in repo["envs"] if e["kind"] == "venv"]
    if venvs:
        v = venvs[0]["path"]
        inside = v.startswith(repo["path"] + os.sep)
        v = os.path.relpath(v, repo["path"]) if inside else v
        py = f"{v}{SEP}{BIN}{SEP}python"
        repo["activate"] = f"{v}{SEP}{BIN}{SEP}activate" if WIN else f"source {v}/bin/activate"
    elif "python" in repo["stack"]:
        repo["setup"].insert(0, f"{PY} -m venv .venv")
        pip = f".venv{SEP}{BIN}{SEP}pip"
        p = Path(repo["path"])
        if (p / "requirements.txt").exists():
            repo["setup"].append(f"{pip} install -r requirements.txt")
        elif (p / "pyproject.toml").exists():
            repo["setup"].append(f"{pip} install -e .")
    repo["run"] = [c.replace("{py}", py) for c in repo["run"]]
    repo["restore"] = install_cmds(repo["path"])


def parkable(repo):
    """Folders `park` may remove: envs and build folders inside the repo, never tracked by git."""
    root, out = repo["path"], []
    for item in [*repo["reclaimable"], *repo["envs"]]:
        path = item["path"]
        if not path.startswith(root + os.sep) or os.path.islink(path) or not os.path.isdir(path):
            continue
        if run(["git", "-C", root, "ls-files", "--", path], 10).strip():
            continue
        out.append({"path": path, "kind": item.get("kind", ""), "size": item.get("size")})
    return out


def park(repo, today=None):
    """Delete the parkable folders. Returns (removed paths, restore text for the note)."""
    removed = []
    for item in parkable(repo):
        shutil.rmtree(item["path"])
        removed.append(item["path"])
    names = ", ".join(os.path.relpath(x, repo["path"]) for x in removed)
    text = f"Parked {today or time.strftime('%Y-%m-%d')} (removed {names or 'nothing'})."
    if repo.get("restore"):
        text += " To restore: " + " && ".join(repo["restore"])
    return removed, text


def scan(roots, progress=None):
    roots = [str(Path(r).expanduser()) for r in roots]
    repo_paths, env_paths = walk(roots)
    with ThreadPoolExecutor(8) as ex:
        repos = list(ex.map(lambda rp: analyze_repo(*rp), repo_paths))
        envs = [{"path": str(p), "name": p.name, "kind": k, "python": env_python_version(p) if k == "venv" else "", "repo": None}
                for p, k in env_paths]
        for e, s in zip(envs, ex.map(lambda e: dir_size(e["path"]), envs)):
            e["size"] = s
    for e in envs:
        o = owner(e["path"], repos)
        if o:
            e["repo"] = o["path"]
            o["envs"].append(e)
    for r in repos:
        finalize(r)
    ports = procs.listening()
    containers = procs.docker_containers()
    procs.link(ports, containers, repos, envs)
    for r in repos:
        r["ports"] = sorted({p["port"] for p in ports if p["repo"] == r["path"]})
    repos.sort(key=lambda r: (r["tool"], -(r["last_commit"] or 0)))
    return {"roots": roots, "scanned": time.time(), "repos": repos, "envs": envs,
            "ports": ports, "containers": containers}
