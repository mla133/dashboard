"""T12: GUI smoke tests for the Teams pane and the HOME Teams box (FR-036, FR-030, FR-031, FR-037).

Skipped when Tk cannot open a display. All data sources are faked; no network, no Outlook/Gmail, no Mindchuk.
"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime

import pytest

from lcars_dash import config, copilot_ops, google_ops, home_ops, live_ops, outlook_ops, teams_ops

gui = pytest.importorskip("lcars_dash.gui")


def _chat(cid, title, unread=True, mentions=0):
    return {"id": cid, "title": title, "chat_type": "oneOnOne", "members": ["Alice", "Me"], "preview": "hello there",
            "sender": "Alice", "time": datetime(2026, 11, 10, 14, 30), "time_utc": None, "last_read_utc": None,
            "unread": unread, "web_url": "", "mentions": mentions, "mentions_capped": False}


def _summary():
    chats = [_chat("19:a", "[bold]Alice", True, 1), _chat("19:b", "Bob", False)]
    return {"unread_chats": 1, "mentions": 1, "latest": chats, "chats": chats, "me": "Me", "capped": False,
            "loaded_at": datetime(2026, 11, 10, 9, 0, 0), "cache_notice": ""}


def _message(text="hi there"):
    return {"id": "m1", "time": datetime(2026, 11, 10, 14, 0), "time_utc": None, "sender": "Alice", "sender_id": "u",
            "text": text, "mentions_me": False, "deleted": False, "system": False}


@pytest.fixture(scope="module")
def _shared_app(tmp_path_factory):
    """One Dashboard for the whole module (creating several Tk roots in one process is unreliable on Windows).

    Every external source is faked; the Teams answer comes from `_FAKE["summary"]` so tests can change it.
    """
    mp = pytest.MonkeyPatch()
    mp.setattr(config, "CONFIG_FILE", tmp_path_factory.mktemp("cfg") / "lcars_dash.json")
    mp.setattr(teams_ops, "summary", _fake_summary)
    mp.setattr(teams_ops, "messages", lambda cid, limit=50: [_message()])
    mp.setattr(teams_ops, "auth_state", lambda: {"state": "idle", "user_code": "", "verification_uri": "",
                                                 "message": "", "error": "", "cache_notice": ""})
    mp.setattr(gui.Dashboard, "load_all", lambda self: None)
    mp.setattr(live_ops, "snapshot", lambda: [])
    mp.setattr(copilot_ops, "today_usage", lambda: {"sessions": 0, "calls": 0, "tokens": 0, "aic": 0.0, "models": []})
    mp.setattr(home_ops, "week_events", lambda ops: [])
    mp.setattr(outlook_ops, "mail", lambda *a, **kw: [])
    mp.setattr(google_ops, "mail", lambda *a, **kw: [])
    try:
        app = gui.Dashboard()
    except tk.TclError as e:
        mp.undo()
        pytest.skip(f"Tk unavailable: {e}")
    yield app
    try:
        app.destroy()
    except tk.TclError:
        pass
    mp.undo()


_FAKE: dict = {"summary": None}


def _fake_summary(*a, **kw):
    s = _FAKE["summary"]
    if isinstance(s, Exception):
        raise s
    return s if s is not None else _summary()


@pytest.fixture
def make_app(_shared_app):
    """Reset the shared app to a clean state and choose what the faked teams_ops.summary returns."""
    def build(summary=None):
        app = _shared_app
        _FAKE["summary"] = summary
        app.teams.token += 1  # discard any in-flight load
        app.teams.state, app.teams.last_load, app.teams.rows, app.teams.msg_cache = "idle", 0.0, {}, {}
        app.teams.tree.delete(*app.teams.tree.get_children())
        app.home.data.clear()
        app.home.last_load = 0.0
        app.home.teams_busy = False
        app.show_status()
        app.update()
        app.show_home()
        return app
    yield build
    _FAKE["summary"] = None


def pump(app, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.02)
    app.update()
    return cond()


def test_home_teams_box_mapped_and_last_in_tab_order(make_app):
    app = make_app()
    app.geometry("1500x940+20+20")
    assert pump(app, lambda: isinstance(app.home.data.get("teams"), dict))
    app.update()
    home = app.home
    assert home.order[-1] is home.teams_box
    for t in home.order:
        assert t.winfo_ismapped() and t.winfo_height() > 10, t
    text = home.teams_box.get("1.0", "end")
    assert "Unread chats: 1" in text and "Mentions: 1" in text
    assert "[bold]Alice" in text  # chat titles are plain text, never markup


def test_home_teams_box_not_configured_does_not_break_other_boxes(make_app):
    app = make_app(teams_ops.TeamsNotConfigured("missing file"))
    assert pump(app, lambda: isinstance(app.home.data.get("teams"), Exception))
    assert "Teams not configured" in app.home.teams_box.get("1.0", "end")
    assert pump(app, lambda: "mail_outlook" in app.home.data and "usage" in app.home.data)


def test_home_tab_cycle_reaches_teams_and_click_opens_tab(make_app):
    app = make_app()
    app.update()
    home = app.home
    home.cycle(home.order[-2], 1)
    app.focus_force()
    app.update()
    home.cycle(home.order[-2], 1)
    app.update()
    assert app.focus_get() is home.teams_box
    home.teams_box.event_generate("<Button-1>")
    app.update()
    assert app.view == "teams"


def test_show_teams_loaded_state_and_messages(make_app):
    app = make_app()
    app.show_teams()
    pane = app.teams
    assert pump(app, lambda: pane.state == "loaded")
    assert len(pane.tree.get_children()) == 2
    assert pane.tree.selection() == ("19:a",)
    pane._load_messages()
    assert pump(app, lambda: "hi there" in pane.view.get("1.0", "end"))
    assert "Alice" in pane.view.get("1.0", "end")
    assert "TEAMS" in app.HELP["teams"][0]


def test_show_teams_not_configured_state(make_app):
    app = make_app(teams_ops.TeamsNotConfigured("missing file"))
    app.show_teams()
    pane = app.teams
    assert pump(app, lambda: pane.state == "error")
    assert "TEAMS NOT CONFIGURED" in pane.view.get("1.0", "end")
    assert not pane.tree.get_children()


def test_show_teams_signin_state_and_other_tabs_usable(make_app):
    err = teams_ops.TeamsSignInRequired("Go to the page")
    err.user_code, err.verification_uri = "ABC123", "https://microsoft.com/devicelogin"
    app = make_app(err)
    app.show_teams()
    pane = app.teams
    assert pump(app, lambda: pane.state == "signin")
    body = pane.view.get("1.0", "end")
    assert "ABC123" in body and "devicelogin" in body
    app.show_home()
    app.update()
    assert app.view == "home"
    app.show_teams()
    app.show_home()


def test_shift_f11_and_y_open_teams_and_gmail_f11_unchanged(make_app):
    app = make_app()
    app.update()
    app.show_status()
    app.update()
    app.focus_force()
    app.update()
    app.event_generate("<Shift-F11>")
    app.update()
    assert app.view == "teams"
    app.show_status()
    app.update()
    app.event_generate("<Key-y>")
    app.update()
    assert app.view == "teams"
    app.event_generate("<F11>")
    app.update()
    assert app.view == "google"


def test_theme_cycle_recolors_teams_without_error(make_app):
    app = make_app()
    app.show_teams()
    assert pump(app, lambda: app.teams.state == "loaded")
    app.cycle_theme()
    app.update()
    app.show_home()
    app.update()
    assert app.view == "home"
