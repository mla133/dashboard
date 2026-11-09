"""Thin wrapper around the `mindchuk` command-line tool (~/homedev/mindchuk)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path.home() / "homedev" / "mindchuk"
EXIT_MEANING = {1: "API failure or conflicting edit", 2: "usage error or empty input",
                3: "authentication failed (check MINDCHUK_EMAIL / MINDCHUK_PASSWORD)",
                4: "network failure", 5: "entry not found"}


class MindchukError(Exception):
    pass


def _command() -> tuple[list[str], Path | None]:
    exe = shutil.which("mindchuk") or str(Path.home() / ".local" / "bin" / "mindchuk.exe")
    if Path(exe).exists():
        return [exe], None
    if (REPO / "src").is_dir():
        import sys
        return [sys.executable, "-m", "mindchuk"], REPO / "src"
    raise MindchukError("mindchuk is not installed (pipx install ~/homedev/mindchuk)")


def run(*args: str, stdin: str | None = None, timeout: int = 60) -> str:
    cmd, pypath = _command()
    env = None
    if pypath:
        import os
        env = {**os.environ, "PYTHONPATH": str(pypath)}
    try:
        p = subprocess.run(
            [*cmd, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise MindchukError("timed out")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip().splitlines()
        detail = msg[-1] if msg else EXIT_MEANING.get(p.returncode, f"exit {p.returncode}")
        raise MindchukError(detail)
    return p.stdout


def list_entries(n: int = 50, include_archived: bool = False) -> list[tuple[str, str]]:
    args = ["list", "-n", str(n)] + (["--all"] if include_archived else [])
    rows = []
    for line in run(*args).splitlines():
        eid, _, title = line.partition("\t")
        if eid.strip():
            rows.append((eid.strip(), title.strip()))
    return rows


def show(eid: str) -> str:
    return run("show", "--id", eid)


def add(text: str) -> str:
    return run("add", "-", stdin=text).strip()


def append(eid: str, text: str) -> str:
    return run("append", "--id", eid, "-", stdin=text).strip()


def archive(eid: str, undo: bool = False) -> None:
    run("unarchive" if undo else "archive", "--id", eid)


def delete(eid: str) -> None:
    run("delete", "--id", eid, "--yes")
