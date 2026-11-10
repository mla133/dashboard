"""T04/T05: chat + message parsing, HTML stripping, summary (FR-013..017)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lcars_dash import teams_ops
from . import teams_fakes as fk
from .teams_fakes import FakeResponse

ME = fk.ME_ID


def members(*names):
    return [fk.member("Me Myself", ME)] + [fk.member(n, "u-" + n) for n in names]


def chats_with(g, *items):
    g.add("/me/chats", fk.page(list(items)))
    return teams_ops.chats()


# ---- FR-013 chats ------------------------------------------------------------------------------

def test_one_on_one_title_from_other_member_and_unread(signed_in):
    c = chats_with(signed_in, fk.chat_json("c1", "oneOnOne", members=members("Alice"),
                                           last=fk.preview("2026-11-10T14:30:00.1234567Z", "hello <b>x</b>", "Alice"),
                                           last_read="2026-11-10T10:00:00Z"))[0]
    assert c["title"] == "Alice" and c["chat_type"] == "oneOnOne"
    assert c["unread"] is True and c["sender"] == "Alice" and c["preview"] == "hello <b>x</b>"
    assert c["time_utc"] == datetime(2026, 11, 10, 14, 30, 0, 123456, tzinfo=timezone.utc)
    assert c["time"].tzinfo is None and c["web_url"].endswith("c1")
    assert c["mentions"] == 0 and c["mentions_capped"] is False
    assert c["members"] == ["Me Myself", "Alice"]


def test_group_with_topic_uses_topic(signed_in):
    c = chats_with(signed_in, fk.chat_json("c1", "group", topic="  Project X  ", members=members("A", "B"),
                                           last=fk.preview(), last_read="2026-11-10T14:30:00Z"))[0]
    assert c["title"] == "Project X" and c["unread"] is False  # read == preview time -> read


def test_group_without_topic_joins_others(signed_in):
    c = chats_with(signed_in, fk.chat_json("c1", "group", members=members("Bob", "Cy"), last=fk.preview()))[0]
    assert c["title"] == "Bob, Cy" and c["unread"] is True  # never read


def test_meeting_without_members_uses_type_label(signed_in):
    c = chats_with(signed_in, fk.chat_json("c1", "meeting", members=[], last=fk.preview()))[0]
    assert c["title"] == "Meeting chat"


def test_unknown_type_label_falls_back(signed_in):
    assert chats_with(signed_in, fk.chat_json("c1", "weird", members=[]))[0]["title"] == "weird"


def test_no_preview_is_read_and_empty(signed_in):
    c = chats_with(signed_in, fk.chat_json("c1", members=members("Al")))[0]
    assert (c["unread"], c["preview"], c["sender"], c["time"], c["time_utc"]) == (False, "", "", None, None)


def test_preview_deleted_event_and_html(signed_in):
    rows = chats_with(
        signed_in,
        fk.chat_json("d", members=[], last=fk.preview("2026-11-10T01:00:00Z", deleted=True)),
        fk.chat_json("e", members=[], last=fk.preview("2026-11-10T02:00:00Z", msg_type="systemEventMessage")),
        fk.chat_json("h", members=[], last=fk.preview("2026-11-10T03:00:00Z", "<p>a</p><p>b&nbsp;c</p>", html=True)))
    by = {c["id"]: c["preview"] for c in rows}
    assert by == {"d": "[deleted]", "e": "[event]", "h": "a b c"}


def test_chats_sorted_newest_first_none_last(signed_in):
    rows = chats_with(
        signed_in,
        fk.chat_json("none", members=[]),
        fk.chat_json("old", members=[], last=fk.preview("2026-11-01T00:00:00Z")),
        fk.chat_json("new", members=[], last=fk.preview("2026-11-09T00:00:00Z")))
    assert [c["id"] for c in rows] == ["new", "old", "none"]


def test_two_pages_followed(signed_in):
    nxt = f"{teams_ops.GRAPH}/me/chats?$skiptoken=2"
    signed_in.add("/me/chats", fk.page([fk.chat_json("a", members=[])], next_link=nxt))
    signed_in.add(nxt, fk.page([fk.chat_json("b", members=[])]))
    assert {c["id"] for c in teams_ops.chats(100)} == {"a", "b"}


def test_400_falls_back_to_members_endpoint_and_is_sticky(signed_in):
    signed_in.add("/me/chats",
                  FakeResponse(400, {"error": {"message": "expand"}}),
                  fk.page([fk.chat_json("a", members=None, last=fk.preview()),
                           fk.chat_json("t", topic="Topic", last=fk.preview())]))
    signed_in.add("/me/chats/a/members", {"value": [fk.member("Zed", "u-z"), fk.member("Me", ME)]})
    rows = teams_ops.chats()
    by = {c["id"]: c for c in rows}
    assert by["a"]["title"] == "Zed" and by["t"]["title"] == "Topic"
    assert signed_in.paths("/me/chats/t/members") == []  # topic set: no member lookup
    fallback_params = [c["params"] for c in signed_in.calls if c["url"].endswith("/me/chats")]
    assert fallback_params[0]["$expand"] == "members,lastMessagePreview" and fallback_params[1]["$expand"] == "lastMessagePreview"
    signed_in.calls.clear()
    teams_ops.chats()
    assert [c["params"]["$expand"] for c in signed_in.calls if c["url"].endswith("/me/chats")] == ["lastMessagePreview"]


# ---- FR-014 messages ---------------------------------------------------------------------------

CID = "19:abc@thread.v2"


def msgs(g, *items):
    g.add(f"/me/chats/{CID}/messages", fk.page(list(items)))
    return teams_ops.messages(CID)


def test_messages_oldest_first_text_and_html(signed_in):
    rows = msgs(signed_in,
                fk.message_json("2", "2026-11-10T15:00:00Z", "<p>second</p>", "Bob", html=True),
                fk.message_json("1", "2026-11-10T14:00:00Z", "first", "Alice"))
    assert [m["id"] for m in rows] == ["1", "2"]
    assert (rows[0]["text"], rows[0]["sender"], rows[0]["sender_id"]) == ("first", "Alice", "u-Alice")
    assert rows[1]["text"] == "second" and rows[0]["time"] < rows[1]["time"]


def test_mention_me_vs_other(signed_in):
    rows = msgs(signed_in,
                fk.message_json("1", "2026-11-10T14:00:00Z", mentions=[fk.mention(ME)]),
                fk.message_json("2", "2026-11-10T15:00:00Z", mentions=[fk.mention("someone-else")]))
    assert [m["mentions_me"] for m in rows] == [True, False]


def test_system_and_deleted(signed_in):
    rows = msgs(signed_in,
                fk.message_json("s", "2026-11-10T14:00:00Z", "joined", msg_type="systemEventMessage"),
                fk.message_json("d", "2026-11-10T15:00:00Z", "secret", deleted=True, mentions=[fk.mention(ME)]))
    s, d = rows
    assert (s["text"], s["system"], s["sender"], s["mentions_me"]) == ("[event]", True, "", False)
    assert (d["text"], d["deleted"], d["mentions_me"]) == ("[deleted]", True, False)


def test_attachment_only_message(signed_in):
    rows = msgs(signed_in, fk.message_json("a", text="", html=True, attachments=[{"id": "1"}]))
    assert rows[0]["text"] == "[attachment]"


def test_sender_fallbacks_and_missing_time():
    assert teams_ops._sender({"application": {"displayName": "Bot"}}) == "Bot"
    assert teams_ops._sender({"device": {"displayName": "Dev"}}) == "Dev"
    assert teams_ops._sender(None) == "" and teams_ops._sender({"user": None}) == ""
    m = teams_ops._parse_message({"id": "x", "body": {"content": "t", "contentType": "text"}}, ME)
    assert m["time"] is None and m["sender"] == "" and m["text"] == "t"


@pytest.mark.parametrize("s,expect", [(None, None), ("", None), ("garbage", None), (5, None)])
def test_parse_utc_invalid(s, expect):
    assert teams_ops._parse_utc(s) is expect


def test_parse_utc_naive_assumed_utc():
    assert teams_ops._parse_utc("2026-11-10T10:00:00").tzinfo == timezone.utc


# ---- FR-015 html_to_text -----------------------------------------------------------------------

H = teams_ops.html_to_text


@pytest.mark.parametrize("src,expect", [
    ("a<br>b<br/>c", "a\nb\nc"),
    ("<p>one</p><p>two</p>", "one\ntwo"),
    ("<div>x</div><div>y</div>", "x\ny"),
    ("<ul><li>a</li><li>b</li></ul>", "a\nb"),
    ("Tom &amp; Jerry &lt;3 &quot;q&quot;", 'Tom & Jerry <3 "q"'),
    ("&lt;b&gt;bold&lt;/b&gt;", "<b>bold</b>"),
    ('hi <at id="0">Ann <b>Lee</b></at>!', "hi @Ann Lee!"),
    ('<img src="x.png" alt="pic">', "[image]"),
    ('look <attachment id="abc"></attachment>', "look [attachment]"),
    ('<attachment id="abc"/>', "[attachment]"),
    ('ok <emoji id="x" alt="😀" title="smile"></emoji>', "ok 😀"),
    ("a<br><br><br><br>b", "a\n\nb"),
    ("<script>alert(1)</script><style>p{}</style>text", "text"),
    ("x\xa0y", None),
    ("bad\x1b[31mred\x00\x07", "bad[31mred"),
])
def test_html_table(src, expect):
    if expect is None:
        expect = "x y"
    assert H(src) == expect


def test_plain_passthrough_and_no_tag_stripping():
    assert H("a <b> c &amp; d", "text") == "a <b> c &amp; d"
    assert H("line1\r\nline2  \n\n\n\nline3", "text") == "line1\nline2\n\nline3"
    assert H("\x1b[2Jhi", "text") == "[2Jhi"


def test_none_and_empty():
    assert H(None) == "" and H("") == ""


def test_single_line_collapses_whitespace():
    assert H("<p>a</p>\n<p>b   c</p>", single_line=True) == "a b c"


# ---- FR-016 summary ----------------------------------------------------------------------------

def three_chat_setup(g):
    """3 chats: c1 (2 unread, 2 mentions of me + 1 of other), c2 unread (no mention), c3 read."""
    g.add("/me/chats", fk.page([
        fk.chat_json("c1", members=members("Al"), last=fk.preview("2026-11-10T14:00:00Z"), last_read="2026-11-10T09:00:00Z"),
        fk.chat_json("c2", members=members("Bo"), last=fk.preview("2026-11-10T13:00:00Z"), last_read="2026-11-10T09:00:00Z"),
        fk.chat_json("c3", members=members("Cy"), last=fk.preview("2026-11-10T12:00:00Z"), last_read="2026-11-10T12:00:00Z")]))
    g.add("/me/chats/c1/messages", fk.page([
        fk.message_json("a", "2026-11-10T14:00:00Z", mentions=[fk.mention(ME)]),
        fk.message_json("b", "2026-11-10T13:30:00Z", mentions=[fk.mention(ME)]),
        fk.message_json("c", "2026-11-10T13:00:00Z", mentions=[fk.mention("other")]),
        fk.message_json("old", "2026-11-10T08:00:00Z", mentions=[fk.mention(ME)])]))  # before last read: not counted
    g.add("/me/chats/c2/messages", fk.page([fk.message_json("d", "2026-11-10T13:00:00Z")]))


def test_summary_counts(signed_in):
    three_chat_setup(signed_in)
    s = teams_ops.summary()
    assert (s["unread_chats"], s["mentions"], s["capped"]) == (2, 2, False)
    assert s["me"] == "Me Myself" and [c["id"] for c in s["latest"]] == ["c1", "c2", "c3"]
    assert [c["mentions"] for c in s["chats"]] == [2, 0, 0]
    assert isinstance(s["loaded_at"], datetime)
    assert signed_in.paths("/me/chats/c3/messages") == []  # read chats are never scanned


def test_summary_latest_limit(signed_in):
    three_chat_setup(signed_in)
    assert len(teams_ops.summary(latest=2)["latest"]) == 2


def test_summary_capped_when_more_than_15_unread(signed_in):
    items = [fk.chat_json(f"u{i}", members=[], last=fk.preview(f"2026-11-10T{i:02d}:00:00Z")) for i in range(16)]
    signed_in.add("/me/chats", fk.page(items))
    for i in range(16):
        signed_in.add(f"/me/chats/u{i}/messages", fk.page([]))
    s = teams_ops.summary()
    assert s["unread_chats"] == 16 and s["capped"] is True
    assert len(signed_in.paths("/me/chats/u")) == teams_ops.MAX_SCAN_CHATS


def test_summary_capped_when_scan_window_full(signed_in):
    signed_in.add("/me/chats", fk.page([fk.chat_json("c1", members=[], last=fk.preview("2026-11-10T14:00:00Z"),
                                                     last_read="2026-11-10T09:00:00Z")]))
    signed_in.add("/me/chats/c1/messages", fk.page([fk.message_json(f"m{i}", f"2026-11-10T1{i % 10}:00:00Z") for i in range(3)]))
    assert teams_ops.summary(scan=3)["capped"] is True
    teams_ops._reset()
    assert teams_ops.summary(scan=10)["capped"] is False


def test_summary_scan_error_is_best_effort_and_capped(signed_in):
    three_chat_setup(signed_in)
    signed_in.add("/me/chats/c1/messages", FakeResponse(500, {"error": {"message": "x"}}))
    s = teams_ops.summary()
    assert s["capped"] is True and s["chats"][0]["mentions"] == 0


def test_summary_sign_in_required_from_scan_reraised(signed_in, monkeypatch):
    three_chat_setup(signed_in)

    def boom(chat_id, limit=50):
        raise teams_ops.TeamsSignInRequired("C", "https://u", "m", 0)
    monkeypatch.setattr(teams_ops, "messages", boom)
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops.summary()


def test_summary_cache_max_age(signed_in):
    three_chat_setup(signed_in)
    first = teams_ops.summary(max_age=60)
    n = len(signed_in.calls)
    assert teams_ops.summary(max_age=60) is first and len(signed_in.calls) == n
    assert teams_ops.summary(max_age=0) is not first
    assert teams_ops.summary(latest=3, max_age=60) is not first  # different args


def test_summary_retry_clears_failed_state(fake_msal, write_config, graph):
    write_config()
    fake_msal.signed_out()
    fake_msal.complete_result = {"error": "authorization_declined"}
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops.summary()
    fake_msal.complete_event.set()
    import time
    for _ in range(300):
        if teams_ops.auth_state()["state"] == "failed":
            break
        time.sleep(0.01)
    with pytest.raises(teams_ops.TeamsError) as exc:
        teams_ops.summary()
    assert "press r to retry" in str(exc.value)
    fake_msal.complete_event.clear()
    with pytest.raises(teams_ops.TeamsSignInRequired):
        teams_ops.summary(retry=True)
    assert len(fake_msal.flow_calls) == 2
    fake_msal.complete_event.set()


def test_summary_surfaces_cache_notice(signed_in):
    signed_in.add("/me/chats", fk.page([]))
    assert teams_ops.summary()["cache_notice"].startswith("Teams token cache unavailable")
