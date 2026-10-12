import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from gitroster import demo, procs
from gitroster.server import App, make_handler


class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = (procs.listening, procs.docker_containers)
        roots, store = demo.setup()
        cls.root = roots[0]
        cls.app = App(roots, 0, store=store, demo=True)
        cls.state = cls.app.do_scan()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (), {}))
        cls.app.port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = make_handler(cls.app)
        cls.base = f"http://127.0.0.1:{cls.app.port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        procs.listening, procs.docker_containers = cls.real  # setup() replaces them; put the real ones back

    def repo(self, name):
        return next(r for r in self.state["repos"] if r["name"] == name)

    def test_sample_repos_cover_the_states_the_ui_shows(self):
        self.assertEqual(len(self.state["repos"]), 6)
        self.assertEqual(self.repo("atlas-api")["ahead"], 2)
        self.assertEqual(self.repo("atlas-api")["kind"], "mine")
        self.assertEqual(self.repo("rust-notes")["kind"], "clone")
        self.assertEqual(self.repo("weather-cli")["kind"], "fork")
        self.assertEqual(self.repo("old-experiment")["kind"], "local")
        self.assertTrue(self.repo("bookshelf")["dirty"])
        self.assertEqual(len(self.repo("bookshelf")["work"]["stashes"]), 1)
        self.assertIn("tracked-secret", [h["kind"] for h in self.repo("old-experiment")["health"]])

    def test_ports_are_fake_and_linked_to_sample_repos(self):
        self.assertEqual(self.repo("atlas-api")["ports"], [3000])
        self.assertEqual(self.repo("dashboard-ui")["ports"], [5173])
        self.assertTrue(all(p["pid"] >= 40000 for p in self.state["ports"]))

    def test_paths_read_as_home(self):
        self.assertTrue(self.repo("atlas-api")["path"].startswith(self.app.state()["home"]))
        self.assertTrue(self.app.state()["demo"])

    def test_risky_actions_are_disabled(self):
        r = self.repo("atlas-api")
        for path, body in (("/api/kill", {"pid": 40000}), ("/api/start", {"path": r["path"], "cmd": r["run"][0]}),
                           ("/api/open", {"path": r["path"], "target": "folder"}), ("/api/summarize", {"path": r["path"]})):
            req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Origin": self.base})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual((path, cm.exception.code), (path, 403))

    def test_summaries_are_stored_for_two_repos(self):
        meta = self.app.store.meta()
        self.assertIn("what", meta[self.repo("atlas-api")["path"]]["summary"])
        self.assertTrue(meta[self.repo("atlas-api")["path"]]["pinned"])


if __name__ == "__main__":
    unittest.main()
