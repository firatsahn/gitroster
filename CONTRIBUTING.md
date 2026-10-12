# Contributing

Thanks for helping. The project is small on purpose: standard library only, one HTML file, no build step.

```bash
git clone https://github.com/firatsahn/gitroster && cd gitroster
python3 -m unittest discover -s tests -v
python3 -m gitroster ~/projects     # run from source
python3 -m gitroster --demo         # sample repos, safe to click around
```

## Guidelines

- **No runtime dependencies.** If you think you need one, open an issue first.
- **Detection must be deterministic.** File checks, `git`, `ss` and `/proc` decide what is shown. AI output is optional and always labelled unverified.
- **Never delete or modify user files.** gitroster only reads; the one exception is starting and stopping processes you confirm.
- **Anything that runs or kills a process** must be confirmed in the UI and validated on the server against data the server produced.
- Add a test for every detector or endpoint you add. Tests build throwaway git repos in a temp folder, see `tests/test_gitroster.py`.

## Good first issues

- Detectors for more stacks (Ruby, PHP, Java, Deno, Bun, uv, Poetry). They live in `detect()` in `gitroster/scanner.py`.
- Run-in-terminal instead of background start.
- Try the Codex CLI and Gemini CLI summaries for real and report what breaks (see `gitroster/agent.py`).

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Please add a line to the Unreleased section of [CHANGELOG.md](CHANGELOG.md).
