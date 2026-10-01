"""Small JSON persistence: user notes/flags and the last scan."""
import json
import os
import sys
import threading
from pathlib import Path


def _dir(kind):
    """Per-OS config/state folder: XDG on Linux, Application Support on macOS, AppData on Windows."""
    home = Path.home()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA" if kind == "config" else "LOCALAPPDATA") or str(home / "AppData" / ("Roaming" if kind == "config" else "Local"))
    elif sys.platform == "darwin":
        base = str(home / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME" if kind == "config" else "XDG_STATE_HOME") or str(home / (".config" if kind == "config" else ".local/state"))
    d = Path(base) / "gitroster"
    if sys.platform in ("win32", "darwin") and kind == "state":
        d = d / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Store:
    def __init__(self, config_dir=None, state_dir=None):
        self.config = Path(config_dir) if config_dir else _dir("config")
        self.state = Path(state_dir) if state_dir else _dir("state")
        self.config.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _load(self, path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, path, data):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)

    def meta(self):
        return self._load(self.config / "meta.json")

    def update_meta(self, repo_path, **fields):
        allowed = {"note", "pinned", "ignored", "ai", "ai_at"}
        with self.lock:
            data = self._load(self.config / "meta.json")
            entry = data.setdefault(repo_path, {})
            entry.update({k: v for k, v in fields.items() if k in allowed})
            self._save(self.config / "meta.json", data)
            return entry

    def settings(self):
        return self._load(self.config / "settings.json")

    def update_settings(self, **fields):
        allowed = {"editor", "editor_custom", "terminal", "theme"}
        with self.lock:
            data = self._load(self.config / "settings.json")
            data.update({k: v for k, v in fields.items() if k in allowed})
            self._save(self.config / "settings.json", data)
            return data

    def cached_scan(self):
        return self._load(self.state / "scan.json")

    def save_scan(self, scan):
        with self.lock:
            self._save(self.state / "scan.json", scan)

    def log_path(self, name):
        d = self.state / "logs"
        d.mkdir(exist_ok=True)
        return d / f"{name}.log"
