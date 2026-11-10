"""Regression tests for the security review findings SEC-001..SEC-005."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

import pytest
from rich.text import Text

from lcars_dash import teams_ops
from lcars_dash.tui_panes import TeamsView
from . import teams_fakes as fk
from .test_tui_teams_smoke import SIZE, _summary, quiet_ops  # noqa: F401  (fixture re-export)

ATTACKS = [
    "A\x1b]0;PWNED\x07B",          # OSC ended with BEL
    "A\x1b]52;c;ZXZpbA==\x1b\\B",  # OSC 52 ended with ST
    "A\x9b31mB",                   # C1 CSI
    "A\u202eB",                    # right-to-left override
    "A\u2066B\u2069",              # bidi isolates
]
BAD = "\x1b\x9b\x07\u202e\u2066\u2069\x9c"


def _clean(s: str) -> bool:
    return not any(ch in s for ch in BAD)


@pytest.mark.parametrize("attack", ATTACKS)
def test_clean_text_removes_controls_and_bidi(attack):
    assert _clean(teams_ops.clean_text(attack))
    assert _clean(teams_ops.html_to_text(attack, "text"))


def test_clean_text_single_line_and_multiline():
    assert teams_ops.clean_text("a\nb\tc") == "a b c"
    assert teams_ops.clean_text("a\nb\tc", multiline=True) == "a\nb\tc"
    assert teams_ops.clean_text(None) == ""


@pytest.mark.parametrize("attack", ATTACKS)
def test_parse_chat_and_message_sanitised(attack):
    raw = fk.chat_json("19:x@thread.v2", chat_type="group", topic="T" + attack,
                       members=[fk.member("M" + attack, "u1")], last=fk.preview(sender="S" + attack, text="p" + attack))
    chat = teams_ops._parse_chat(raw, "me")
    for v in (chat["title"], chat["sender"], chat["preview"], *chat["members"]):
        assert _clean(v)
    chat2 = teams_ops._parse_chat(fk.chat_json("19:y@thread.v2", chat_type="group",
                                               members=[fk.member("N" + attack, "u1")]), "me")
    assert _clean(chat2["title"])
    msg = teams_ops._parse_message(fk.message_json(sender="S" + attack, text="t" + attack), "me")
    assert _clean(msg["sender"]) and _clean(msg["text"])


@pytest.mark.parametrize("attack", ATTACKS)
def test_graph_error_and_me_name_sanitised(signed_in, attack):
    signed_in.add("/me", fk.FakeResponse(200, {"id": "u", "displayName": "Me" + attack}))
    assert _clean(teams_ops._me()["name"])
    signed_in.add("/me/chats", fk.FakeResponse(500, {"error": {"message": "boom" + attack}}))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._get("/me/chats")
    assert _clean(str(exc.value)) and "boom" in str(exc.value)


@pytest.mark.parametrize("attack", ATTACKS)
def test_flow_reason_and_signin_fields_sanitised(attack):
    assert _clean(teams_ops._flow_reason({"error_description": "bad" + attack}))
    e = teams_ops.TeamsSignInRequired.from_flow({"user_code": "AB" + attack, "message": "m" + attack,
                                                 "verification_uri": "https://x" + attack})
    assert _clean(e.user_code) and _clean(e.message) and _clean(e.verification_uri) and _clean(str(e))


# ---- SEC-002 -------------------------------------------------------------------------------------

WORST = ["<emoji alt=\"" * 2300, "<at>" * 7000, "<script>" * 3500, "<style>" * 4000, "<attachment>" * 2500,
         "<a " * 9000, "<" * 28000, "<img " * 5600, "<at x=\"" * 4000]


@pytest.mark.parametrize("payload", WORST)
@pytest.mark.parametrize("single", [False, True])
def test_html_to_text_is_fast_on_hostile_input(payload, single):
    t0 = time.perf_counter()
    teams_ops.html_to_text(payload, "html", single)
    assert time.perf_counter() - t0 < 0.2


def test_html_to_text_caps_input_length():
    out = teams_ops.html_to_text("x" * 500_000, "html")
    assert len(out) <= teams_ops.MAX_BODY_CHARS


# ---- SEC-004 -------------------------------------------------------------------------------------

def test_teams_status_line_is_not_parsed_as_markup(tmp_path, quiet_ops):
    from lcars_dash.app import LcarsDash

    async def go():
        app = LcarsDash()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            view = app.query_one(TeamsView)
            view.say("cache failed: [Errno 2] [/oops] [bold")  # would raise MarkupError if parsed
            await pilot.pause()
            from textual.widgets import Static
            status = view.query_one("#tm-status", Static)
            assert "[Errno 2]" in str(status.render())
    asyncio.run(go())


# ---- SEC-005 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://graph.microsoft.com/v1.0/Teams/x/Channels",
    "https://graph.microsoft.com/v1.0/me/Chats/x/CHANNELS/y",
    "https://graph.microsoft.com/v1.0/me/chats/../messages",
    "https://graph.microsoft.com/v1.0/me/chats/%2e%2e/messages",
    "https://graph.microsoft.com/v1.0/me/chats/a%2fb/messages",
    "https://graph.microsoft.com/v1.0/users/x/messages",
    "https://graph.microsoft.com/v1.0/mex",
    "https://graph.microsoft.com/v1.0/me/joinedTeams",   # SEC-007
    "https://graph.microsoft.com/v1.0/me/mailFolders",   # SEC-007
    "https://graph.microsoft.com/v1.0/me/chatsx",        # SEC-007
    "http://graph.microsoft.com/v1.0/me",
    "https://user@graph.microsoft.com/v1.0/me",
    "https://graph.microsoft.com:444/v1.0/me",
])
def test_get_guard_rejects_unsafe_urls(url, signed_in):
    with pytest.raises(teams_ops.TeamsError):
        teams_ops._get(url)
    assert signed_in.calls == []


def test_get_guard_allows_normal_paths(signed_in):
    signed_in.add("/me/chats", fk.page([]))
    assert teams_ops._get("https://graph.microsoft.com/v1.0/me/chats", {"$top": 1}) == {"value": []}


@pytest.mark.parametrize("bad", [".", "..", "...", "a/../b", "x..y/z"])
def test_chat_id_rejects_dot_ids(bad):
    with pytest.raises(teams_ops.TeamsError):
        teams_ops._chat_path(bad)
