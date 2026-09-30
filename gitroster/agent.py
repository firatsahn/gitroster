"""Optional: ask a local coding agent to explain how to run a repo.

The agent gets the README, file tree and detected commands on stdin, and is asked
not to use tools. Output is stored as "AI-generated, unverified".
"""
import os
import shlex
import subprocess
from pathlib import Path

DEFAULT_CMD = "claude -p --disallowedTools Bash,Edit,Write,NotebookEdit"

PROMPT = """You are helping a developer remember a project they cloned months ago.
Using ONLY the context below, write a short runbook in plain text with these sections:

WHAT: one sentence on what this project is.
SETUP: numbered steps to install dependencies (mention the env in use).
RUN: the command(s) to start it and the port/URL it will use, if known.
WATCH OUT: 1-3 gotchas (GPU, API keys, .env files, large downloads). Skip if none.

Be concise (max ~150 words). If something is unknown, say "unknown" instead of guessing.
Do not run commands and do not use tools.

--- CONTEXT ---
Path: {path}
Detected stack: {stack}
Detected setup commands: {setup}
Detected run commands: {run}
Existing envs: {envs}

File tree (depth 2):
{tree}

README (truncated):
{readme}
"""


def tree(path, depth=2, limit=80):
    root = Path(path)
    out = []
    for dirpath, dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if len(rel.parts) >= depth:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules", "__pycache__") and not d.startswith(".venv"))
        for name in sorted(files)[:15]:
            out.append(str(rel / name) if rel.parts else name)
        if len(out) >= limit:
            break
    return "\n".join(out[:limit])


def build_prompt(repo):
    p = Path(repo["path"])
    text = ""
    for n in ("README.md", "readme.md", "README.rst", "README.txt"):
        if (p / n).exists():
            text = (p / n).read_text(errors="replace")[:6000]
            break
    return PROMPT.format(
        path=repo["path"], stack=", ".join(repo["stack"]) or "unknown",
        setup="; ".join(repo["setup"]) or "none", run="; ".join(repo["run"]) or "none",
        envs=", ".join(e["path"] for e in repo["envs"]) or "none",
        tree=tree(p), readme=text or "(no README)")


def explain(repo, agent_cmd=None, timeout=180):
    cmd = shlex.split(agent_cmd or os.environ.get("GITROSTER_AGENT") or DEFAULT_CMD)
    try:
        r = subprocess.run(cmd, input=build_prompt(repo), capture_output=True, text=True,
                           timeout=timeout, cwd=repo["path"])
    except FileNotFoundError:
        raise RuntimeError(f"agent command not found: {cmd[0]} (set --agent-cmd or GITROSTER_AGENT)")
    except subprocess.TimeoutExpired:
        raise RuntimeError("agent timed out")
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError((r.stderr or "agent returned nothing").strip()[:300])
    return r.stdout.strip()
