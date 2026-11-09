"""Per-repository test runner: detect a test command, run it, remember the last result."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from . import config

RESULTS_FILE = Path.home() / ".lcars_dash_tests.json"
TIMEOUT = 900


def detect(path: Path, name: str = "") -> str | None:
    """Command line to run this repo's tests, or None. Override via config "test_commands"."""
    override = config.test_commands().get(name) or config.test_commands().get(path.name)
    if override:
        return override
    has = lambda *names: any((path / n).exists() for n in names)  # noqa: E731
    if has("pytest.ini", "conftest.py") or (path / "tests").is_dir() and any((path / "tests").glob("test_*.py")):
        return "python -m pytest -q"
    if has("pyproject.toml") and "pytest" in (path / "pyproject.toml").read_text(encoding="utf-8", errors="ignore"):
        return "python -m pytest -q"
    pkg = path / "package.json"
    if pkg.exists():
        try:
            test = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}).get("test", "")
        except (OSError, ValueError):
            test = ""
        if test and "no test specified" not in test:
            return "npm test --silent"
    if any(path.glob("*.sln")) or any(path.glob("*[Tt]est*/*.csproj")) or any(path.glob("*.csproj")):
        return "dotnet test --nologo"
    mk = path / "Makefile"
    if mk.exists() and re.search(r"^test\s*:", mk.read_text(encoding="utf-8", errors="ignore"), re.M):
        return "make test"
    return None


def load_results() -> dict[str, dict]:
    try:
        data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run(path: Path, name: str) -> dict:
    """Run the repo's tests (blocking) and persist the result."""
    cmd = detect(path, name)
    if not cmd:
        return {"cmd": "", "rc": None, "when": datetime.now().isoformat(timespec="seconds"), "secs": 0,
                "tail": "No test command detected. Add one under \"test_commands\" in ~/.lcars_dash.json."}
    start = time.time()
    try:
        p = subprocess.run(cmd, cwd=path, shell=True, capture_output=True, text=True, timeout=TIMEOUT,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rc, text = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, text = -1, f"Timed out after {TIMEOUT}s"
    except OSError as e:
        rc, text = -1, str(e)
    res = {"cmd": cmd, "rc": rc, "when": datetime.now().isoformat(timespec="seconds"),
           "secs": round(time.time() - start, 1), "tail": "\n".join(text.strip().splitlines()[-40:])}
    data = load_results()
    data[str(path)] = res
    try:
        RESULTS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass
    return res


def label(res: dict | None) -> str:
    """Short text for the table: PASS / FAIL / NONE plus age."""
    if not res:
        return "-"
    if res.get("rc") is None:
        return "N/A"
    try:
        mins = int((datetime.now() - datetime.fromisoformat(res["when"])).total_seconds() // 60)
    except (ValueError, KeyError):
        mins = 0
    age = f"{mins}m" if mins < 60 else f"{mins // 60}h" if mins < 1440 else f"{mins // 1440}d"
    return f"{'PASS' if res['rc'] == 0 else 'FAIL'} {age}"
