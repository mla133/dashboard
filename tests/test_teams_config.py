"""T02: configuration, exceptions, lazy imports (FR-001..004, NFR-003)."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from lcars_dash import teams_ops
from . import teams_fakes as fk

PREFIX = "Teams not configured: create ~/.lcars_dash/teams_config.json"


def assert_not_configured(exc, reason):
    text = str(exc.value)
    assert text.startswith(PREFIX)
    assert "public client" in text and "device code" in text and "Chat.Read" in text
    assert f"Reason: {reason}" in text


@pytest.mark.parametrize("raw,reason", [
    (None, "file not found"),
    ("{not json", "invalid JSON"),
    ("[1, 2]", "not a JSON object"),
    ('{"tenant_id": "contoso.com"}', "missing client_id"),
    (json.dumps({"client_id": fk.GOOD_CLIENT_ID}), "missing tenant_id"),
    (json.dumps({"client_id": "  ", "tenant_id": "contoso.com"}), "missing client_id"),
    (json.dumps({"client_id": fk.GOOD_CLIENT_ID, "tenant_id": ""}), "missing tenant_id"),
    (json.dumps({"client_id": 5, "tenant_id": "contoso.com"}), "missing client_id"),
    (json.dumps({"client_id": "not-a-guid", "tenant_id": "contoso.com"}), "client_id is not a GUID"),
    (json.dumps({"client_id": fk.GOOD_CLIENT_ID, "tenant_id": "evil.com/../x?y"}), "tenant_id has invalid characters"),
])
def test_bad_config_raises_not_configured_without_http(raw, reason, write_config, fake_msal, graph):
    if raw is not None:
        write_config(raw=raw)
    with pytest.raises(teams_ops.TeamsNotConfigured) as exc:
        teams_ops.chats()
    assert_not_configured(exc, reason)
    assert graph.calls == [] and fake_msal.apps == []


def test_unreadable_config_reports_reason(write_config, monkeypatch):
    write_config()
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")))
    with pytest.raises(teams_ops.TeamsNotConfigured) as exc:
        teams_ops._load_config()
    assert "cannot read file: Permission denied" in str(exc.value)


def test_good_config_and_utf8_bom(write_config):
    path = write_config()
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert teams_ops._load_config() == (fk.GOOD_CLIENT_ID, fk.GOOD_TENANT_ID)


def test_domain_tenant_accepted(write_config):
    write_config(tenant_id="contoso.onmicrosoft.com")
    assert teams_ops._load_config()[1] == "contoso.onmicrosoft.com"


def test_config_read_at_call_time(write_config):
    write_config()
    teams_ops._load_config()
    write_config(client_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert teams_ops._load_config()[0] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_authority_and_client_id_reach_msal(signed_in, fake_msal):
    signed_in.add("/me/chats", fk.page([]))
    teams_ops.chats()
    app = fake_msal.apps[0]
    assert app.client_id == fk.GOOD_CLIENT_ID
    assert app.authority == f"https://login.microsoftonline.com/{fk.GOOD_TENANT_ID}"


def test_scopes_constant():
    assert teams_ops.SCOPES == ["Chat.Read", "User.Read"]


def test_import_safe_and_missing_msal(write_config, monkeypatch):
    monkeypatch.setitem(sys.modules, "msal", None)
    write_config()
    with pytest.raises(teams_ops.TeamsMissingLibrary) as exc:
        teams_ops.chats()
    assert "pip install msal msal-extensions requests" in str(exc.value)


def test_missing_requests(write_config, fake_msal, monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", None)
    write_config()
    with pytest.raises(teams_ops.TeamsMissingLibrary):
        teams_ops.chats()


def test_top_level_imports_are_stdlib_only_and_no_ui():
    tree = ast.parse(Path(teams_ops.__file__).read_text(encoding="utf-8"))
    top = {(n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
           for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in getattr(n, "names", [None])[:1]}
    assert not top & {"msal", "msal_extensions", "requests", "tkinter", "textual", "rich"}
    src = Path(teams_ops.__file__).read_text(encoding="utf-8")
    for ui in ("tkinter", "textual", "import rich", "from rich"):
        assert ui not in src


def test_only_get_verb_used_in_source():
    src = Path(teams_ops.__file__).read_text(encoding="utf-8")
    for verb in ("requests.post", "requests.put", "requests.patch", "requests.delete", "requests.request"):
        assert verb not in src


def test_non_teams_errors_are_wrapped(signed_in, monkeypatch):
    monkeypatch.setattr(teams_ops, "_me", lambda: (_ for _ in ()).throw(KeyError("boom")))
    with pytest.raises(teams_ops.TeamsError):
        teams_ops.chats()


def test_public_exceptions_hierarchy():
    for cls in (teams_ops.TeamsNotConfigured, teams_ops.TeamsMissingLibrary, teams_ops.TeamsSignInRequired,
                teams_ops.TeamsBadRequest):
        assert issubclass(cls, teams_ops.TeamsError)
