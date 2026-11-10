"""TDD-gate gap tests: conventions, config isolation, read-only guarantees, import/launch safety."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY_FILES = [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts]


def _bare_lf(p: Path) -> int:
    return len(re.findall(rb"(?<!\r)\n", p.read_bytes()))


@pytest.mark.parametrize("p", PY_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_python_files_are_crlf(p):
    assert _bare_lf(p) == 0


def test_user_theme_config_untouched():
    f = Path.home() / ".lcars_dash.json"
    if not f.exists():
        pytest.skip("no user config on this machine")
    assert json.loads(f.read_text(encoding="utf-8")) == {"theme": "DEEP SPACE 9"}


def _src(name: str) -> str:
    return (ROOT / "lcars_dash" / name).read_text(encoding="utf-8")


def test_teams_ops_never_references_mindchuk_or_write_verbs():
    s = _src("teams_ops.py")
    assert "mindchuk" not in s.lower()
    assert not re.search(r"requests\.(post|put|patch|delete|request)\b|\.session\(|Session\(", s)
    assert len(re.findall(r"requests\.get\(", s)) == 1


def test_teams_ui_code_does_not_call_mindchuk_in_teams_paths():
    for name in ("tui_panes.py", "gui.py"):
        s = _src(name)
        m = re.search(r"class Teams(View|Pane)\b.*?(?=\nclass |\Z)", s, re.S)
        assert m, name
        assert "mindchuk" not in m.group(0).lower()


def test_home_ops_teams_helpers_do_not_use_mindchuk():
    s = _src("home_ops.py")
    assert "mindchuk" not in s.lower()


def test_requirements_list_teams_dependencies():
    txt = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for dep in ("msal", "msal-extensions", "requests"):
        assert re.search(rf"^{re.escape(dep)}\b", txt, re.M), dep


def test_requested_scopes_exclude_write_permissions():
    from lcars_dash import teams_ops
    scopes = list(teams_ops.SCOPES)
    assert sorted(scopes) == ["Chat.Read", "User.Read"]


def test_entry_modules_import_cleanly_without_msal_or_network():
    code = (
        "import sys\n"
        "sys.modules['msal']=None; sys.modules['msal_extensions']=None\n"
        "import lcars_dash.teams_ops, lcars_dash.gui, lcars_dash.home_ops, lcars_dash.tui_panes\n"
        "import importlib.util as u\n"
        "assert u.find_spec('lcars_dash.app')\n"
        "print('OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_gui_and_app_expose_entry_points():
    from lcars_dash import app, gui
    assert callable(gui.main) and hasattr(app, "LcarsDash")
