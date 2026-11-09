"""Live view of running Copilot CLI sessions, derived from ~/.copilot/session-state (read-only)."""
from __future__ import annotations

import ctypes
import re
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path.home() / ".copilot" / "session-state"
TAIL_BYTES = 2_000_000
BLOCKS = "▁▂▃▄▅▆▇█"
NOISE = ("hook.start", "hook.end")  # emitted around every tool call; would swamp the activity signal
WAIT_AFTER_S = 45  # a "working" session silent this long is probably waiting on a permission/user prompt
_TYPE = re.compile(r'^\{"type":"([^"]+)"')
_TS = re.compile(r'"timestamp":"([^"]+)"\s*[,}]')
_TOOL = re.compile(r'"toolName":"([^"]+)"')
_STILL_ACTIVE = 259


def pid_alive(pid: int) -> bool:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == _STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def _workspace(d: Path) -> dict:
    info: dict = {}
    try:
        for line in (d / "workspace.yaml").read_text(encoding="utf-8", errors="replace").splitlines():
            k, _, v = line.partition(":")
            if k in ("cwd", "name", "id"):
                info[k] = v.strip()
    except OSError:
        pass
    return info


def running() -> list[dict]:
    """Sessions with a live `inuse.<pid>.lock` (one per running copilot process)."""
    out = []
    if not STATE_DIR.is_dir():
        return out
    for d in STATE_DIR.iterdir():
        if not d.is_dir():
            continue
        pids = [int(m.group(1)) for f in d.glob("inuse.*.lock") if (m := re.fullmatch(r"inuse\.(\d+)\.lock", f.name))]
        pids = [p for p in pids if pid_alive(p)]
        if pids:
            out.append({"id": d.name, "dir": d, "pid": pids[0], **_workspace(d)})
    return out


def _parse_ts(ts: str) -> float | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _tail_events(path: Path) -> list[tuple[str, float | None, str]]:
    """(type, epoch seconds, raw line) for the last ~2 MB of events."""
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        raw = f.read()
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]  # first line is cut off
    events = []
    for line in lines:
        t = _TYPE.match(line)
        if not t:
            continue
        m = _TS.search(line[-200:])
        events.append((t.group(1), _parse_ts(m.group(1)) if m else None, line))
    return events


def _state(events, now: float) -> tuple[str, str, float | None]:
    """(state, detail, seconds since last activity) from the newest meaningful event."""
    for typ, ts, line in reversed(events):
        # model.* and usage events are logged after assistant.turn_end too, so they say nothing about busy/idle
        if typ in NOISE or typ.startswith(("session.usage", "model.")) or typ == "session.binary_asset":
            continue
        age = now - ts if ts else None
        if typ in ("assistant.turn_end", "session.task_complete", "session.idle", "abort"):
            return "IDLE", "", age
        detail = ""
        if typ == "tool.execution_start":
            m = _TOOL.search(line)
            detail = m.group(1) if m else "tool"
        if age is not None and age > WAIT_AFTER_S:
            return "WAITING?", detail, age
        return "WORKING", detail or ("thinking" if typ.startswith(("model.", "assistant.", "user.")) else typ), age
    return "IDLE", "", None


def snapshot(window_s: int = 600, bucket_s: int = 10, now: float | None = None) -> list[dict]:
    """One row per running session: state, last activity and per-bucket event counts (oldest first)."""
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    n = window_s // bucket_s
    rows = []
    for s in running():
        counts = [0] * n
        state, detail, age = "IDLE", "", None
        try:
            events = _tail_events(s["dir"] / "events.jsonl")
            for typ, ts, _ in events:
                if ts is None or typ in NOISE:
                    continue
                i = int((now - ts) // bucket_s)
                if 0 <= i < n:
                    counts[n - 1 - i] += 1
            state, detail, age = _state(events, now)
        except OSError:
            pass
        cwd = s.get("cwd", "")
        rows.append({"id": s["id"], "pid": s["pid"], "name": s.get("name") or "(unnamed)",
                     "folder": Path(cwd).name if cwd else "?", "cwd": cwd, "state": state, "detail": detail,
                     "age": age, "counts": counts, "total": sum(counts)})
    rows.sort(key=lambda r: (r["age"] is None, r["age"] or 0))
    return rows


def sparkline(counts: list[int]) -> str:
    peak = max(counts, default=0)
    if not peak:
        return "·" * len(counts)
    return "".join("·" if c == 0 else BLOCKS[min(len(BLOCKS) - 1, max(0, round(c / peak * (len(BLOCKS) - 1))))]
                   for c in counts)


def age_label(age: float | None) -> str:
    if age is None:
        return "-"
    age = int(max(age, 0))
    return f"{age}s" if age < 60 else f"{age // 60}m" if age < 3600 else f"{age // 3600}h"
