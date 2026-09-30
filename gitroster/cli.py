import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__, scanner
from .server import App, serve


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gitroster",
                                 description="Find the repos, envs and ports you forgot about.")
    ap.add_argument("roots", nargs="*", default=[str(Path.home())], help="folders to scan (default: ~)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--json", action="store_true", help="print one scan as JSON and exit")
    ap.add_argument("--open", action="store_true", help="open the page in a browser")
    ap.add_argument("--agent-cmd", help='command for AI summaries; reads the prompt on stdin '
                                        '(default: "claude -p", or $GITROSTER_AGENT)')
    ap.add_argument("--version", action="version", version=f"gitroster {__version__}")
    a = ap.parse_args(argv)

    if a.json:
        json.dump(scanner.scan(a.roots), sys.stdout, indent=2)
        return 0

    app = App(a.roots, a.port, agent_cmd=a.agent_cmd)
    url = f"http://127.0.0.1:{a.port}"
    print(f"gitroster {__version__} on {url}  (scanning {', '.join(a.roots)})")
    if a.open:
        webbrowser.open(url)
    serve(app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
