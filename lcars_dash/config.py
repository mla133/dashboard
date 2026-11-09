"""User settings in ~/.lcars_dash.json (theme, repository roots, per-repo test commands)."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".lcars_dash.json"
DEFAULT_ROOTS = [Path.home() / "SoftwareDevelopment", Path.home() / "HomeDev"]


def load() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**changes) -> None:
    data = load()
    data.update(changes)
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def roots() -> list[Path]:
    """Configured repository roots ("roots": [...] in the config file), else the defaults."""
    raw = load().get("roots")
    paths = [Path(p).expanduser() for p in raw] if isinstance(raw, list) and raw else DEFAULT_ROOTS
    return [p for p in paths if p.is_dir()]


def test_commands() -> dict[str, str]:
    """Per-repo overrides: "test_commands": {"repo name": "command line"}."""
    raw = load().get("test_commands")
    return raw if isinstance(raw, dict) else {}
