<p align="center">
  <img src="gitroster/static/icon.svg" width="72" alt="gitroster logo">
</p>

<h1 align="center">gitroster</h1>

<p align="center">
  <b>A roster of every git repo on your machine: yours, forks and clones.<br>What each one is, what's running, and how to run it.</b>
</p>

---

You clone a lot of open source projects, fork some, and write your own. Months later you have no idea which ones are still on disk, which are running in the background, which port belongs to what, or how you started them. gitroster scans your folders and puts it all on one page.

## Quick start

```bash
pip install gitroster         # or: pipx install gitroster
gitroster ~/projects          # then open http://127.0.0.1:8765
```

From source, without installing:

```bash
git clone https://github.com/firatsahn/gitroster && cd gitroster
python3 -m gitroster ~/projects
```

### Desktop app (Electron)

Prefer a window over a browser tab? The same UI runs in an Electron shell on Windows, macOS and Linux:

```bash
cd electron && npm install && npm start
```

It starts the local server on a free port and stops it when you close the window. It needs Python 3.9+ on the machine (set `GITROSTER_PYTHON` if it is not on your PATH). It scans `~/projects`, or your home folder if that does not exist; set `GITROSTER_ROOTS` to scan other folders. `npm run dist` builds an installer with electron-builder.

### Platforms

Linux, macOS and Windows are supported. Ports come from `ss` (Linux), `lsof` (macOS) or `netstat` (Windows). On Windows a process's working directory is not readable, so ports are matched to repos by the command line only.

Scan several folders at once with `gitroster ~/projects ~/tools`. Without arguments it scans your home folder. Use `gitroster --json` to print a scan for scripts.

## What you get

**Repos**
- Every git repo, with last commit, branch, size on disk and README summary
- Sorted by origin: **mine** (you authored commits), **fork** (has an `upstream` remote), **clone** (someone else's) and **local** (no remote)
- Flags for **uncommitted changes**, **unpushed commits**, **no remote** and **dormant** (no commit in 90+ days and nothing running)
- Notes, pin and ignore, kept in `~/.config/gitroster/` (`~/Library/Application Support/gitroster` on macOS, `%APPDATA%\gitroster` on Windows)

**Look inside any repo**
- A detail page per repo: overview (languages, contributors linked to GitHub, tags, most changed files, README), file browser with a viewer, commit history with a graph and per-commit diffs, branches, dependencies
- **Search** code, file names and commit messages across every repo at once (plain text or regex)
- Search also finds **packages**: which repo uses a package and at which version, flagged when versions differ between repos
- **Related repos**: copies of the same remote, and local repos that depend on each other
- Everything is read-only

**Work you might forget**
- Stashes, branches that exist only on this machine or are not merged yet, and extra worktrees, with filters for each
- A commit graph of every branch (click a branch to jump to it)
- Light, dark or system theme in Settings
- One-click open in your editor, terminal or file manager. Settings lists the editors (VS Code, Cursor, PyCharm, IntelliJ, Zed, Sublime and more) and terminals installed on your machine so you can pick one, or set a custom command

**How to run it**
- Setup and run commands detected from `package.json` (npm, pnpm, yarn), `pyproject.toml`, `requirements.txt`, `manage.py`, `main.py`/`app.py`, `Cargo.toml`, `go.mod`, `pubspec.yaml`, `Makefile`, Docker Compose and Wrangler
- Commands use the repo's own virtual environment when one exists
- Commands and ports mentioned in the README
- **▶ Start** runs a detected command in the background with a log (after you confirm)

**Ports and processes**
- Every listening port you own, matched to a repo by the process working directory, then by the command line
- Ports open on all interfaces are flagged
- One click to open it in the browser, one to stop it
- Docker containers, matched to their compose folder

**AI summary (optional)**
- Press the sparkle button next to **Details** and an agent CLI you already have writes a short summary of the repo: what it is, stack, how to run it, what you were working on, gotchas. It is labelled *AI-generated, unverified*, shown on the card and on the repo's Overview, and marked when the repo has changed since.
- gitroster finds the agent CLIs installed on your machine (Claude Code, Codex CLI, Gemini CLI) and you pick one in Settings. There is no API key to enter and no model to host: it runs the CLI you are already signed in to, with its tools turned off, and nothing is executed.
- It sends that agent the README, a file list (secret-looking files are left out), dependency names, detected commands and recent commit titles. Where that goes depends on the agent: all three are cloud services.
- Prefer another tool? Use any command that reads a prompt on stdin: a custom command in Settings, `gitroster --agent-cmd "my-agent"` or `GITROSTER_AGENT`.
- Only Claude Code is tested here. The Codex and Gemini invocations follow their documented non-interactive modes but are untested.

## How it works

Detection is deterministic: file checks, `git`, `du`, `ss` and `/proc`. The AI part is opt-in and separate. See [SECURITY.md](SECURITY.md) for the safety model: loopback only, host and origin checks, and start/stop limited to things the scanner found.

## Limits

- Linux and WSL for now. Ports use `ss` and `/proc`. macOS is welcome as a contribution.
- Only processes owned by your user are visible.
- Hidden folders (`~/.nvm`), `node_modules` and anything deeper than 6 levels are skipped.
- A big first scan can take a while on slow disks or `/mnt/c`. The last result is shown instantly while a new scan runs.
- Run commands are guesses from well-known files. Treat them as a starting point.

## Contributing

Issues and PRs welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Run the tests with `python3 -m unittest discover -s tests`.

## License

MIT
