# Changelog

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
