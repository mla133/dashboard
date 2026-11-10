"""Read-only access to desktop Outlook (mail and calendar) through COM. No UI code here."""
from __future__ import annotations

from datetime import datetime, timedelta

INBOX, CALENDAR = 6, 9  # OlDefaultFolders


class OutlookError(Exception):
    pass


def _namespace():
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise OutlookError("pywin32 is not installed (pip install pywin32)") from e
    pythoncom.CoInitialize()  # needed because callers run on worker threads
    try:
        return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception as e:
        raise OutlookError(f"Cannot reach desktop Outlook: {e}") from e


def _naive(dt) -> datetime:
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def mail(limit: int = 50, unread_only: bool = False) -> list[dict]:
    try:
        items = _namespace().GetDefaultFolder(INBOX).Items
        items.Sort("[ReceivedTime]", True)
        out = []
        for m in items:
            if len(out) >= limit:
                break
            try:
                if unread_only and not m.UnRead:
                    continue
                out.append({"id": m.EntryID, "received": _naive(m.ReceivedTime), "from": m.SenderName or "",
                            "subject": m.Subject or "(no subject)", "unread": bool(m.UnRead),
                            "body": (m.Body or "")[:4000]})
            except Exception:
                continue  # non-mail items (meeting requests, reports) lack some properties
        return out
    except OutlookError:
        raise
    except Exception as e:
        raise OutlookError(str(e)) from e


def trash(entry_id: str) -> None:
    """Move a message to Deleted Items (recoverable from Outlook)."""
    try:
        _namespace().GetItemFromID(entry_id).Delete()
    except OutlookError:
        raise
    except Exception as e:
        raise OutlookError(str(e)) from e


def events(days: int = 7) -> list[dict]:
    try:
        items = _namespace().GetDefaultFolder(CALENDAR).Items
        items.IncludeRecurrences = True
        items.Sort("[Start]")
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days)
        fmt = "%m/%d/%Y %I:%M %p"
        found = items.Restrict(f"[Start] >= '{start.strftime(fmt)}' AND [Start] < '{end.strftime(fmt)}'")
        out = []
        for e in found:
            try:
                start = _naive(e.Start)  # recurring occurrences share an EntryID
                out.append({"id": f"{e.EntryID}|{start:%Y%m%d%H%M}", "start": start, "end": _naive(e.End),
                            "subject": e.Subject or "(no subject)", "location": e.Location or "",
                            "all_day": bool(e.AllDayEvent), "organizer": e.Organizer or "",
                            "body": (e.Body or "")[:4000]})
            except Exception:
                continue
            if len(out) >= 500:
                break
        return out
    except OutlookError:
        raise
    except Exception as e:
        raise OutlookError(str(e)) from e
