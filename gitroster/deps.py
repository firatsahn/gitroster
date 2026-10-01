"""Read dependency manifests (npm, PyPI, Go, Cargo, Composer). Parsers are small and forgiving on purpose."""
import json
import os
import re
from pathlib import Path

MAX_DEPS = 500
PRUNE = {"node_modules", ".git", "__pycache__", "vendor", "dist", "build", "target", ".venv", "venv", "env"}
REQ_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;#]*)")
STR_RE = re.compile(r"""["']([^"']+)["']""")


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:400000]
    except OSError:
        return ""


def _norm_py(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _req(line):
    m = REQ_RE.match(line.strip())
    return (_norm_py(m.group(1)), m.group(2).strip()) if m else None


def _toml_sections(text):
    sections, cur = {}, ""
    for line in text.splitlines():
        m = re.match(r"^\s*\[{1,2}([^\]]+)\]{1,2}\s*$", line)
        if m:
            cur = m.group(1).strip()
            sections.setdefault(cur, [])
        elif cur is not None:
            sections.setdefault(cur, []).append(line)
    return sections


def _toml_value(v):
    v = v.strip()
    m = re.match(r"""^["']([^"']*)["']""", v)
    if m:
        return m.group(1)
    m = re.search(r"""version\s*=\s*["']([^"']*)["']""", v)
    return m.group(1) if m else "*"


def _toml_table_deps(lines, eco, dev, skip=()):
    out = []
    for line in lines:
        m = re.match(r"""^\s*["']?([A-Za-z0-9_.-]+)["']?\s*=\s*(.+)$""", line)
        if m and m.group(1) not in skip:
            out.append({"name": _norm_py(m.group(1)) if eco == "pypi" else m.group(1), "spec": _toml_value(m.group(2)), "eco": eco, "dev": dev})
    return out


def _toml_array(lines, key):
    """Strings of `key = [ ... ]` (one or many lines)."""
    out, collecting = [], False
    for line in lines:
        if not collecting:
            m = re.match(rf"^\s*{re.escape(key)}\s*=\s*\[(.*)$", line)
            if not m:
                continue
            collecting, line = True, m.group(1)
        out += STR_RE.findall(line)
        if "]" in re.sub(r"\"[^\"]*\"|'[^']*'", "", line):  # a `]` outside quotes closes the array
            collecting = False
    return out


def pyproject(text):
    sec = _toml_sections(text)
    name, deps = "", []
    project = sec.get("project", [])
    for line in project:
        m = re.match(r"""^\s*name\s*=\s*["']([^"']+)["']""", line)
        if m:
            name = _norm_py(m.group(1))
    for s in _toml_array(project, "dependencies"):
        r = _req(s)
        if r:
            deps.append({"name": r[0], "spec": r[1], "eco": "pypi", "dev": False})
    optional = sec.get("project.optional-dependencies", [])
    for group in re.findall(r"^\s*([\w-]+)\s*=\s*\[", "\n".join(optional), re.M):
        for s_ in _toml_array(optional, group):
            r = _req(s_)
            if r:
                deps.append({"name": r[0], "spec": r[1], "eco": "pypi", "dev": True})
    if "tool.poetry" in sec and not name:
        for line in sec["tool.poetry"]:
            m = re.match(r"""^\s*name\s*=\s*["']([^"']+)["']""", line)
            if m:
                name = _norm_py(m.group(1))
    deps += _toml_table_deps(sec.get("tool.poetry.dependencies", []), "pypi", False, skip=("python",))
    for key in ("tool.poetry.dev-dependencies", "tool.poetry.group.dev.dependencies"):
        deps += _toml_table_deps(sec.get(key, []), "pypi", True)
    return name, deps


def requirements(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "git+", "http")):
            continue
        r = _req(line)
        if r:
            out.append({"name": r[0], "spec": r[1], "eco": "pypi", "dev": False})
    return out


def package_json(text):
    try:
        data = json.loads(text)
    except ValueError:
        return "", []
    if not isinstance(data, dict):
        return "", []
    out = []
    for key, dev in (("dependencies", False), ("devDependencies", True)):
        for k, v in (data.get(key) or {}).items():
            out.append({"name": k, "spec": str(v), "eco": "npm", "dev": dev})
    return str(data.get("name") or ""), out


def composer_json(text):
    try:
        data = json.loads(text)
    except ValueError:
        return "", []
    if not isinstance(data, dict):
        return "", []
    out = []
    for key, dev in (("require", False), ("require-dev", True)):
        for k, v in (data.get(key) or {}).items():
            if "/" in k:
                out.append({"name": k, "spec": str(v), "eco": "composer", "dev": dev})
    return str(data.get("name") or ""), out


def go_mod(text):
    name, out, block = "", [], False
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        m = re.match(r"^module\s+(\S+)", line)
        if m:
            name = m.group(1)
        elif re.match(r"^require\s*\($", line):
            block = True
        elif block and line == ")":
            block = False
        else:
            m = re.match(r"^(?:require\s+)?(\S+)\s+(v\S+)$", line) if (block or line.startswith("require ")) else None
            if m:
                out.append({"name": m.group(1), "spec": m.group(2), "eco": "go", "dev": False})
    return name, out


def cargo(text):
    sec = _toml_sections(text)
    name = ""
    for line in sec.get("package", []):
        m = re.match(r"""^\s*name\s*=\s*["']([^"']+)["']""", line)
        if m:
            name = m.group(1)
    out = _toml_table_deps(sec.get("dependencies", []), "cargo", False)
    out += _toml_table_deps(sec.get("dev-dependencies", []), "cargo", True)
    out += _toml_table_deps(sec.get("build-dependencies", []), "cargo", True)
    return name, out


def _manifests(d):
    """(names, deps) for one folder."""
    names, deps = [], []
    for fname, fn, eco in (("package.json", package_json, "npm"), ("composer.json", composer_json, "composer"),
                           ("go.mod", go_mod, "go"), ("Cargo.toml", cargo, "cargo"), ("pyproject.toml", pyproject, "pypi")):
        text = _read(d / fname)
        if text:
            n, dd = fn(text)
            if n:
                names.append({"eco": eco, "name": n})
            deps += dd
    seen = {(x["name"]) for x in deps if x["eco"] == "pypi"}
    for f in sorted(d.glob("requirements*.txt"))[:4]:
        dev = "dev" in f.name or "test" in f.name
        for x in requirements(_read(f)):
            if x["name"] not in seen:
                seen.add(x["name"])
                x["dev"] = dev
                deps.append(x)
    return names, deps


def collect(path):
    """Dependencies of a repo: its root and immediate subfolders that have a manifest."""
    root = Path(path)
    names, deps = _manifests(root)
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in PRUNE and not p.name.startswith(".")) if root.is_dir() else []:
        n, dd = _manifests(d)
        names += n
        for x in dd:
            x["where"] = d.name
        deps += dd
    return {"names": names, "deps": deps[:MAX_DEPS]}
