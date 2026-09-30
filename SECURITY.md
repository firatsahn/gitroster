# Security

gitroster runs a local web server that can start and stop processes on your machine, so it is built defensively:

- Binds to `127.0.0.1` only. Do not put it behind a proxy or tunnel.
- Rejects requests whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding).
- POST requests must carry a same-origin `Origin` header, so other websites cannot trigger actions.
- `Start` only runs commands the scanner itself detected for a scanned repo. Arbitrary commands are refused.
- `Stop` only signals processes that are currently listening on a port.
- The AI feature sends the README, file names and detected commands to the agent command you configure. Nothing is sent unless you press the button.

Report vulnerabilities privately through GitHub's "Report a vulnerability" on the repository's Security tab.
