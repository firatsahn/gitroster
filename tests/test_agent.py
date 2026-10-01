import json
import os
import shlex
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from gitroster import agent, pathscan
from gitroster.server import App
from gitroster.store import Store

from test_gitroster import git, make_repo

FAKE = """import sys
data = sys.stdin.read()
open(sys.argv[1], "w").write(data)
print('```json')
print('{"what": "A demo project", "stack": "node", "run": "npm start", "status": "adding search", "watch": "none"}')
print('```')
"""


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.old_path = os.environ.get("PATH", "")
        os.environ.pop("GITROSTER_AGENT", None)

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        pathscan._index.update(at=0.0, map={})
        self.tmp.cleanup()

    def fake_cli(self, *names):
        bindir = self.root / "bin"
        bindir.mkdir(exist_ok=True)
        for old in bindir.iterdir():  # start from an empty PATH folder each time
            old.unlink()
        for n in names:
            f = bindir / n
            f.write_text("#!/bin/sh\nexit 0\n")
            f.chmod(f.stat().st_mode | stat.S_IEXEC)
        os.environ["PATH"] = str(bindir)
        pathscan._index.update(at=0.0, map={})

    def test_parse_accepts_fenced_embedded_and_plain_answers(self):
        good = '{"what": "x", "stack": "y", "run": "z", "status": "s", "watch": "none"}'
        self.assertEqual(agent.parse("```json\n" + good + "\n```")["what"], "x")
        self.assertEqual(agent.parse("Sure! " + good + " Hope this helps")["run"], "z")
        self.assertEqual(agent.parse("just words"), {"raw": "just words"})
        self.assertEqual(agent.parse('{"unrelated": 1}'), {"raw": '{"unrelated": 1}'})

    @unittest.skipIf(sys.platform == "win32", "uses shell-script stand-ins for the CLIs")
    def test_detects_installed_cli_agents_only(self):
        self.fake_cli("gemini")
        self.assertEqual(agent.detect(), [{"id": "gemini", "label": "Gemini CLI"}])
        self.fake_cli()
        self.assertEqual(agent.detect(), [])
        self.assertEqual(agent.command({}), (None, ""))

    @unittest.skipIf(sys.platform == "win32", "uses shell-script stand-ins for the CLIs")
    def test_command_choice_and_precedence(self):
        self.fake_cli("claude", "codex")
        argv, label = agent.command({})
        self.assertEqual(label, "Claude Code")
        self.assertIn("--disallowedTools", argv)  # tools must stay off
        argv, label = agent.command({"agent": "codex"})
        self.assertEqual(label, "Codex CLI")
        self.assertIn("read-only", argv)
        argv, label = agent.command({"agent": "custom", "agent_custom": "myagent --flag"})
        self.assertEqual((argv[1:], label), (["--flag"], "custom command"))
        argv, label = agent.command({"agent": "codex"}, override="other --x")  # --agent-cmd wins
        self.assertEqual((argv[1:], label), (["--x"], "custom command"))

    def test_summarize_sends_facts_not_secrets_and_stores_result(self):
        repo = make_repo(self.root, "demo", {"package.json": json.dumps({"name": "demo", "dependencies": {"left-pad": "1"}}),
                                             ".env": "SECRET=1", "README.md": "# Demo\n\nA demo project for testing summaries.\n"})
        git(repo, "commit", "-q", "--allow-empty", "-m", "add the search box")
        script = self.root / "fake_agent.py"
        script.write_text(FAKE)
        prompt_file = self.root / "prompt.txt"
        store = Store(self.root / "c", self.root / "s")
        app = App([self.root], 0, store=store, agent_cmd=shlex.join([sys.executable, str(script), str(prompt_file)]))
        app.do_scan()
        entry = app.summarize(str(repo))
        s = entry["summary"]
        self.assertEqual((s["what"], s["run"], s["agent"]), ("A demo project", "npm start", "custom command"))
        self.assertEqual(s["head"], app.repo(str(repo))["head"])
        self.assertEqual(store.meta()[str(repo)]["summary"]["status"], "adding search")
        prompt = prompt_file.read_text()
        self.assertIn("add the search box", prompt)
        self.assertIn("left-pad", prompt)
        self.assertNotIn(".env", prompt)  # secret-looking files are not even listed
        self.assertNotIn("SECRET=1", prompt)

    @unittest.skipIf(sys.platform == "win32", "uses shell-script stand-ins for the CLIs")
    def test_summarize_reports_missing_agent_and_unknown_repo(self):
        app = App([self.root], 0, store=Store(self.root / "c", self.root / "s"))
        make_repo(self.root, "solo")
        app.do_scan()
        self.fake_cli()  # empty PATH: no agent CLI installed
        with self.assertRaises(RuntimeError):
            app.summarize(str(self.root / "solo"))
        with self.assertRaises(ValueError):
            app.summarize("/nope")


class OpenerDetectTest(unittest.TestCase):
    def test_detect_waits_for_a_scan_that_is_already_running(self):
        import threading
        import time

        from gitroster import opener

        saved, real = dict(opener._detected), opener._detect
        started = threading.Event()

        def slow():
            started.set()
            time.sleep(0.3)
            return {"editors": [], "terminals": []}

        opener._detected.update(value=None, at=0)
        opener._detect = slow
        try:
            opener.warm()  # background scan holds the lock
            self.assertTrue(started.wait(2))
            self.assertEqual(opener.detect(), {"editors": [], "terminals": []})  # used to return None here
        finally:
            opener._detect = real
            opener._detected.update(saved)


if __name__ == "__main__":
    unittest.main()
