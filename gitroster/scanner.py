"""Filesystem scan: git repos, virtual envs, git state, ports."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import deps as depmod
from . import procs

PRUNE = {
    "node_modules", ".cache", ".git", "__pycache__", ".npm", "site-packages",
    ".local", "snap", ".cargo", ".rustup", ".gradle", ".m2", "dist", "build",
    "Library", "AppData", ".Trash", "target", "$RECYCLE.BIN", "Application Data",
}
MAX_DEPTH = 6
GENERIC_NAMES = {"project", "src", "app", "code", "repo", "main", "web", "backend", "frontend"}
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
    info["remotes"] = {}
    for line in run(["git", "-C", str(path), "remote", "-v"], 5).splitlines():
        parts = line.split()
        if len(parts) >= 2:
            info["remotes"].setdefault(parts[0], parts[1])
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


def default_branch(path):
    ref = run(["git", "-C", str(path), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], 5).strip()
    if "/" in ref:
        return ref.split("/", 1)[1]
    for b in ("main", "master"):
        if run(["git", "-C", str(path), "rev-parse", "--verify", "-q", f"refs/heads/{b}"], 5).strip():
            return b
    return ""


def forgotten_work(path):
    """Work that is easy to lose track of: stashes, branches not merged anywhere safe, extra worktrees."""
    p = str(path)
    stashes = []
    for line in run(["git", "-C", p, "stash", "list", "--format=%gd\t%ct\t%gs"], 8).splitlines():
        ref, _, rest = line.partition("\t")
        ts, _, msg = rest.partition("\t")
        stashes.append({"ref": ref, "time": int(ts) if ts.isdigit() else None, "message": msg})
    base = default_branch(path)
    heads = run(["git", "-C", p, "for-each-ref", "refs/heads", "--format=%(refname:short)"], 8).split()
    bases = [b for b in dict.fromkeys([base, "develop", "dev"]) if b and b in heads]  # git-flow repos merge into develop
    unmerged = set(heads) - set(bases)
    for b in bases:
        unmerged &= set(run(["git", "-C", p, "for-each-ref", f"--no-merged={b}", "refs/heads", "--format=%(refname:short)"], 8).split())
    branches, merged = [], 0
    fmt = "%(refname:short)\t%(upstream:short)\t%(upstream:track)\t%(committerdate:unix)\t%(HEAD)"
    for line in run(["git", "-C", p, "for-each-ref", "refs/heads", f"--format={fmt}"], 8).splitlines():
        name, upstream, track, ts, head = (line.split("\t") + [""] * 5)[:5]
        if name in bases:
            continue
        if bases and name not in unmerged:
            merged += 1
            continue
        ahead = re.search(r"ahead (\d+)", track)
        gone = "gone" in track
        state = "local-only" if not upstream or gone or ahead else "unmerged"
        branches.append({"name": name, "state": state, "upstream": upstream, "gone": gone,
                         "ahead": int(ahead.group(1)) if ahead else 0,
                         "time": int(ts) if ts.isdigit() else None, "current": head.strip() == "*"})
    worktrees, block = [], {}
    for line in run(["git", "-C", p, "worktree", "list", "--porcelain"], 8).splitlines() + [""]:
        if line:
            k, _, v = line.partition(" ")
            block[k] = v
        elif block:
            worktrees.append(block)
            block = {}
    extra = [{"path": w.get("worktree", ""), "branch": w.get("branch", "").replace("refs/heads/", ""),
              "missing": "prunable" in w or not os.path.isdir(w.get("worktree", ""))} for w in worktrees[1:]]
    branches.sort(key=lambda b: (b["state"] != "local-only", -(b["time"] or 0)))
    return {"default": base, "stashes": stashes, "branches": branches, "merged_branches": merged, "worktrees": extra}


def graph(path, limit=300):
    """Recent commits of all branches, tags and remotes, newest first, for drawing a commit graph."""
    fmt = "%H%x1f%P%x1f%an%x1f%ct%x1f%D%x1f%s"
    out = run(["git", "-C", str(path), "log", "--topo-order", f"-n{int(limit)}", "--branches", "--tags", "--remotes",
               f"--format={fmt}"], 20)
    commits = []
    for line in out.splitlines():
        h, parents, author, ts, refs, subject = (line.split("\x1f") + [""] * 6)[:6]
        commits.append({"hash": h, "parents": parents.split(), "author": author, "time": int(ts) if ts.isdigit() else None,
                        "refs": [r.strip() for r in refs.split(",") if r.strip()], "subject": subject[:200]})
    return commits


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
    }
    r.update(git_info(p))
    r.update(readme(p))
    d = depmod.collect(p)
    r["pkg"], r["deps"] = d["names"], d["deps"]
    r["work"] = forgotten_work(p)
    r["health"] = health(p)
    r["subprojects"] = subprojects(p)
    r["size"] = dir_size(p)
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


def norm_remote(url):
    """git@github.com:a/b.git, ssh://git@github.com:22/a/b and https://github.com/a/b.git -> github.com/a/b"""
    u = (url or "").strip().lower()
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)(?::\d+)?[:/](.+)$", u)
    if not m:
        return u
    path = re.sub(r"\.git$", "", m.group(2).strip("/"))
    return f"{m.group(1)}/{path}"


def main_remote(r):
    remotes = r.get("remotes", {})
    return remotes.get("origin") or next(iter(remotes.values()), "")


GENERIC_PKGS = {"app", "main", "test", "tests", "src", "lib", "utils", "common", "core", "api", "web", "server", "client"}


def relate(repos):
    """Fill same_remote (copies of one repo), uses / used_by (local packages that depend on each other)."""
    by_remote, by_pkg = {}, {}
    for r in repos:
        key = norm_remote(main_remote(r))
        r["same_remote"] = []
        r["uses"], r["used_by"] = [], []
        if key:
            by_remote.setdefault(key, []).append(r["path"])
        for n in r.get("pkg", []):
            if len(n["name"]) >= 3 and n["name"].lower() not in GENERIC_PKGS:
                by_pkg.setdefault((n["eco"], n["name"].lower()), set()).add(r["path"])
    for r in repos:
        key = norm_remote(main_remote(r))
        r["same_remote"] = [x for x in by_remote.get(key, []) if x != r["path"]] if key else []
        for d in r.get("deps", []):
            for other in by_pkg.get((d["eco"], d["name"].lower()), ()):
                if other != r["path"] and other not in r["uses"]:
                    r["uses"].append(other)
    index = {r["path"]: r for r in repos}
    for r in repos:
        for other in r["uses"]:
            index[other]["used_by"].append(r["path"])


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
    relate(repos)
    ports = procs.listening()
    containers = procs.docker_containers()
    procs.link(ports, containers, repos, envs)
    for r in repos:
        r["ports"] = sorted({p["port"] for p in ports if p["repo"] == r["path"]})
    repos.sort(key=lambda r: (r["tool"], -(r["last_commit"] or 0)))
    return {"roots": roots, "scanned": time.time(), "repos": repos, "envs": envs,
            "ports": ports, "containers": containers}
