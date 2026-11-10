"""T04: Graph HTTP layer (FR-017..019, NFR-002, NFR-003)."""
from __future__ import annotations

import pytest
import requests

from lcars_dash import teams_ops
from . import teams_fakes as fk
from .teams_fakes import FakeResponse

G = teams_ops.GRAPH


def test_me_requested_once_across_calls(signed_in):
    signed_in.add("/me/chats", fk.page([]))
    teams_ops.chats()
    teams_ops.chats()
    assert signed_in.paths("/me") .count("/me") == 1


def test_get_only_headers_timeout_and_no_team_or_channel_paths(signed_in):
    cid = "19:abc@thread.v2"
    signed_in.add("/me/chats", fk.page([fk.chat_json(cid, members=[], last=fk.preview())]))
    signed_in.add(f"/me/chats/{cid}/messages", fk.page([fk.message_json()]))
    teams_ops.summary()
    assert signed_in.calls
    for c in signed_in.calls:
        assert c["method"] == "GET"
        assert c["headers"]["Authorization"] == "Bearer tok-silent" and c["headers"]["Accept"] == "application/json"
        assert c["timeout"] == teams_ops.TIMEOUT
        assert "/teams/" not in c["url"] and "/channels/" not in c["url"]
    assert signed_in.other_verb_calls == []


def test_chat_and_message_request_parameters(signed_in):
    signed_in.add("/me/chats", fk.page([]))
    signed_in.add("/me/chats/19:x@thread.v2/messages", fk.page([]))
    teams_ops.chats(500)
    teams_ops.messages("19:x@thread.v2", 500)
    chat_call = [c for c in signed_in.calls if c["url"].endswith("/me/chats")][0]
    assert chat_call["params"]["$top"] == 50
    assert chat_call["params"]["$expand"] == "members,lastMessagePreview"
    assert chat_call["params"]["$orderby"] == "lastMessagePreview/createdDateTime desc"
    msg_call = [c for c in signed_in.calls if c["url"].endswith("/messages")][0]
    assert msg_call["params"] == {"$top": 50, "$orderby": "createdDateTime desc"}


def test_foreign_next_link_rejected_and_token_not_sent(signed_in):
    signed_in.add("/me/chats", fk.page([fk.chat_json("c1")], next_link="https://evil.example/steal"))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops.chats(100)
    assert "non-Graph URL" in str(exc.value)
    assert all(c["url"].startswith(G) for c in signed_in.calls)


def test_next_link_lookalike_host_rejected(signed_in):
    signed_in.add("/me/chats", fk.page([fk.chat_json("c1")], next_link="https://graph.microsoft.com.evil.net/v1.0/x"))
    with pytest.raises(teams_ops.TeamsError):
        teams_ops.chats(100)


def test_team_and_channel_urls_refused(signed_in):
    for url in ("/teams/abc/channels", "/chats/x/channels/y"):
        with pytest.raises(teams_ops.TeamsError) as exc:
            teams_ops._get(url)
        assert "not allowed" in str(exc.value)
    assert signed_in.paths("/teams") == []


@pytest.mark.parametrize("bad", ["", "a b", "../x", "x/y", "x" * 401, "x?y"])
def test_invalid_chat_id_rejected_without_http(bad, signed_in):
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops.messages(bad)
    assert "Invalid chat id" in str(exc.value)
    assert signed_in.calls == []


def test_chat_id_is_percent_encoded_safely():
    assert teams_ops._chat_path("19:abc@thread.v2") == "19:abc@thread.v2"
    assert teams_ops._chat_path("a=b_c-d.e") == "a=b_c-d.e"


def test_401_refreshes_token_then_succeeds(signed_in, fake_msal):
    signed_in.add("/me", FakeResponse(401, {}), fk.me_json())
    assert teams_ops._me()["id"] == fk.ME_ID
    assert [c["force_refresh"] for c in fake_msal.silent_calls] == [False, True]


def test_401_twice_removes_account_and_requires_sign_in(signed_in, fake_msal):
    signed_in.add("/me", FakeResponse(401, {}))
    fake_msal.silent_results[:] = [{"access_token": "tok-silent"}, {"access_token": "tok-silent"}, None]
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops._me()
    assert fake_msal.removed == [{"home_account_id": "acct-1"}]
    fake_msal.complete_event.set()


def test_403_message(signed_in):
    signed_in.add("/me", FakeResponse(403, {"error": {"message": "nope"}}))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._me()
    assert "denied access (403)" in str(exc.value) and "Chat.Read consent is missing" in str(exc.value)


def test_429_retry_after_then_success(signed_in, sleeps):
    signed_in.add("/me", FakeResponse(429, {}, headers={"Retry-After": "3"}), fk.me_json())
    assert teams_ops._me()["id"] == fk.ME_ID
    assert sleeps == [3]


def test_retry_after_capped_and_default(signed_in, sleeps):
    signed_in.add("/me", FakeResponse(429, {}, headers={"Retry-After": "99"}), fk.me_json())
    teams_ops._me()
    teams_ops._reset()
    signed_in.add("/me", FakeResponse(503, {}, headers={"Retry-After": "soon"}), fk.me_json())
    teams_ops._me()
    assert sleeps == [10, 2]


def test_429_twice_is_throttling_error(signed_in, sleeps):
    signed_in.add("/me", FakeResponse(429, {}, headers={"Retry-After": "1"}))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._me()
    assert "Teams is throttling requests, try again later" in str(exc.value)
    assert sleeps == [1]


@pytest.mark.parametrize("exc_type", [requests.Timeout, requests.ConnectionError])
def test_network_errors(exc_type, signed_in):
    signed_in.add("/me", exc_type("slow"))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._me()
    assert "Cannot reach Microsoft Graph" in str(exc.value)


def test_invalid_json_and_non_dict(signed_in):
    signed_in.add("/me", fk.invalid_json_response())
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._me()
    assert "invalid response" in str(exc.value)
    signed_in.add("/me", FakeResponse(200, [1]))
    with pytest.raises(teams_ops.TeamsError):
        teams_ops._me()


def test_other_status_includes_truncated_message(signed_in):
    signed_in.add("/me", FakeResponse(500, {"error": {"message": "x" * 500}}))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._me()
    assert str(exc.value).startswith("Microsoft Graph error 500: xxx") and len(str(exc.value)) < 260


def test_status_falls_back_to_reason(signed_in):
    signed_in.add("/me", FakeResponse(502, fk.invalid_json_response()._json, reason="Bad Gateway"))
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops._me()
    assert "Bad Gateway" in str(exc.value)


def test_400_is_bad_request(signed_in):
    signed_in.add("/me", FakeResponse(400, {"error": {"message": "bad $expand"}}))
    with pytest.raises(teams_ops.TeamsBadRequest) as exc:
        teams_ops._me()
    assert "Microsoft Graph error 400: bad $expand" in str(exc.value)


def test_pagination_stops_at_max_pages_and_limit(signed_in):
    nxt = f"{G}/me/chats?page=2"
    signed_in.add("/me/chats", fk.page([fk.chat_json("a")], next_link=nxt))
    signed_in.add(nxt, fk.page([fk.chat_json("b")], next_link=nxt))
    rows = teams_ops.chats(100)
    assert len(signed_in.paths("/me/chats")) == teams_ops.MAX_PAGES
    assert len(rows) == teams_ops.MAX_PAGES
    signed_in.calls.clear()
    assert len(teams_ops.chats(2)) == 2
    assert len(signed_in.paths("/me/chats")) == 2


def test_sign_in_required_propagates_from_chats(fake_msal, write_config, graph):
    write_config()
    fake_msal.signed_out()
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops.chats()
    assert graph.calls == []
    fake_msal.complete_event.set()
