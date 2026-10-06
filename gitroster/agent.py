"""Optional: ask a coding agent CLI you already have to summarize a repo.

Nothing here talks to a network service itself and no API keys are handled. gitroster only runs the
agent CLI you chose, feeds it a prompt on stdin and asks it not to use tools. The answer is stored
as "AI-generated, unverified".
"""
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from . import scanner
from .pathscan import which

# id, label, program, arguments, how to install. The prompt is written to stdin. Every entry must keep
# the agent away from tools: the summary needs only text, and nothing should be run or edited.
AGENTS = [
    ("claude", "Claude Code", "claude", ["-p", "--disallowedTools", "Bash,Edit,Write,NotebookEdit"],
     "npm install -g @anthropic-ai/claude-code"),
    ("codex", "Codex CLI", "codex", ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"],
     "npm install -g @openai/codex"),
    ("gemini", "Gemini CLI", "gemini", ["-p", "Follow the instructions in the input exactly. Do not use tools."],
     "npm install -g @google/gemini-cli"),
]

PROMPT = """You are helping a developer remember a project they wrote or cloned long ago.
Use ONLY the facts below. If something is not in the facts, say "unknown". Do not run commands or use tools.

Answer with ONLY a JSON object (no markdown fence) with these string keys:
  "what":   one sentence on what this project is and does
  "stack":  the main languages, frameworks and services, short
  "run":    how to set it up and start it, 1-3 short steps, or "unknown"
  "status": what the recent commits, unmerged branches and stashes suggest was being worked on, 1-2 sentences
  "watch":  gotchas such as API keys, GPUs, databases, large downloads; "none" if nothing is apparent

--- FACTS ---
Name: {name}
Path: {path}
Kind: {kind}   Branch: {branch}   Uncommitted changes: {dirty}   Unpushed commits: {ahead}
Detected stack: {stack}
Setup commands: {setup}
Run commands: {run}
Dependencies: {deps}
Local-only or unmerged branches: {branches}
Stashes: {stashes}

Recent commits (newest first):
{commits}

File tree (depth 2):
{tree}

README (truncated):
{readme}
"""


def detect():
    """Agent CLIs installed on this machine."""
    return [{"id": e[0], "label": e[1]} for e in AGENTS if which(e[2])]


def catalog():
    """Every agent gitroster knows how to drive, with whether it is installed here."""
    return [{"id": i, "label": label, "installed": bool(which(prog)), "install": hint} for i, label, prog, _, hint in AGENTS]


def _resolve(argv):
    return [which(argv[0]) or argv[0], *argv[1:]]


def command(settings=None, override=None):
    """-> (argv, label). Precedence: --agent-cmd / $GITROSTER_AGENT, a custom command from Settings,
    the agent picked in Settings, then the first one found."""
    explicit = override or os.environ.get("GITROSTER_AGENT")
    if explicit:
        return _resolve(shlex.split(explicit)), "custom command"
    settings = settings or {}
    if settings.get("agent") == "custom" and settings.get("agent_custom"):
        return _resolve(shlex.split(settings["agent_custom"])), "custom command"
    entries = [e for e in AGENTS if which(e[2])]
    chosen = next((e for e in entries if e[0] == settings.get("agent")), entries[0] if entries else None)
    if not chosen:
        return None, ""
    return [which(chosen[2]), *chosen[3]], chosen[1]


def tree(path, depth=2, limit=80):
    root = Path(path)
    out = []
    for dirpath, dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if len(rel.parts) >= depth:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules", "__pycache__") and not d.startswith(".venv"))
        for name in sorted(files)[:15]:
            shown = str(rel / name) if rel.parts else name
            if not scanner.SECRET_FILES.search(shown):  # never even list secret-looking files
                out.append(shown)
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
    w = repo.get("work") or {}
    commits = "\n".join(f"- {c['subject']}" for c in scanner.graph(p, 15)) or "none"
    deps = ", ".join(d["name"] for d in repo.get("deps", [])[:25]) or "none"
    return PROMPT.format(
        name=repo["name"], path=repo["path"], kind=repo.get("kind", ""), branch=repo.get("branch", ""),
        dirty="yes" if repo.get("dirty") else "no", ahead=repo.get("ahead", 0),
        stack=", ".join(repo["stack"]) or "unknown", setup="; ".join(repo["setup"]) or "none",
        run="; ".join(repo["run"]) or "none", deps=deps,
        branches=", ".join(f"{b['name']} ({b['state']})" for b in w.get("branches", [])[:8]) or "none",
        stashes="; ".join(s["message"] for s in w.get("stashes", [])[:5]) or "none",
        commits=commits, tree=tree(p), readme=text or "(no README)")


KEYS = ("what", "stack", "run", "status", "watch")


def parse(text):
    """The agent's answer as {what, stack, run, status, watch}; falls back to the raw text."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    for candidate in (cleaned, cleaned[cleaned.find("{"):cleaned.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and any(k in data for k in KEYS):
            return {k: str(data.get(k, "")).strip()[:600] for k in KEYS}
    return {"raw": text.strip()[:2000]}


def summarize(repo, settings=None, override=None, timeout=180):
    argv, label = command(settings, override)
    if not argv:
        raise RuntimeError("no agent CLI found; install Claude Code, Codex or Gemini CLI, or set a custom command in Settings")
    try:
        r = subprocess.run(argv, input=build_prompt(repo), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=repo["path"])
    except FileNotFoundError:
        raise RuntimeError(f"agent command not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("the agent took too long")
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError((r.stderr or "the agent returned nothing").strip()[:300])
    return {**parse(r.stdout), "agent": label, "head": repo.get("head", ""), "at": time.time()}
