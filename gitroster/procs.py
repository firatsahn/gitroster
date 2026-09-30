"""Listening ports, their processes, and Docker containers (Linux / WSL)."""
import json
import os
import re
import subprocess
from pathlib import Path


def _run(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def listening():
    """Every listening TCP port owned by the current user."""
    res = []
    for line in _run(["ss", "-ltnpH"]).splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        host, _, port = parts[3].rpartition(":")
        m = re.search(r'\("([^"]*)",pid=(\d+)', line)
        if not m:
            continue
        pid = int(m.group(2))
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            since = os.stat(f"/proc/{pid}").st_mtime
        except OSError:
            cwd, cmd, since = "", "", 0
        res.append({
            "port": int(port), "host": host.strip("[]"), "pid": pid, "proc": m.group(1),
            "cmd": cmd[:240], "cwd": cwd, "since": since, "repo": None,
            "exposed": host.strip("[]") in ("0.0.0.0", "*", "::"),
        })
    return sorted(res, key=lambda r: r["port"])


def docker_containers():
    out = _run(["docker", "ps", "--format", "{{json .}}"], 5)
    res = []
    for line in out.splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        wd = re.search(r"com\.docker\.compose\.project\.working_dir=([^,]+)", c.get("Labels", ""))
        res.append({"name": c.get("Names", ""), "image": c.get("Image", ""), "ports": c.get("Ports", ""),
                    "status": c.get("Status", ""), "workdir": wd.group(1) if wd else "", "repo": None})
    return res


def _owner(path, items):
    best = None
    for c in items:
        cp = c["path"]
        if path == cp or path.startswith(cp + os.sep):
            if best is None or len(cp) > len(best["path"]):
                best = c
    return best


def link(ports, containers, repos, envs):
    """Attach each port/container to a repo: by cwd, then by paths in the command line."""
    for pt in ports:
        o = _owner(pt["cwd"], repos) if pt["cwd"] else None
        if not o:
            for e in sorted(envs, key=lambda e: -len(e["path"])):
                if e["path"] in pt["cmd"]:
                    o = _owner(e["path"], repos)
                    break
        if not o:
            for r in sorted(repos, key=lambda r: -len(r["path"])):
                if r["path"] in pt["cmd"]:
                    o = r
                    break
        pt["repo"] = o["path"] if o else None
    for c in containers:
        o = _owner(c["workdir"], repos) if c["workdir"] else None
        c["repo"] = o["path"] if o else None
