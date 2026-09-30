# Changelog

## Unreleased

- Windows and macOS support (ports via `lsof` / `netstat`, per-OS config folders, Windows paths and commands). CI now runs on all three.
- Electron desktop app in `electron/`.
- Park: remove a repo's dependency and build folders (never git-tracked ones, never while it listens on a port) and save the restore command in its note.
- Health check: tracked secret-looking files, `.env` not ignored, missing `.gitignore`.
- Zombie warning for repos that hold a port but have no recent commits.
- Projects inside repo subfolders are listed with their run commands.
- Markdown export of the whole inventory (`/api/export.md`, Export button).

## 0.1.0

- Scan folders for git repos, Python venvs / conda envs, reclaimable folders and large files.
- Match listening ports and Docker containers to repos (by working directory, then command line).
- Repo kind: mine, fork, clone or local.
- Repo status: uncommitted changes, unpushed commits, dormant, no remote.
- Detect setup and run commands (npm/pnpm/yarn, Python, Cargo, Go, Flutter, Make, Docker Compose, Wrangler) plus commands and expected ports from the README.
- Start a detected command, stop a listening process, and read the log, all with confirmation.
- Notes, pin and ignore per repo.
- Cleanup view with copyable `rm` commands. Nothing is ever deleted by the tool.
- Optional AI runbook through a local agent (`claude -p` by default).
