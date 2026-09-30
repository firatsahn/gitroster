import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gitroster import procs, scanner
from gitroster.server import App, make_handler
from gitroster.store import Store


def git(path, *args):
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_repo(root, name, files=None):
    p = Path(root) / name
    p.mkdir(parents=True)
    git(p, "init", "-q")
    for f, content in (files or {}).items():
        (p / f).parent.mkdir(parents=True, exist_ok=True)
        (p / f).write_text(content)
    git(p, "add", "-A")
    git(p, "commit", "-qm", "init", "--allow-empty")
    return p


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_repo_and_node_commands(self):
        make_repo(self.root, "site", {
            "package.json": json.dumps({"scripts": {"dev": "vite", "build": "vite build", "evil; rm": "x"}}),
            "README.md": "# Site\n\nA small demo website used for testing gitroster.\n\nOpen http://localhost:5173\n",
        })
        s = scanner.scan([self.root])
        (r,) = s["repos"]
        self.assertEqual(r["name"], "site")
        self.assertIn("node", r["stack"])
        self.assertEqual(r["run"], ["npm run dev"])
        self.assertEqual(r["setup"], ["npm install"])
        self.assertEqual(r["expected_ports"], [5173])
        self.assertFalse(r["dirty"])
        self.assertEqual(r["kind"], "local")

    def test_dirty_and_branch_names_with_dots(self):
        p = make_repo(self.root, "app", {"main.py": "print(1)"})
        git(p, "checkout", "-qb", "release/v1.2")
        (p / "new.txt").write_text("x")
        info = scanner.git_info(p)
        self.assertEqual(info["branch"], "release/v1.2")
        self.assertTrue(info["dirty"])

    def test_health_flags_tracked_and_unignored_secrets(self):
        make_repo(self.root, "leaky", {".env": "KEY=1", "package.json": "{}", "deploy/server.pem": "x"})
        make_repo(self.root, "safe", {".gitignore": ".env\n", ".env.example": "KEY=", "package.json": "{}"})
        (self.root / "safe" / ".env").write_text("KEY=1")
        by = {r["name"]: r for r in scanner.scan([self.root])["repos"]}
        self.assertEqual([i["kind"] for i in by["leaky"]["health"]], ["tracked-secret", "no-gitignore"])
        self.assertEqual(by["leaky"]["health"][0]["files"], [".env", "deploy/server.pem"])
        self.assertEqual(by["safe"]["health"], [])

    def test_unignored_env_file(self):
        p = make_repo(self.root, "x", {".gitignore": "*.log\n", "package.json": "{}"})
        (p / ".env").write_text("A=1")
        self.assertEqual([i["kind"] for i in scanner.health(p)], ["unignored-env"])

    def test_subprojects_and_export(self):
        make_repo(self.root, "mono", {"web/package.json": json.dumps({"scripts": {"dev": "vite"}}), "docs/a.md": "x"})
        s = scanner.scan([self.root])
        (r,) = s["repos"]
        self.assertEqual([(x["name"], x["run"]) for x in r["subprojects"]], [("web", ["npm run dev"])])
        from gitroster import export
        md = export.markdown(s, {r["path"]: {"note": "my note"}})
        self.assertIn("## mono", md)
        self.assertIn("my note", md)

    def test_park_removes_untracked_folders_and_writes_restore(self):
        p = make_repo(self.root, "web", {"package.json": "{}", "dist/tracked.js": "x"})
        (p / "node_modules" / "a").mkdir(parents=True)
        (p / "node_modules" / "a" / "i.js").write_text("x")
        repo = scanner.scan([self.root])["repos"][0]
        removed, text = scanner.park(repo, today="2026-01-01")
        self.assertEqual(removed, [str(p / "node_modules")])
        self.assertTrue((p / "dist" / "tracked.js").exists())  # tracked by git: untouched
        self.assertIn("Parked 2026-01-01", text)
        self.assertIn("npm install", text)

    def test_venv_is_linked_and_used_in_run_command(self):
        p = make_repo(self.root, "api", {"main.py": "print(1)", "requirements.txt": "flask\n"})
        venv = p / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version = 3.12.3\n")
        (self.root / "stray_env").mkdir()
        (self.root / "stray_env" / "pyvenv.cfg").write_text("version = 3.10.0\n")
        s = scanner.scan([self.root])
        (r,) = s["repos"]
        self.assertEqual([e["path"] for e in r["envs"]], [str(venv)])
        self.assertEqual(r["run"], [f".venv{scanner.SEP}{scanner.BIN}{scanner.SEP}python main.py"])
        self.assertEqual(r["setup"], [])
        self.assertEqual(r["activate"], (f".venv{scanner.SEP}{scanner.BIN}{scanner.SEP}activate" if scanner.WIN else "source .venv/bin/activate"))
        orphans = [e for e in s["envs"] if not e["repo"]]
        self.assertEqual([e["name"] for e in orphans], ["stray_env"])

    def test_python_repo_without_venv_gets_setup_steps(self):
        make_repo(self.root, "tool", {"main.py": "x", "requirements.txt": "a\n"})
        (r,) = scanner.scan([self.root])["repos"]
        self.assertEqual(r["setup"][0], f"{scanner.PY} -m venv .venv")
        self.assertIn(f".venv{scanner.SEP}{scanner.BIN}{scanner.SEP}pip install -r requirements.txt", r["setup"])
        self.assertEqual(r["run"], [f"{scanner.PY} main.py"])

    def test_generic_folder_names_get_parent_prefix(self):
        make_repo(self.root / "venhancer", "project")
        (r,) = scanner.scan([self.root])["repos"]
        self.assertEqual(r["name"], "venhancer/project")

    def test_reclaimable_and_big_files(self):
        p = make_repo(self.root, "ml", {"a.txt": "x"})
        (p / "node_modules").mkdir()
        (p / "node_modules" / "x").write_bytes(b"0" * 4096)
        big = p / "model.safetensors"
        with open(big, "wb") as f:
            f.truncate(scanner.BIG_FILE + 1)
        (r,) = scanner.scan([self.root])["repos"]
        self.assertEqual([x["kind"] for x in r["reclaimable"]], ["node_modules"])
        self.assertEqual(r["big_files"][0]["path"], "model.safetensors")
        self.assertGreater(r["big_total"], scanner.BIG_FILE)

    def test_repo_kind(self):
        def with_remote(name, *remotes, email="t@t"):
            p = make_repo(self.root, name)
            git(p, "config", "user.email", email)
            for rn in remotes:
                git(p, "remote", "add", rn, "https://example.com/x/y.git")
            return p
        self.assertEqual(scanner.repo_kind(with_remote("a"), ""), "local")
        self.assertEqual(scanner.repo_kind(with_remote("b", "origin", "upstream"), ""), "fork")
        self.assertEqual(scanner.repo_kind(with_remote("c", "origin"), ""), "mine")  # commits by t@t
        self.assertEqual(scanner.repo_kind(with_remote("d", "origin", email="someone@else"), ""), "clone")

    def test_owner_prefers_longest_path(self):
        items = [{"path": "/a"}, {"path": "/a/b"}]
        self.assertEqual(scanner.owner("/a/b/c", items)["path"], "/a/b")
        self.assertEqual(scanner.owner("/a/bc", items)["path"], "/a")
        self.assertIsNone(scanner.owner("/x", items))

    def test_port_linked_by_cwd_then_command_line(self):
        repos = [{"path": "/r/one"}, {"path": "/r/two"}]
        envs = [{"path": "/r/two/.venv"}]
        ports = [
            {"cwd": "/r/one/src", "cmd": "node x", "repo": None},
            {"cwd": "/", "cmd": "/r/two/.venv/bin/python app.py", "repo": None},
            {"cwd": "/", "cmd": "nginx", "repo": None},
        ]
        procs.link(ports, [], repos, envs)
        self.assertEqual([p["repo"] for p in ports], ["/r/one", "/r/two", None])


class PlatformParsersTest(unittest.TestCase):
    def test_parse_ss(self):
        out = 'LISTEN 0 128 127.0.0.1:8765 0.0.0.0:* users:(("python3",pid=42,fd=3))\nLISTEN 0 4096 [::]:22 [::]:*\n'
        self.assertEqual(procs.parse_ss(out), [("127.0.0.1", "8765", "42", "python3")])

    def test_parse_lsof_macos(self):
        out = ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
               "node 501 me 23u IPv4 0x1 0t0 TCP *:3000 (LISTEN)\n"
               "Python 77 me 4u IPv6 0x2 0t0 TCP [::1]:8000 (LISTEN)\n")
        self.assertEqual(procs.parse_lsof(out), [("*", "3000", "501", "node"), ("[::1]", "8000", "77", "Python")])

    def test_parse_netstat_windows(self):
        out = ("  Proto  Local Address          Foreign Address        State           PID\r\n"
               "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1040\r\n"
               "  TCP    127.0.0.1:5173         0.0.0.0:0              LISTENING       9120\r\n"
               "  TCP    127.0.0.1:5173         127.0.0.1:5000         ESTABLISHED     9120\r\n")
        self.assertEqual(procs.parse_netstat(out), [("0.0.0.0", "135", "1040"), ("127.0.0.1", "5173", "9120")])

    def test_parse_powershell_processes(self):
        one = '{"p":9120,"n":"node.exe","c":"node vite","t":1700000000}'
        self.assertEqual(procs.parse_ps_procs(one)[9120]["n"], "node.exe")
        self.assertEqual(len(procs.parse_ps_procs("[" + one + "," + one.replace("9120", "7") + "]")), 2)
        self.assertEqual(procs.parse_ps_procs("garbage"), {})

    def test_walk_size_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a").mkdir()
            (Path(d) / "a" / "f").write_bytes(b"x" * 100)
            self.assertEqual(scanner.walk_size(d, 1e12), 100)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.repo = make_repo(root / "src", "demo", {"main.py": "print('hello')\n"})
        store = Store(root / "cfg", root / "state")
        cls.app = App([root / "src"], 0, store=store)
        cls.app.do_scan()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (), {}))
        cls.app.port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = make_handler(cls.app)
        cls.base = f"http://127.0.0.1:{cls.app.port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        h = {"Origin": self.base, "Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=h if body is not None else (headers or {}))
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_state_lists_repo(self):
        code, s = self.call("/api/state")
        self.assertEqual(code, 200)
        self.assertEqual([r["name"] for r in s["repos"]], ["demo"])

    def test_rejects_foreign_host_and_origin(self):
        code, _ = self.call("/api/state", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)
        code, _ = self.call("/api/meta", {"path": str(self.repo), "note": "x"}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)

    def test_meta_roundtrip_and_unknown_repo(self):
        code, m = self.call("/api/meta", {"path": str(self.repo), "note": "hi", "pinned": True, "junk": 1})
        self.assertEqual((code, m), (200, {"note": "hi", "pinned": True}))
        code, _ = self.call("/api/meta", {"path": "/etc", "note": "x"})
        self.assertEqual(code, 404)

    def test_start_only_runs_detected_commands(self):
        code, _ = self.call("/api/start", {"path": str(self.repo), "cmd": "rm -rf /"})
        self.assertEqual(code, 400)
        code, r = self.call("/api/start", {"path": str(self.repo), "cmd": "python3 main.py"})
        self.assertEqual(code, 200)
        for _ in range(50):
            _, out = self.call("/api/log?path=" + urllib.request.quote(str(self.repo)))
            if "hello" in out["log"]:
                break
            threading.Event().wait(0.1)
        self.assertIn("hello", out["log"])

    def test_kill_refuses_non_listening_pid(self):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # alive, but not listening on any port
        try:
            code, _ = self.call("/api/kill", {"pid": sleeper.pid})
            self.assertEqual(code, 404)
            self.assertIsNone(sleeper.poll())
        finally:
            sleeper.kill()
            sleeper.wait()


if __name__ == "__main__":
    unittest.main()
