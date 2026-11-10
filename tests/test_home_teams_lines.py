"""T06: home_ops Teams formatting helpers (FR-029, FR-022, FR-024, FR-032, NFR-008)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from lcars_dash import home_ops, teams_ops


def chat(title="Alice", unread=True, mentions=0, t=datetime(2026, 11, 10, 14, 30), sender="Alice", preview="hello"):
    return {"id": title, "title": title, "unread": unread, "mentions": mentions, "time": t, "sender": sender, "preview": preview}


def summ(chats, u=None, m=None, capped=False, notice=""):
    return {"unread_chats": sum(c["unread"] for c in chats) if u is None else u,
            "mentions": sum(c["mentions"] for c in chats) if m is None else m,
            "latest": chats[:5], "chats": chats, "capped": capped, "loaded_at": datetime(2026, 11, 10, 9, 5, 7),
            "cache_notice": notice}


def test_cells_variants():
    assert home_ops.teams_cells(chat(unread=True, mentions=2)) == ("*@", "11-10 14:30", "Alice", "Alice: hello")
    assert home_ops.teams_cells(chat(unread=False, t=None, sender="", preview="p")) == ("  ", "-", "Alice", "p")
    assert home_ops.teams_cells(chat(unread=False, mentions=1))[0] == " @"


def test_lines_loaded_tags_and_format():
    lines = home_ops.teams_lines(summ([chat("A", True, 1), chat("B", True, 0), chat("C", False, 0)]), 80)
    assert lines[0] == ("mention", "Unread chats: 2  //  Mentions: 1")
    assert [t for t, _ in lines[1:]] == ["mention", "unread", "row"]
    # row text goes through short() (like mail_lines), which collapses runs of spaces
    assert lines[1][1] == "*@ 11-10 14:30 A Alice: hello"
    assert lines[3][1] == "11-10 14:30 C Alice: hello"


def test_lines_header_tags():
    assert home_ops.teams_lines(summ([chat(unread=True)]), 80)[0][0] == "unread"
    assert home_ops.teams_lines(summ([chat(unread=False)]), 80)[0][0] == "dim"
    assert home_ops.teams_lines(summ([chat(mentions=1)], capped=True), 80)[0][1].endswith("Mentions: 1+")


def test_lines_empty_and_rows_limit():
    assert home_ops.teams_lines(summ([]), 80) == [("dim", "Unread chats: 0  //  Mentions: 0"), ("dim", "No chats")]
    many = summ([chat(f"T{i}") for i in range(8)])
    many["latest"] = many["chats"]
    assert len(home_ops.teams_lines(many, 80)) == 6


def test_lines_truncated_to_width_and_long_title():
    s = summ([chat("T" * 50, preview="p" * 200)])
    lines = home_ops.teams_lines(s, 40)
    assert all(len(text) <= 40 for _, text in lines) and lines[1][1].endswith("…")
    assert "T" * 20 not in home_ops.teams_lines(s, 200)[1][1]  # title shortened to 20 chars


def test_error_lines_not_configured():
    err = teams_ops.TeamsNotConfigured("file not found")
    assert home_ops.teams_error_lines(err, 80, True) == [("err", "Teams not configured - open TEAMS (y) for setup")]
    full = home_ops.teams_error_lines(err, 80, False)
    assert full[0] == ("h", "TEAMS NOT CONFIGURED") and all(t == "row" for t, _ in full[1:])
    assert any("Chat.Read" in x for _, x in full) and any(x == "Reason: file not found" for _, x in full)


def test_error_lines_missing_library():
    err = teams_ops.TeamsMissingLibrary("Teams libraries missing (msal): pip install msal msal-extensions requests")
    assert home_ops.teams_error_lines(err, 90, True) == [("err", "Teams libraries missing - pip install msal msal-extensions requests")]
    assert home_ops.teams_error_lines(err, 90, False) == [("h", "TEAMS LIBRARIES MISSING"), ("row", str(err))]


def test_error_lines_sign_in():
    err = teams_ops.TeamsSignInRequired("CODE1234", "https://microsoft.com/devicelogin", "go sign in", 0)
    assert home_ops.teams_error_lines(err, 80, True) == [
        ("unread", "Sign in: https://microsoft.com/devicelogin  code CODE1234"),
        ("dim", "Waiting for sign-in... (r to retry)")]
    full = home_ops.teams_error_lines(err, 80, False)
    assert full[0] == ("h", "SIGN IN TO MICROSOFT TEAMS")
    assert full[1] == ("row", "1. Open  https://microsoft.com/devicelogin")
    assert full[2] == ("mention", "2. Enter code  CODE1234")
    assert full[3][1].endswith("Chat.Read / User.Read") and full[4] == ("dim", "Waiting for sign-in... (r to retry)")
    assert full[5] == ("dim", "go sign in") and len(full) == 6


def test_error_lines_other():
    err = teams_ops.TeamsError("first line\nsecond line")
    assert home_ops.teams_error_lines(err, 80, True) == [("err", "Error: first line")]
    assert home_ops.teams_error_lines(err, 80, False) == [("err", "Error: first line\nsecond line")]
    assert len(home_ops.teams_error_lines(teams_ops.TeamsError("x" * 100), 20, True)[0][1]) == 20
    assert home_ops.teams_error_lines(ValueError("v"), 80, True) == [("err", "Error: v")]


def m(t, text, sender="Al", **kw):
    return {"time": t, "text": text, "sender": sender, "mentions_me": False, "deleted": False, "system": False, **kw}


def test_message_lines_day_headers_and_continuation():
    today = datetime.combine(date.today(), datetime.min.time()).replace(hour=9, minute=5)
    yday = today - timedelta(days=1)
    lines = home_ops.teams_message_lines([m(yday, "old"), m(today, "l1\nl2"), m(today, "me!", mentions_me=True)])
    assert lines[0] == ("h", f"{yday:%a %Y-%m-%d}")
    assert lines[1] == ("row", "09:05  Al: old")
    assert lines[2] == ("today", f"{today:%a %Y-%m-%d}  (today)")
    assert lines[3] == ("row", "09:05  Al: l1") and lines[4] == ("row", "       l2")
    assert lines[5] == ("mention", "09:05  Al: me!")


def test_message_lines_system_deleted_no_sender_no_time():
    t = datetime(2026, 1, 2, 3, 4)
    lines = home_ops.teams_message_lines([m(t, "[event]", "", system=True), m(t, "[deleted]", deleted=True), m(None, "x", "")])
    assert lines[1] == ("dim", "03:04  [event]") and lines[2][0] == "dim"
    assert lines[3] == ("row", "--:--  x") and len(lines) == 4


def test_message_lines_empty():
    assert home_ops.teams_message_lines([]) == [("dim", "No messages")]


def test_status_line():
    s = summ([chat("A", True, 1), chat("B", False, 0)])
    assert home_ops.teams_status(s) == "2 chat(s)  //  1 unread  //  1 mention(s)  //  loaded 09:05:07  //  r reload  l read  Esc back"
    out = home_ops.teams_status(summ([chat()], capped=True, notice="Teams token cache unavailable (x)"))
    assert out.endswith("  //  Teams token cache unavailable (x)") and "1+ mention(s)" not in out and "0+ mention(s)" in out


def test_existing_helpers_untouched():
    assert home_ops.mail_lines([], 40) == [("dim", "Inbox is empty")]
    assert home_ops.calendar_lines([], 40) == [("dim", "No events this work week")]
