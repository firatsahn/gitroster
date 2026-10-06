"""Open a repo in an editor, a terminal or the file manager (Linux, macOS, Windows, WSL).

Editors and terminals are detected on this machine; the user picks one in Settings.
"""
import glob
import os
import shlex
import shutil
import subprocess
import threading
import sys
import time

from .pathscan import which

WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
WSL = bool(os.environ.get("WSL_DISTRO_NAME"))
HOME = os.path.expanduser("~")

# id, label, commands on PATH, macOS app name
EDITORS = [
    ("code", "VS Code", ["code"], "Visual Studio Code"),
    ("cursor", "Cursor", ["cursor"], "Cursor"),
    ("windsurf", "Windsurf", ["windsurf"], "Windsurf"),
    ("codium", "VSCodium", ["codium"], "VSCodium"),
    ("zed", "Zed", ["zed"], "Zed"),
    ("subl", "Sublime Text", ["subl"], "Sublime Text"),
    ("pycharm", "PyCharm", ["pycharm", "pycharm-professional", "pycharm-community", "charm", "pycharm64"], "PyCharm"),
    ("idea", "IntelliJ IDEA", ["idea", "intellij-idea-ultimate", "intellij-idea-community", "idea64"], "IntelliJ IDEA"),
    ("webstorm", "WebStorm", ["webstorm", "webstorm64"], "WebStorm"),
    ("phpstorm", "PhpStorm", ["phpstorm", "phpstorm64"], "PhpStorm"),
    ("goland", "GoLand", ["goland", "goland64"], "GoLand"),
    ("rustrover", "RustRover", ["rustrover", "rustrover64"], "RustRover"),
    ("clion", "CLion", ["clion", "clion64"], "CLion"),
    ("studio", "Android Studio", ["studio", "studio64"], "Android Studio"),
    ("xed", "Xcode", ["xed"], None),
]
# id, label, commands, argument template ({p} = folder), macOS app
TERMINALS = [
    ("wt", "Windows Terminal", ["wt"], ["-d", "{p}"], None),
    ("powershell", "PowerShell", ["pwsh", "powershell"], None, None),
    ("cmd", "Command Prompt", ["cmd"], None, None),
    ("Terminal", "Terminal", [], None, "Terminal"),
    ("iTerm", "iTerm", [], None, "iTerm"),
    ("Warp", "Warp", [], None, "Warp"),
    ("gnome-terminal", "GNOME Terminal", ["gnome-terminal"], ["--working-directory={p}"], None),
    ("konsole", "Konsole", ["konsole"], ["--workdir", "{p}"], None),
    ("xfce4-terminal", "Xfce Terminal", ["xfce4-terminal"], ["--working-directory={p}"], None),
    ("tilix", "Tilix", ["tilix"], ["-w", "{p}"], None),
    ("kitty", "kitty", ["kitty"], ["--directory", "{p}"], None),
    ("alacritty", "Alacritty", ["alacritty"], ["--working-directory", "{p}"], None),
    ("wezterm", "WezTerm", ["wezterm"], ["start", "--cwd", "{p}"], None),
    ("x-terminal-emulator", "System default", ["x-terminal-emulator"], None, None),
]


def _mac_app(name):
    return bool(name) and any(os.path.isdir(f"{d}/{name}.app") or glob.glob(f"{d}/{name}*.app") for d in ("/Applications", f"{HOME}/Applications"))


_which = which


def _find_cmd(cmds):
    for c in cmds:
        found = _which(c)
        if found:
            return found
    for c in cmds:  # JetBrains Toolbox installs launchers here
        for pattern in (f"{HOME}/.local/share/JetBrains/Toolbox/scripts/{c}", f"{HOME}/Library/Application Support/JetBrains/Toolbox/scripts/{c}",
                        f"{os.environ.get('LOCALAPPDATA', '')}/JetBrains/Toolbox/scripts/{c}.cmd"):
            if os.path.isfile(pattern):
                return pattern
    return None


def _editor_launcher(entry):
    _, _, cmds, app = entry
    found = _find_cmd(cmds)
    if found:
        return [found]
    if MAC and _mac_app(app):
        return ["open", "-a", app]
    return None


def _terminal_available(entry):
    tid, _, cmds, _, app = entry
    if MAC:
        return _mac_app(app) or bool(_find_cmd(cmds))
    if WIN:
        return tid in ("wt", "powershell", "cmd") and bool(_find_cmd(cmds) or tid == "cmd")
    if WSL and tid == "wt":
        return bool(_which("wt.exe"))
    return not app and bool(cmds) and tid not in ("wt", "powershell", "cmd") and bool(_find_cmd(cmds))


_detected = {"at": 0, "value": None}
_lock = threading.Lock()


def _refresh():
    if not _lock.acquire(blocking=False):
        return
    try:
        _detected.update(value=_detect(), at=time.time())
    finally:
        _lock.release()


def warm():
    """Scan in the background at startup so the settings panel opens instantly."""
    threading.Thread(target=_refresh, daemon=True).start()


def detect(max_age=600):
    """Editors and terminals found on this machine. Scanning PATH is slow on WSL, so the last result is
    served at once and refreshed in the background when it is stale."""
    if _detected["value"] is None:
        with _lock:  # waits for a background scan that is already running instead of returning nothing
            if _detected["value"] is None:
                _detected.update(value=_detect(), at=time.time())
    elif time.time() - _detected["at"] > max_age:
        warm()
    return _detected["value"]


def _detect():
    editors = [{"id": e[0], "label": e[1]} for e in EDITORS if _editor_launcher(e)]
    terminals = [{"id": t[0], "label": t[1]} for t in TERMINALS if _terminal_available(t)]
    return {"editors": editors, "terminals": terminals}


def _spawn(cmd, cwd=None, shell=False):
    kw = {"creationflags": 0x08000200} if WIN else {"start_new_session": True}
    subprocess.Popen(cmd, cwd=cwd, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kw)


def _win_path(path):
    out = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True).stdout.strip()
    return out or path


def editor_cmd(settings):
    """Chosen editor, else $GITROSTER_EDITOR, else the first detected one. -> (command list, label)"""
    choice = (settings or {}).get("editor", "")
    if choice == "custom" and settings.get("editor_custom"):
        return shlex.split(settings["editor_custom"]), "custom editor"
    for e in EDITORS:
        if e[0] == choice:
            cmd = _editor_launcher(e)
            if cmd:
                return cmd, e[1]
    custom = os.environ.get("GITROSTER_EDITOR")
    if custom:
        return shlex.split(custom), custom
    for e in EDITORS:
        cmd = _editor_launcher(e)
        if cmd:
            return cmd, e[1]
    return None, ""


def _terminal_entry(settings):
    want = (settings or {}).get("terminal", "")
    avail = [t for t in TERMINALS if _terminal_available(t)]
    return next((t for t in avail if t[0] == want), avail[0] if avail else None)


def _open_terminal(path, settings):
    t = _terminal_entry(settings)
    if not t:
        raise RuntimeError("no terminal found; pick one in Settings")
    tid, label, cmds, args, app = t
    if MAC:
        if app and _mac_app(app):
            _spawn(["open", "-a", app, path])
        else:
            _spawn([_find_cmd(cmds), *[a.replace("{p}", path) for a in (args or [])]], cwd=path)
    elif WIN:
        if tid == "wt":
            _spawn(["wt", "-d", path])
        elif tid == "powershell":
            _spawn(["cmd", "/c", "start", cmds[0], "-NoExit", "-Command", f"Set-Location -LiteralPath '{path}'"])
        else:
            _spawn(["cmd", "/c", "start", "cmd", "/k", f'cd /d "{path}"'])
    elif WSL and tid == "wt":
        _spawn(["wt.exe", "-d", _win_path(path), "wsl.exe", "--cd", path])
    else:
        _spawn([_find_cmd(cmds), *[a.replace("{p}", path) for a in (args or [])]], cwd=path)
    return label


def open_repo(path, target, settings=None):
    if not os.path.isdir(path):
        raise ValueError("folder no longer exists")
    if target == "editor":
        cmd, label = editor_cmd(settings)
        if not cmd:
            raise RuntimeError("no editor found; pick one in Settings")
        full = [*cmd, path]
        _spawn(subprocess.list2cmdline(full) if WIN else full, shell=WIN)
        return label
    if target == "folder":
        if WIN:
            os.startfile(path)
        elif MAC:
            _spawn(["open", path])
        elif WSL and _which("explorer.exe"):
            _spawn(["explorer.exe", _win_path(path)])
        else:
            _spawn(["xdg-open", path])
        return "file manager"
    if target == "terminal":
        return _open_terminal(path, settings)
    raise ValueError("unknown target")
