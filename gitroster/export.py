"""Markdown export of the whole inventory."""
import time


def _home(p):
    import os
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if p.startswith(h) else p


def markdown(scan, meta):
    repos = [r for r in scan.get("repos", []) if not meta.get(r["path"], {}).get("ignored")]
    out = [f"# Repo inventory", "", f"{len(repos)} repos, scanned {time.strftime('%Y-%m-%d %H:%M', time.localtime(scan.get('scanned', time.time())))}", ""]
    for r in repos:
        m = meta.get(r["path"], {})
        out += [f"## {r['name']}", "",
                f"- path: `{_home(r['path'])}`",
                f"- kind: {r['kind']}" + (f" · remote: {r['remote']}" if r.get("remote") else ""),
                f"- stack: {', '.join(r['stack']) or '-'}"]
        if r.get("summary"):
            out.append(f"- about: {r['summary']}")
        if m.get("note"):
            out.append(f"- note: {m['note']}")
        if r.get("setup"):
            out.append("- setup: " + "; ".join(f"`{c}`" for c in r["setup"]))
        if r.get("run"):
            out.append("- run: " + "; ".join(f"`{c}`" for c in r["run"]))
        if r.get("ports"):
            out.append("- ports: " + ", ".join(str(p) for p in r["ports"]))
        w = r.get("work") or {}
        if w.get("stashes"):
            out.append(f"- stashes: {len(w['stashes'])}")
        for b in w.get("branches", []):
            out.append(f"- branch `{b['name']}`: {b['state']}" + (f" (ahead {b['ahead']})" if b["ahead"] else ""))
        for t in w.get("worktrees", []):
            out.append(f"- worktree `{t['path']}` ({t['branch'] or 'detached'})" + (" MISSING" if t["missing"] else ""))
        for h in r.get("health", []):
            out.append(f"- WARNING: {h['text']}" + (f" ({', '.join(h['files'])})" if h["files"] else ""))
        out.append("")
    return "\n".join(out)
