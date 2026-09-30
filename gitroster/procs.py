"""Listening ports, their processes, and Docker containers (Linux, macOS, Windows)."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
EXPOSED = ("0.0.0.0", "*", "::")


def _run(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _entry(port, host, pid, name, cmd, cwd, since):
    host = host.strip("[]")
    return {"port": int(port), "host": host, "pid": int(pid), "proc": name, "cmd": cmd[:240], "cwd": cwd,
            "since": since, "repo": None, "exposed": host in EXPOSED}


def _dedupe(rows):
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["port"], r["pid"])):
        if (r["port"], r["pid"]) not in seen:
            seen.add((r["port"], r["pid"]))
            out.append(r)
    return out


# ---- Linux -----------------------------------------------------------------

def parse_ss(text):
    """-> [(host, port, pid, name)] from `ss -ltnpH`."""
    res = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        host, _, port = parts[3].rpartition(":")
        m = re.search(r'\("([^"]*)",pid=(\d+)', line)
        if m and port.isdigit():
            res.append((host, port, m.group(2), m.group(1)))
    return res


def _linux():
    res = []
    for host, port, pid, name in parse_ss(_run(["ss", "-ltnpH"])):
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            since = os.stat(f"/proc/{pid}").st_mtime
        except OSError:
            cwd, cmd, since = "", "", 0
        res.append(_entry(port, host, pid, name, cmd, cwd, since))
    return res


# ---- macOS -----------------------------------------------------------------

def parse_lsof(text):
    """-> [(host, port, pid, name)] from `lsof -nP -iTCP -sTCP:LISTEN`."""
    res = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        m = re.search(r"(\S+):(\d+) \(LISTEN\)", line)
        if len(parts) > 8 and m and parts[1].isdigit():
            res.append((m.group(1), m.group(2), parts[1], parts[0].replace("\\x20", " ")))
    return res


def _mac():
    res = []
    for host, port, pid, name in parse_lsof(_run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])):
        cwd = next((l[1:] for l in _run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"]).splitlines() if l.startswith("n")), "")
        cmd = _run(["ps", "-o", "command=", "-p", pid]).strip()
        started = _run(["ps", "-o", "lstart=", "-p", pid]).strip()
        try:
            since = time.mktime(time.strptime(started, "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            since = 0
        res.append(_entry(port, host, pid, name, cmd, cwd, since))
    return res


# ---- Windows ---------------------------------------------------------------

def parse_netstat(text):
    """-> [(host, port, pid)] from `netstat -ano -p TCP` (LISTENING rows)."""
    res = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3].upper() == "LISTENING" and parts[4].isdigit():
            host, _, port = parts[1].rpartition(":")
            if port.isdigit():
                res.append((host, port, parts[4]))
    return res


PS_PROCS = ("Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{p=$_.ProcessId; n=$_.Name; "
            "c=$_.CommandLine; t=[DateTimeOffset]$_.CreationDate | ForEach-Object { $_.ToUnixTimeSeconds() }} } "
            "| ConvertTo-Json -Compress")


def parse_ps_procs(text):
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return {}
    data = [data] if isinstance(data, dict) else data
    return {int(d["p"]): d for d in data if isinstance(d, dict) and d.get("p") is not None}


def _windows():
    rows = parse_netstat(_run(["netstat", "-ano", "-p", "TCP"]))
    info = parse_ps_procs(_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_PROCS], 15)) if rows else {}
    res = []
    for host, port, pid in rows:
        d = info.get(int(pid), {})
        name = (d.get("n") or "").removesuffix(".exe")
        res.append(_entry(port, host, pid, name, d.get("c") or "", "", d.get("t") or 0))
    return res


def listening():
    """Every listening TCP port we can attribute to a process."""
    return _dedupe(_windows() if WIN else _mac() if MAC else _linux())


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
