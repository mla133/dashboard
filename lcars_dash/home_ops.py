"""Shared data/formatting for the HOME pane and the TEAMS views (GUI and TUI)."""
from __future__ import annotations

from datetime import date, timedelta

from . import teams_ops
from .live_ops import short


def week_range(today: date | None = None) -> tuple[date, date]:
    """Monday-Friday of the current work week (the coming one on weekends)."""
    today = today or date.today()
    mon = today - timedelta(days=today.weekday()) if today.weekday() < 5 else today + timedelta(days=7 - today.weekday())
    return mon, mon + timedelta(days=4)


def week_events(ops) -> list[dict]:
    mon, fri = week_range()
    back = (date.today() - mon).days
    return [e for e in ops.events(5, back) if mon <= e["start"].date() <= fri]


def calendar_lines(events: list[dict], width: int) -> list[tuple[str, str]]:
    """(tag, text) lines grouped by day; tags: h (day), today, row, dim."""
    if not events:
        return [("dim", "No events this work week")]
    out, last = [], None
    for e in sorted(events, key=lambda e: e["start"]):
        d = e["start"].date()
        if d != last:
            last = d
            out.append(("today" if d == date.today() else "h", f"{d:%a %m-%d}" + ("  (today)" if d == date.today() else "")))
        when = "all day" if e["all_day"] else f"{e['start']:%H:%M}-{e['end']:%H:%M}"
        out.append(("row", short(f"  {when:<12}{e['subject']}", width)))
    return out


def mail_lines(rows: list[dict], width: int) -> list[tuple[str, str]]:
    """(tag, text) lines for recent inbox mail; tag is 'unread' or 'row'."""
    if not rows:
        return [("dim", "Inbox is empty")]
    return [("unread" if r["unread"] else "row",
             short(f"{'*' if r['unread'] else ' '} {r['received']:%m-%d %H:%M}  {short(r['from'], 20):<20}  {r['subject']}", width))
            for r in rows]


def _clip(text: str, width: int) -> str:
    """Truncate to width with an ellipsis, keeping inner spacing (unlike short())."""
    return text if len(text) <= width else text[:max(width - 1, 0)] + "…"


def teams_cells(chat: dict) -> tuple[str, str, str, str]:
    """(marker, time, title, last) for the TEAMS list; marker is '*' (unread) + '@' (unread message mentions you)."""
    marker = ("*" if chat["unread"] else " ") + ("@" if chat.get("mentions") else " ")
    when = f"{chat['time']:%m-%d %H:%M}" if chat.get("time") else "-"
    last = f"{chat['sender']}: {chat['preview']}" if chat.get("sender") else chat.get("preview", "")
    return marker, when, chat["title"], last


def teams_lines(summary: dict, width: int, rows: int = 5) -> list[tuple[str, str]]:
    """(tag, text) lines for the HOME Teams box; tags: mention, unread, row, dim."""
    u, m = summary["unread_chats"], summary["mentions"]
    head = f"Unread chats: {u}  //  Mentions: {m}{'+' if summary.get('capped') else ''}"
    out = [("mention" if m else "unread" if u else "dim", _clip(head, width))]
    latest = summary["latest"][:rows]
    if not latest:
        return out + [("dim", "No chats")]
    for c in latest:
        marker, when, title, last = teams_cells(c)
        out.append(("mention" if c.get("mentions") else "unread" if c["unread"] else "row",
                   short(f"{marker} {when:<11}  {short(title, 20):<20}  {last}", width)))
    return out


def teams_error_lines(err: BaseException, width: int, compact: bool) -> list[tuple[str, str]]:
    """State lines for an exception from teams_ops (compact = HOME box, full = TEAMS text pane)."""
    first = (str(err).splitlines() or [""])[0]
    if isinstance(err, teams_ops.TeamsNotConfigured):
        if compact:
            return [("err", short("Teams not configured - open TEAMS (y) for setup", width))]
        return [("h", "TEAMS NOT CONFIGURED")] + [("row", line) for line in str(err).splitlines()]
    if isinstance(err, teams_ops.TeamsMissingLibrary):
        if compact:
            return [("err", short("Teams libraries missing - pip install msal msal-extensions requests", width))]
        return [("h", "TEAMS LIBRARIES MISSING"), ("row", str(err))]
    if isinstance(err, teams_ops.TeamsSignInRequired):
        uri, code = err.verification_uri, err.user_code
        if compact:
            return [("unread", _clip(f"Sign in: {uri}  code {code}", width)),
                   ("dim", short("Waiting for sign-in... (r to retry)", width))]
        out = [("h", "SIGN IN TO MICROSOFT TEAMS"), ("row", f"1. Open  {uri}"), ("mention", f"2. Enter code  {code}"),
              ("row", "3. Sign in with your work account and accept Chat.Read / User.Read"),
              ("dim", "Waiting for sign-in... (r to retry)")]
        return out + ([("dim", err.message)] if err.message else [])
    if compact:
        return [("err", short(f"Error: {first}", width))]
    return [("err", f"Error: {err}")]


def teams_message_lines(messages: list[dict]) -> list[tuple[str, str]]:
    """(tag, text) lines for a chat transcript (oldest first) with a header per day."""
    if not messages:
        return [("dim", "No messages")]
    out, last = [], None
    for msg in messages:
        t = msg.get("time")
        if t is not None and t.date() != last:
            last = t.date()
            today = last == date.today()
            out.append(("today" if today else "h", f"{last:%a %Y-%m-%d}" + ("  (today)" if today else "")))
        stamp = f"{t:%H:%M}" if t is not None else "--:--"
        tag = "mention" if msg.get("mentions_me") else "dim" if msg.get("system") or msg.get("deleted") else "row"
        lines = (msg["text"] or "").split("\n")
        lines[0] = f"{stamp}  {msg['sender']}: {lines[0]}" if msg["sender"] else f"{stamp}  {lines[0]}"
        out.append((tag, lines[0]))
        out.extend((tag, " " * 7 + line) for line in lines[1:])
    return out


def teams_status(summary: dict) -> str:
    """One-line status for the TEAMS view."""
    text = (f"{len(summary['chats'])} chat(s)  //  {summary['unread_chats']} unread  //  "
            f"{summary['mentions']}{'+' if summary.get('capped') else ''} mention(s)  //  "
            f"loaded {summary['loaded_at']:%H:%M:%S}  //  r reload  l read  Esc back")
    notice = summary.get("cache_notice")
    return text + (f"  //  {notice}" if notice else "")
