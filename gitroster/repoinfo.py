"""Read-only views of a repo: overview, file tree, file contents, commits, search, activity. Nothing here writes."""
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .scanner import run

REF_RE = re.compile(r"^[\w./@{}^~+-]{1,200}$")
HASH_RE = re.compile(r"^[0-9a-f]{4,40}$")
MAX_FILE = 300_000
MAX_DIFF = 200_000

LANGS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".astro": "Astro", ".vue": "Vue", ".svelte": "Svelte",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".swift": "Swift", ".dart": "Dart", ".c": "C", ".h": "C",
    ".cpp": "C++", ".cs": "C#", ".php": "PHP", ".rb": "Ruby", ".sh": "Shell", ".sql": "SQL", ".md": "Markdown",
    ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".ipynb": "Notebook", ".lua": "Lua",
}


def _git(path, *args, timeout=15):
    return run(["git", "-C", str(path), *args], timeout)


def check_ref(ref):
    if not REF_RE.match(ref or "") or ref.startswith("-") or ".." in ref:
        raise ValueError("bad ref")
    return ref


def check_rel(rel):
    rel = (rel or "").strip("/")
    if rel.startswith("-") or ".." in rel.split("/") or "\\" in rel or "\0" in rel:
        raise ValueError("bad path")
    return rel


def overview(path):
    p = Path(path)
    files = [f for f in _git(p, "ls-files", "-z").split("\0") if f]
    langs = {}
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        name = LANGS.get(ext)
        if not name:
            continue
        try:
            size = (p / f).stat().st_size
        except OSError:
            continue
        item = langs.setdefault(name, {"name": name, "files": 0, "bytes": 0})
        item["files"] += 1
        item["bytes"] += size
    languages = sorted(langs.values(), key=lambda x: -x["bytes"])[:8]
    contributors = []
    for line in _git(p, "shortlog", "-sn", "HEAD").splitlines()[:10]:
        n, _, name = line.strip().partition("\t")
        if n.isdigit():
            contributors.append({"name": name, "commits": int(n)})
    tags = []
    for line in _git(p, "tag", "--sort=-creatordate", "--format=%(refname:short)\t%(creatordate:unix)").splitlines()[:12]:
        name, _, ts = line.partition("\t")
        tags.append({"name": name, "time": int(ts) if ts.isdigit() else None})
    total = _git(p, "rev-list", "--count", "HEAD").strip()
    first = _git(p, "log", "--reverse", "--format=%ct", "-n1", "--max-parents=0", "HEAD").strip()
    changed = {}
    for f in _git(p, "log", "-n", "60", "--name-only", "--format=").splitlines():
        if f:
            changed[f] = changed.get(f, 0) + 1
    recent = [{"file": f, "changes": n} for f, n in sorted(changed.items(), key=lambda kv: -kv[1])[:10]]
    readme = ""
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        try:
            readme = (p / name).read_text(encoding="utf-8", errors="replace")[:20000]
            break
        except OSError:
            continue
    return {"languages": languages, "contributors": contributors, "tags": tags, "files_total": len(files),
            "commits_total": int(total) if total.isdigit() else 0, "first_commit": int(first) if first.isdigit() else None,
            "hot_files": recent, "readme": readme}


def tree(path, ref, rel):
    ref, rel = check_ref(ref or "HEAD"), check_rel(rel)
    spec = f"{ref}:{rel}" if rel else ref
    out = _git(path, "ls-tree", "-l", spec)
    entries = []
    for line in out.splitlines():
        meta, _, name = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 4:
            entries.append({"name": name, "type": parts[1], "size": int(parts[3]) if parts[3].isdigit() else None})
    entries.sort(key=lambda e: (e["type"] != "tree", e["name"].lower()))
    return entries


def read_file(path, ref, rel):
    ref, rel = check_ref(ref or "HEAD"), check_rel(rel)
    if not rel:
        raise ValueError("no file")
    try:
        proc = subprocess.run(["git", "-C", str(path), "show", f"{ref}:{rel}"], capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        raise ValueError("could not read file")
    if proc.returncode != 0:
        raise ValueError("file not found at that ref")
    data = proc.stdout
    if b"\0" in data[:8000]:
        return {"binary": True, "size": len(data), "text": ""}
    return {"binary": False, "size": len(data), "truncated": len(data) > MAX_FILE,
            "text": data[:MAX_FILE].decode("utf-8", errors="replace")}


def commit(path, h):
    if not HASH_RE.match(h or ""):
        raise ValueError("bad hash")
    fmt = "%H%x1f%P%x1f%an%x1f%ct%x1f%B"
    out = _git(path, "show", "--no-patch", f"--format={fmt}", h)
    head = (out.split("\x1f") + [""] * 5)[:5]
    files = []
    for line in _git(path, "show", "--format=", "--numstat", "-M", h).splitlines():
        a, _, rest = line.partition("\t")
        d, _, name = rest.partition("\t")
        if name:
            files.append({"file": name, "added": int(a) if a.isdigit() else None, "deleted": int(d) if d.isdigit() else None})
    diff = _git(path, "show", "--format=", "--patch", "--no-color", "-M", h, timeout=20)
    return {"hash": head[0].strip(), "parents": head[1].split(), "author": head[2], "time": int(head[3]) if head[3].isdigit() else None,
            "message": head[4].strip(), "files": files[:300], "diff": diff[:MAX_DIFF], "diff_truncated": len(diff) > MAX_DIFF}


def search_repo(repo, q, scope, regex=False, per=40):
    path = repo["path"]
    res = {"path": path, "name": repo["name"], "code": [], "files": [], "commits": [], "capped": False}
    if "code" in scope:
        cmd = ["git", "-C", path, "grep", "-n", "-I", "-i", "--no-color", "-E" if regex else "-F", "-e", q]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:
                f, _, rest = line.partition(":")
                n, _, text = rest.partition(":")
                if n.isdigit():
                    res["code"].append({"file": f, "line": int(n), "text": text.strip()[:240]})
                if len(res["code"]) >= per:
                    res["capped"] = True
                    proc.kill()
                    break
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if "files" in scope:
        low = q.lower()
        res["files"] = [f for f in _git(path, "ls-files").splitlines() if low in f.lower()][:15]
    if "commits" in scope:
        for line in _git(path, "log", "--branches", "-i", "-F", f"--grep={q}", "-n", "8", "--format=%H%x1f%ct%x1f%s").splitlines():
            h, _, rest = line.partition("\x1f")
            ts, _, subject = rest.partition("\x1f")
            res["commits"].append({"hash": h, "time": int(ts) if ts.isdigit() else None, "subject": subject[:200]})
    return res


def search(repos, q, scope=("code", "files", "commits"), regex=False):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda r: search_repo(r, q, scope, regex), repos))
    return [r for r in results if r["code"] or r["files"] or r["commits"]]


def activity(repos, days=30, mine=False):
    since = f"--since={int(days)}.days.ago"

    def one(r):
        args = ["log", "--branches", since, "-n", "150", "--format=%H%x1f%ct%x1f%an%x1f%s"]
        if mine:
            email = _git(r["path"], "config", "user.email").strip()
            if not email:
                return []
            args.append(f"--author={email}")
        out = []
        for line in _git(r["path"], *args).splitlines():
            h, ts, author, subject = (line.split("\x1f") + [""] * 4)[:4]
            if ts.isdigit():
                out.append({"repo": r["path"], "name": r["name"], "hash": h, "time": int(ts), "author": author, "subject": subject[:200]})
        return out

    with ThreadPoolExecutor(8) as ex:
        rows = [c for chunk in ex.map(one, repos) for c in chunk]
    rows.sort(key=lambda c: -c["time"])
    return rows[:1500]
