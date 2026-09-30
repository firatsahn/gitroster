"""Open a repo in an editor, a terminal or the file manager (Linux, macOS, Windows, WSL)."""
import os
import shlex
import shutil
import subprocess
import sys

EDITORS = ("code", "cursor", "codium", "windsurf", "zed", "subl", "idea", "pycharm")
TERMINALS = ("x-terminal-emulator", "gnome-terminal", "konsole", "kitty", "alacritty", "xfce4-terminal")
WSL = bool(os.environ.get("WSL_DISTRO_NAME"))


def _spawn(cmd, cwd=None, shell=False):
    kw = {"creationflags": 0x08000200} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen(cmd, cwd=cwd, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kw)


def _win_path(path):
    out = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True).stdout.strip()
    return out or path


def editor_cmd():
    """User override ($GITROSTER_EDITOR) or the first known editor on PATH."""
    custom = os.environ.get("GITROSTER_EDITOR")
    if custom:
        return shlex.split(custom)
    for name in EDITORS:
        if shutil.which(name):
            return [name]
    return None


def open_repo(path, target):
    if not os.path.isdir(path):
        raise ValueError("folder no longer exists")
    win = sys.platform == "win32"
    if target == "editor":
        cmd = editor_cmd()
        if not cmd:
            raise RuntimeError("no editor found; set GITROSTER_EDITOR (for example 'code')")
        cmd = [shutil.which(cmd[0]) or cmd[0], *cmd[1:], path]
        _spawn(cmd if not win else subprocess.list2cmdline(cmd), shell=win)
        return cmd[0]
    if target == "folder":
        if win:
            os.startfile(path)
        elif sys.platform == "darwin":
            _spawn(["open", path])
        elif WSL and shutil.which("explorer.exe"):
            _spawn(["explorer.exe", _win_path(path)])
        else:
            _spawn(["xdg-open", path])
        return "file manager"
    if target == "terminal":
        if win:
            if shutil.which("wt"):
                _spawn(["wt", "-d", path])
            else:
                _spawn(["cmd", "/c", "start", "cmd", "/k", f'cd /d "{path}"'])
        elif sys.platform == "darwin":
            _spawn(["open", "-a", "Terminal", path])
        elif WSL and shutil.which("wt.exe"):
            _spawn(["wt.exe", "-d", _win_path(path), "wsl.exe", "--cd", path])
        else:
            term = next((t for t in TERMINALS if shutil.which(t)), None)
            if not term:
                raise RuntimeError("no terminal emulator found")
            _spawn([term], cwd=path)
        return "terminal"
    raise ValueError("unknown target")
