<p align="center">
  <img src="gitroster/static/icon.svg" width="72" alt="gitroster logo">
</p>

<h1 align="center">gitroster</h1>

<p align="center">
  <b>A roster of every git repo on your machine: yours, forks and clones.<br>What each one is, what's running, and how to run it.</b><br>
  Local-first. No dependencies. Nothing leaves your machine.
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

**Cleanup**
- Environments, `node_modules`, build folders and large files, sorted by size and marked "in use" when the repo is running
- Dormant repos with their size
- Copy-paste `rm` commands. The only thing gitroster deletes itself is what you **Park** (dependency and build folders, after a confirmation, never git-tracked files and never while the repo is running)

**AI runbook (optional)**
- Press "Explain how to run" and your local agent writes a short runbook from the README, file tree and detected commands. It is labelled *AI-generated, unverified* and nothing is executed.
- Default agent is `claude -p`. Use any command that reads a prompt on stdin: `gitroster --agent-cmd "ollama run llama3.1"` or set `GITROSTER_AGENT`.

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
