"""TUI smoke tests for the Teams view and HOME Teams box (headless Textual pilot, fakes only)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from lcars_dash import (config, copilot_ops, git_ops, google_ops, live_ops, outlook_ops, teams_ops)
from lcars_dash.app import LcarsDash
from lcars_dash.tui_home import GO, HomeView
from lcars_dash.tui_panes import TeamsView

SIZE = (160, 45)


def _chat(i: int, unread: bool, mentions: int, title: str) -> dict:
    t = datetime(2026, 11, 10, 9, i)
    return {"id": f"19:chat{i}@thread.v2", "title": title, "chat_type": "group", "members": ["Ann", "Bob"],
            "preview": "hello [bold]x[/bold]", "sender": "Ann", "time": t, "time_utc": t, "last_read_utc": None,
            "unread": unread, "web_url": "", "mentions": mentions, "mentions_capped": False}


def _summary() -> dict:
    chats = [_chat(1, True, 1, "Build [red]team[/red]"), _chat(2, True, 0, "Lunch"), _chat(3, False, 0, "Old")]
    return {"unread_chats": 2, "mentions": 1, "latest": chats[:5], "chats": chats, "me": "Me", "capped": False,
            "loaded_at": datetime(2026, 11, 10, 10, 0, 0), "cache_notice": ""}


def _messages(chat_id: str, limit: int = 50) -> list:
    t = datetime(2026, 11, 10, 9, 5)
    return [{"id": "m1", "time": t, "time_utc": t, "sender": "Ann", "sender_id": "u1", "text": "hi [b]there[/b]",
             "mentions_me": True, "deleted": False, "system": False}]


@pytest.fixture
def quiet_ops(monkeypatch):
    """Stub every data source so the app starts offline; returns a dict to configure Teams behaviour."""
    ctl = {"summary": teams_ops.TeamsNotConfigured("no file"), "calls": []}
    monkeypatch.setattr(git_ops, "discover_all", lambda *a, **k: [])
    monkeypatch.setattr(live_ops, "snapshot", lambda *a, **k: [])
    monkeypatch.setattr(copilot_ops, "today_usage",
                        lambda *a, **k: {"sessions": 0, "calls": 0, "tokens": 0, "aic": 0.0, "models": []})
    for mod in (outlook_ops, google_ops):
        monkeypatch.setattr(mod, "mail", lambda *a, **k: [])
        monkeypatch.setattr(mod, "events", lambda *a, **k: [])

    def summary(*a, **k):
        ctl["calls"].append(k)
        if isinstance(ctl["summary"], Exception):
            raise ctl["summary"]
        return ctl["summary"]
    monkeypatch.setattr(teams_ops, "summary", summary)
    monkeypatch.setattr(teams_ops, "messages", _messages)
    return ctl


def _run(tmp_path, scenario):
    async def go():
        app = LcarsDash([tmp_path])
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.3)
            await scenario(app, pilot)
    asyncio.run(go())


def test_open_teams_by_all_routes_not_configured(quiet_ops, tmp_path):
    async def scenario(app, pilot):
        await pilot.press("shift+f11")
        await pilot.pause(0.3)
        assert app.current_view == "teams"
        await pilot.press("escape")
        await pilot.pause()
        assert app.current_view == "status"
        await pilot.press("y")
        await pilot.pause(0.3)
        assert app.current_view == "teams"
        await pilot.press("f12")
        await pilot.pause(0.3)
        assert app.current_view == "home"
        await pilot.click("#n-teams")
        await pilot.pause(0.3)
        assert app.current_view == "teams"
        text = str(app.query_one("#tm-text").render())
        assert "TEAMS NOT CONFIGURED" in text
    _run(tmp_path, scenario)


def test_teams_loaded_rows_use_text_cells(quiet_ops, tmp_path):
    quiet_ops["summary"] = _summary()

    async def scenario(app, pilot):
        await pilot.press("shift+f11")
        await pilot.pause(0.6)
        view = app.query_one(TeamsView)
        assert view.state == "loaded"
        assert view.table.row_count == 3
        cell = view.table.get_row_at(0)[2]
        assert str(cell) == "Build [red]team[/red]"  # literal, not parsed as markup
        await pilot.pause(0.6)  # debounce + message load
        assert "hi [b]there[/b]" in str(app.query_one("#tm-text").render())
        await pilot.press("f5")  # theme cycle re-renders without crashing
        await pilot.pause(0.3)
        assert view.table.row_count == 3
    _run(tmp_path, scenario)


def test_sign_in_pending_keeps_other_tabs_usable(quiet_ops, tmp_path):
    flow = {"user_code": "ABC123", "verification_uri": "https://microsoft.com/devicelogin",
            "message": "go sign in", "expires_at": 9e12}
    quiet_ops["summary"] = teams_ops.TeamsSignInRequired.from_flow(flow)

    async def scenario(app, pilot):
        await pilot.press("shift+f11")
        await pilot.pause(0.5)
        view = app.query_one(TeamsView)
        assert view.state == "signin"
        text = str(app.query_one("#tm-text").render())
        assert "ABC123" in text and "devicelogin" in text
        await pilot.press("escape")
        await pilot.press("t")
        await pilot.pause(0.2)
        assert app.current_view == "terminal"
        await pilot.press("f12")
        await pilot.pause(0.2)
        assert app.current_view == "home"
    _run(tmp_path, scenario)


def test_home_teams_box_tab_enter_and_layout(quiet_ops, tmp_path):
    quiet_ops["summary"] = _summary()

    async def scenario(app, pilot):
        home = app.query_one(HomeView)
        assert list(GO)[-1] == "hm-teams"
        for _ in range(len(GO)):
            await pilot.press("tab")
            if app.focused is not None and app.focused.id == "hm-teams":
                break
        assert app.focused.id == "hm-teams"
        await pilot.pause(0.3)
        box_text = str(app.query_one("#hm-teams").render())
        assert "Unread chats: 2" in box_text
        for wid in list(GO) + ["hm-cal-outlook", "hm-cal-google"]:
            size = app.query_one(f"#{wid}").size
            assert size.width > 0 and size.height > 0, wid
        assert home.max_scroll_y == 0
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.current_view == "teams"
    _run(tmp_path, scenario)


def test_home_teams_failure_does_not_affect_other_boxes(quiet_ops, tmp_path):
    quiet_ops["summary"] = teams_ops.TeamsError("boom")

    async def scenario(app, pilot):
        await pilot.pause(0.3)
        assert "boom" in str(app.query_one("#hm-teams").render())
        assert app.query_one("#hm-usage").size.height > 0
    _run(tmp_path, scenario)


def test_works_without_msal_and_config_untouched(quiet_ops, monkeypatch, tmp_path):
    import sys
    monkeypatch.setitem(sys.modules, "msal", None)
    quiet_ops["summary"] = teams_ops.TeamsMissingLibrary("pip install msal msal-extensions requests")

    async def scenario(app, pilot):
        await pilot.press("shift+f11")
        await pilot.pause(0.4)
        assert "LIBRARIES MISSING" in str(app.query_one("#tm-text").render())
        await pilot.press("f5")
        await pilot.pause(0.2)
    _run(tmp_path, scenario)
    # theme saves went to the tmp file, never the real one
    assert config.CONFIG_FILE.parent == tmp_path
    assert json.loads(config.CONFIG_FILE.read_text("utf-8")).get("theme")
