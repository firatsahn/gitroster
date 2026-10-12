"""Local HTTP server: JSON API + one static page. Binds to 127.0.0.1 only."""
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path

from . import __version__, agent, export, opener, procs, repoinfo, scanner
from .store import Store

STATIC = Path(__file__).parent / "static"
READ = {"graph", "overview", "tree", "file", "commit", "search"}
TYPES = {".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


class App:
    def __init__(self, roots, port, store=None, agent_cmd=None, demo=False):
        self.roots, self.port, self.agent_cmd, self.demo = roots, port, agent_cmd, demo
        self.store = store or Store()
        self.scan = self.store.cached_scan()
        self.scanning = False
        self.lock = threading.Lock()
        threading.Thread(target=opener.detect, daemon=True).start()  # warm the editor/terminal cache

    def settings(self):
        return {"settings": self.store.settings(), **opener.detect(), "agents": agent.catalog(), "version": __version__,
                "agent_override": bool(self.agent_cmd or os.environ.get("GITROSTER_AGENT"))}

    def summarize(self, path):
        repo = self.repo(path)
        if not repo:
            raise ValueError("unknown repo")
        summary = agent.summarize(repo, self.store.settings(), self.agent_cmd)
        return self.store.update_meta(path, summary=summary)

    def repo(self, path):
        return next((r for r in self.scan.get("repos", []) if r["path"] == path), None)

    def do_scan(self):
        with self.lock:
            if self.scanning:  # a scan is already running: don't start a second one
                return self.state()
            self.scanning = True
        try:
            result = scanner.scan(self.roots)
            self.scan = result
            self.store.save_scan(result)
        finally:
            self.scanning = False
        return self.state()

    def live_ports(self):
        ports, containers = procs.listening(), procs.docker_containers()
        procs.link(ports, containers, self.scan.get("repos", []), self.scan.get("envs", []))
        return ports, containers

    def state(self):
        s = dict(self.scan)
        s["meta"] = self.store.meta()
        s["scanning"] = self.scanning
        s["platform"] = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
        s["home"] = str(self.store.config.parent) if self.demo else str(Path.home())  # demo paths read as ~/projects/...
        s["demo"] = self.demo
        return s

    def start(self, path, cmd):
        repo = self.repo(path)
        if not repo or cmd not in repo["run"]:
            raise ValueError("command is not a detected run command for this repo")
        log = self.store.log_path(path)
        with open(log, "ab") as f:
            f.write(f"\n$ {cmd}   [{time.ctime()}]\n".encode())
            if sys.platform == "win32":  # cmd comes from the detected list, never from the request
                proc = subprocess.Popen(cmd, cwd=path, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        shell=True, creationflags=0x08000200)  # new process group, no console window (DETACHED_PROCESS loses the log)
            else:
                proc = subprocess.Popen(shlex.split(cmd), cwd=path, stdout=f, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
        threading.Thread(target=proc.wait, daemon=True).start()  # reap it when it exits
        return {"pid": proc.pid, "log": str(log)}

    def tail(self, path, n=4000):
        log = self.store.log_path(path)
        try:
            with open(log, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - n))
                return f.read().decode(errors="replace")
        except OSError:
            return ""


def make_handler(app):
    hosts = {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def ok(self, obj):
            self.send(200, json.dumps(obj))

        def err(self, code, msg):
            self.send(code, json.dumps({"error": msg}))

        def read_api(self, name):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            repos = [r for r in app.scan.get("repos", []) if not app.store.meta().get(r["path"], {}).get("ignored")]
            try:
                if name == "search":
                    scope = tuple(x for x in q.get("scope", "code,files,commits").split(",") if x in ("code", "files", "commits"))
                    return self.ok({"results": repoinfo.search(repos, q.get("q", ""), scope, q.get("regex") == "1")})
                p = q.get("path", "")
                if not app.repo(p):
                    return self.err(404, "unknown repo")
                if name == "graph":
                    return self.ok({"commits": scanner.graph(p, min(int(q.get("n", 300)), 1000))})
                if name == "overview":
                    return self.ok(repoinfo.overview(p))
                if name == "tree":
                    return self.ok({"entries": repoinfo.tree(p, q.get("ref"), q.get("dir"))})
                if name == "file":
                    return self.ok(repoinfo.read_file(p, q.get("ref"), q.get("file")))
                if name == "commit":
                    return self.ok(repoinfo.commit(p, q.get("hash")))
            except ValueError as e:
                return self.err(400, str(e))
            self.err(404, "not found")

        def do_GET(self):
            if self.headers.get("Host") not in hosts:  # DNS rebinding guard
                return self.err(403, "bad host")
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self.send(200, (STATIC / "index.html").read_bytes(), TYPES[".html"])
            if path in ("/icon.svg", "/favicon.svg", "/favicon.ico"):
                return self.send(200, (STATIC / "icon.svg").read_bytes(), TYPES[".svg"])
            if path == "/api/state":
                return self.ok(app.state())
            if path.startswith("/api/") and path.split("/")[2] in READ:
                return self.read_api(path.split("/")[2])
            if path == "/api/settings":
                return self.ok(app.settings())
            if path == "/api/export.md":
                return self.send(200, export.markdown(app.scan, app.store.meta()), "text/markdown; charset=utf-8")
            if path == "/api/ports":
                ports, containers = app.live_ports()
                return self.ok({"ports": ports, "containers": containers})
            if path == "/api/log":
                q = dict(x.split("=", 1) for x in self.path.partition("?")[2].split("&") if "=" in x)
                from urllib.parse import unquote
                p = unquote(q.get("path", ""))
                return self.ok({"log": app.tail(p) if app.repo(p) else ""})
            self.err(404, "not found")

        def do_POST(self):
            origin = self.headers.get("Origin", "").split("//")[-1]
            if self.headers.get("Host") not in hosts or origin not in hosts:
                return self.err(403, "forbidden")
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 <= length <= 1_000_000:
                    return self.err(413, "body too large")
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self.err(400, "bad json")
            path = self.path
            if app.demo and path in ("/api/kill", "/api/start", "/api/open", "/api/summarize"):
                return self.err(403, "disabled in demo mode")
            try:
                if path == "/api/scan":  # POST only: a page on another site must not be able to trigger a scan
                    return self.ok(app.do_scan())
                if path == "/api/kill":
                    pid = int(body["pid"])
                    if pid not in {p["pid"] for p in procs.listening()}:
                        return self.err(404, "not a listening process")
                    os.kill(pid, signal.SIGTERM)
                    return self.ok({"ok": True})
                if path == "/api/settings":
                    fields = {k: str(body[k])[:300] for k in ("editor", "editor_custom", "terminal", "theme", "agent", "agent_custom") if k in body}
                    if fields.get("theme") not in (None, "system", "light", "dark"):
                        return self.err(400, "theme must be system, light or dark")
                    app.store.update_settings(**fields)
                    return self.ok(app.settings())
                if path == "/api/open":
                    if not app.repo(body["path"]):
                        return self.err(404, "unknown repo")
                    return self.ok({"with": opener.open_repo(body["path"], body["target"], app.store.settings())})
                if path == "/api/start":
                    return self.ok(app.start(body["path"], body["cmd"]))
                if path == "/api/meta":
                    if not app.repo(body["path"]):
                        return self.err(404, "unknown repo")
                    fields = {k: body[k] for k in ("note", "pinned", "ignored") if k in body}
                    if "note" in fields:
                        fields["note"] = str(fields["note"])[:4000]
                    return self.ok(app.store.update_meta(body["path"], **fields))
                if path == "/api/summarize":
                    return self.ok(app.summarize(body["path"]))
            except (KeyError, ValueError, TypeError) as e:
                return self.err(400, f"bad request: {e}")
            except RuntimeError as e:
                return self.err(500, str(e))
            except OSError as e:
                return self.err(500, str(e))
            self.err(404, "not found")

    return Handler


def serve(app):
    opener.warm()
    srv = ThreadingHTTPServer(("127.0.0.1", app.port), make_handler(app))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
