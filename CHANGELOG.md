# Changelog

## Unreleased

- Windows and macOS support (ports via `lsof` / `netstat`, per-OS config folders, Windows paths and commands). CI now runs on all three.
- Electron desktop app in `electron/`.
- Health check: tracked secret-looking files, `.env` not ignored, missing `.gitignore`.
- Zombie warning for repos that hold a port but have no recent commits.
- Projects inside repo subfolders are listed with their run commands.
- Forgotten work per repo: stashes, branches that only exist locally or are not merged, extra worktrees. Filter chips, row tags and a detail section.
- Commit graph of all branches in a modal; click a branch to jump to its tip.
- Open a repo in your editor, terminal or file manager. Settings detects installed editors and terminals and remembers your choice (`GITROSTER_EDITOR` still works as a fallback).
- Repo detail page: overview, files, history with commit diffs, branches, dependencies.
- Search across all repos (code, file names, commit messages), cross-repo dependency view with version drift.
- Related repos: duplicate clones of one remote, and local packages that depend on each other.
- Light, dark and system theme, chosen in Settings.
- Settings opens instantly: editors and terminals are detected in the background (PATH is listed once instead of probed per command, 3.7 s to 0.7 s on WSL).
- Markdown export of the whole inventory (`/api/export.md`, Export button).

## 0.1.0

- Scan folders for git repos, Python venvs / conda envs.
- Match listening ports and Docker containers to repos (by working directory, then command line).
- Repo kind: mine, fork, clone or local.
- Repo status: uncommitted changes, unpushed commits, dormant, no remote.
- Detect setup and run commands (npm/pnpm/yarn, Python, Cargo, Go, Flutter, Make, Docker Compose, Wrangler) plus commands and expected ports from the README.
- Start a detected command, stop a listening process, and read the log, all with confirmation.
- Notes, pin and ignore per repo.
- Optional AI runbook through a local agent (`claude -p` by default).
