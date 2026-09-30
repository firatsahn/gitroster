# Contributing

Thanks for helping. The project is small on purpose: standard library only, one HTML file, no build step.

```bash
git clone <repo> && cd gitroster
python3 -m unittest discover -s tests -v
python3 -m gitroster ~/projects     # run from source
```

## Guidelines

- **No runtime dependencies.** If you think you need one, open an issue first.
- **Detection must be deterministic.** File checks, `git`, `ss` and `/proc` decide what is shown. AI output is optional and always labelled unverified.
- **Never delete or modify user files.** The cleanup view only copies commands.
- **Anything that runs or kills a process** must be confirmed in the UI and validated on the server against data the server produced.
- Add a test for every detector or endpoint you add. Tests build throwaway git repos in a temp folder, see `tests/test_gitroster.py`.

## Good first issues

- Detectors for more stacks (Ruby, PHP, Java, Deno, Bun, uv, Poetry).
- macOS support for ports (`lsof` instead of `ss` and `/proc`).
- Detect projects that live in a subfolder of the repo.
- Run-in-terminal instead of background start.
