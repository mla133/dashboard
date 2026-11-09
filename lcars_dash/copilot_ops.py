"""Copilot CLI session history/usage (read-only) and launchers for editors/terminals."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

DB = Path.home() / ".copilot" / "session-store.db"
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def local_ts(ts: str | None) -> str:
    """ISO timestamp (UTC 'Z' or naive) -> local 'YYYY-MM-DD HH:MM'."""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (dt.astimezone() if dt.tzinfo else dt).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16].replace("T", " ")


def _conn() -> sqlite3.Connection:
    if not DB.exists():
        raise FileNotFoundError(f"{DB} not found")
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=5)


def sessions(limit: int = 300, under: Path | None = None) -> list[dict]:
    """Newest sessions first. `under` keeps only sessions whose cwd is inside that folder."""
    sql = ("SELECT s.id, s.cwd, s.repository, s.branch, s.summary, s.created_at, s.updated_at, "
           "(SELECT count(*) FROM turns t WHERE t.session_id = s.id) FROM sessions s ")
    args: list = []
    if under:
        sql += "WHERE lower(s.cwd) = ? OR lower(s.cwd) LIKE ? "
        base = str(under).lower().rstrip("\\/")
        args += [base, base + "\\%"]
    sql += "ORDER BY s.updated_at DESC LIMIT ?"
    args.append(limit)
    keys = ("id", "cwd", "repository", "branch", "summary", "created", "updated", "turns")
    with _conn() as c:
        return [dict(zip(keys, r)) for r in c.execute(sql, args)]


def detail(session_id: str) -> dict:
    with _conn() as c:
        row = c.execute("SELECT cwd, repository, branch, summary, created_at, updated_at FROM sessions WHERE id = ?",
                        (session_id,)).fetchone()
        cps = c.execute("SELECT checkpoint_number, title FROM checkpoints WHERE session_id = ? "
                        "ORDER BY checkpoint_number", (session_id,)).fetchall()
        turns = c.execute("SELECT turn_index, user_message FROM turns WHERE session_id = ? "
                          "ORDER BY turn_index DESC LIMIT 5", (session_id,)).fetchall()
        files = c.execute("SELECT file_path FROM session_files WHERE session_id = ? LIMIT 12", (session_id,)).fetchall()
        refs = c.execute("SELECT ref_type, ref_value FROM session_refs WHERE session_id = ? LIMIT 12",
                         (session_id,)).fetchall()
    return {"info": row, "checkpoints": cps, "turns": list(reversed(turns)),
            "files": [f[0] for f in files], "refs": refs}


def usage(days: int = 30) -> dict:
    """Aggregates over the last `days` days from assistant_usage_events."""
    since = f"-{int(days)} days"
    where = "substr(u.created_at, 1, 10) >= date('now', ?)"
    with _conn() as c:
        per_day = c.execute(
            f"SELECT substr(u.created_at,1,10) d, count(DISTINCT u.session_id), count(*), "
            f"coalesce(sum(u.input_tokens),0), coalesce(sum(u.output_tokens),0), coalesce(sum(u.request_multiplier),0) "
            f"FROM assistant_usage_events u WHERE {where} GROUP BY d ORDER BY d", (since,)).fetchall()
        per_model = c.execute(
            f"SELECT u.model, count(DISTINCT u.session_id), count(*), coalesce(sum(u.input_tokens),0), "
            f"coalesce(sum(u.output_tokens),0), coalesce(sum(u.request_multiplier),0) "
            f"FROM assistant_usage_events u WHERE {where} GROUP BY u.model ORDER BY 3 DESC", (since,)).fetchall()
        per_folder = c.execute(
            f"SELECT s.cwd, count(DISTINCT u.session_id), count(*), coalesce(sum(u.input_tokens + u.output_tokens),0) "
            f"FROM assistant_usage_events u JOIN sessions s ON s.id = u.session_id WHERE {where} "
            f"GROUP BY s.cwd", (since,)).fetchall()
        n_sessions = c.execute("SELECT count(*) FROM sessions WHERE substr(created_at,1,10) >= date('now', ?)",
                               (since,)).fetchone()[0]
    folders: dict[str, list] = {}  # merge cwd variants that differ only by case/slashes
    for cwd, ns, calls, toks in per_folder:
        key = Path(cwd or "?").name or str(cwd)
        row = folders.setdefault(key.lower(), [key, 0, 0, 0])
        row[1] += ns
        row[2] += calls
        row[3] += toks
    return {"days": days, "sessions": n_sessions, "per_day": per_day, "per_model": per_model,
            "per_folder": sorted(folders.values(), key=lambda r: -r[2])}


# --- launchers -----------------------------------------------------------

def _spawn(args: list[str], cwd: Path | None = None, console: bool = False) -> None:
    subprocess.Popen(args, cwd=str(cwd) if cwd else None, creationflags=NEW_CONSOLE if console else 0,
                     close_fds=True)


def open_vscode(path: Path) -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [shutil.which("code"), shutil.which("code.cmd"),
                  str(Path(local) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"),
                  r"C:\Program Files\Microsoft VS Code\bin\code.cmd"]
    code = next((c for c in candidates if c and Path(c).exists()), None)
    if not code:
        return "VS Code not found (add 'code' to PATH)"
    subprocess.Popen([code, str(path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return f"Opened {path.name} in VS Code"


def open_explorer(path: Path) -> str:
    os.startfile(str(path))  # noqa: S606 (Windows only)
    return f"Opened {path.name} in Explorer"


def open_copilot(path: Path, resume: str | None = None) -> str:
    """New PowerShell window running `copilot` (optionally resuming a session) in `path`."""
    cmd = "copilot" + (f" --resume {resume}" if resume else "")
    if not path.is_dir():
        return f"Folder not found: {path}"
    _spawn(["powershell", "-NoExit", "-Command", cmd], cwd=path, console=True)
    return f"Started `{cmd}` in {path}"
