"""Shared data/formatting for the one-screen HOME pane (used by both the GUI and the TUI)."""
from __future__ import annotations

from datetime import date, timedelta

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
