"""Small JSON persistence: user notes/flags and the last scan."""
import json
import os
import threading
from pathlib import Path


def _dir(env, fallback):
    base = os.environ.get(env) or str(Path.home() / fallback)
    d = Path(base) / "gitroster"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Store:
    def __init__(self, config_dir=None, state_dir=None):
        self.config = Path(config_dir) if config_dir else _dir("XDG_CONFIG_HOME", ".config")
        self.state = Path(state_dir) if state_dir else _dir("XDG_STATE_HOME", ".local/state")
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

    def cached_scan(self):
        return self._load(self.state / "scan.json")

    def save_scan(self, scan):
        with self.lock:
            self._save(self.state / "scan.json", scan)

    def log_path(self, name):
        d = self.state / "logs"
        d.mkdir(exist_ok=True)
        return d / f"{name}.log"
