"""Gmail (read, archive, trash, mark unread, reply drafts) and Google Calendar (read-only). No UI code here.

OAuth client secret: ~/.lcars_dash/client_secret.json. The token is cached beside it.
"""
from __future__ import annotations

import base64
import html
import re
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

DIR = Path.home() / ".lcars_dash"
SECRET, TOKEN = DIR / "client_secret.json", DIR / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.compose",
          "https://www.googleapis.com/auth/calendar.readonly"]


class GoogleError(Exception):
    pass


def _credentials():
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise GoogleError("Google libraries missing (pip install google-api-python-client google-auth-oauthlib)") from e
    creds = None
    if TOKEN.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        except Exception:
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except RefreshError:
            pass
    if not SECRET.exists():
        raise GoogleError(f"Missing {SECRET} (OAuth desktop client from Google Cloud Console)")
    try:
        creds = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES).run_local_server(port=0)
    except Exception as e:
        raise GoogleError(f"Google sign-in failed: {e}") from e
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service(name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_credentials(), cache_discovery=False)


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except GoogleError:
            raise
        except Exception as e:
            raise GoogleError(str(e)) from e
    inner.__name__, inner.__doc__ = fn.__name__, fn.__doc__
    return inner


def _local(dt: datetime) -> datetime:
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _body(payload: dict) -> str:
    """Prefer text/plain; fall back to tag-stripped text/html."""
    plain, rich = [], []

    def walk(p):
        data = (p.get("body") or {}).get("data")
        mime = p.get("mimeType", "")
        if data and mime in ("text/plain", "text/html"):
            text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            (plain if mime == "text/plain" else rich).append(text)
        for sub in p.get("parts") or []:
            walk(sub)
    walk(payload)
    if plain:
        return "\n".join(plain)
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", "\n".join(rich))
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


@_wrap
def mail(limit: int = 50, unread_only: bool = False) -> list[dict]:
    svc = _service("gmail", "v1")
    resp = svc.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=limit,
                                       q="is:unread" if unread_only else None).execute()
    ids = [m["id"] for m in resp.get("messages", [])]
    found: dict[str, dict] = {}

    def got(_rid, msg, exc):
        if not exc:
            found[msg["id"]] = msg
    for i in range(0, len(ids), 20):  # small batches: Gmail rate-limits bursts (5 quota units per full message)
        if i:
            time.sleep(0.6)
        batch = svc.new_batch_http_request(callback=got)
        for mid in ids[i:i + 20]:
            batch.add(svc.users().messages().get(userId="me", id=mid, format="full"))
        batch.execute()
    for attempt in range(3):  # batch calls can drop items when rate-limited; retry the stragglers
        missing = [mid for mid in ids if mid not in found]
        if not missing:
            break
        if attempt:
            time.sleep(3)
        for mid in missing:
            try:
                found[mid] = svc.users().messages().get(userId="me", id=mid, format="full").execute()
            except Exception as e:
                last = e
    if ids and not found:
        raise GoogleError(f"Could not read messages: {last}")
    out = []
    for mid in ids:  # list() already returns newest first
        m = found.get(mid)
        if not m:
            continue
        p = m["payload"]
        name, addr = parseaddr(_header(p, "From"))
        out.append({"id": mid, "thread": m["threadId"], "received": _local(datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc)),
                    "from": name or addr, "addr": addr, "subject": _header(p, "Subject") or "(no subject)",
                    "unread": "UNREAD" in m.get("labelIds", []), "body": _body(p)[:4000],
                    "message_id": _header(p, "Message-ID"), "references": _header(p, "References"),
                    "reply_to": _header(p, "Reply-To") or _header(p, "From")})
    return out


def _when(d: dict) -> tuple[datetime, bool]:
    if "dateTime" in d:
        return _local(datetime.fromisoformat(d["dateTime"].replace("Z", "+00:00"))), False
    return datetime.fromisoformat(d["date"]), True


@_wrap
def events(days: int = 7) -> list[dict]:
    svc = _service("calendar", "v3")
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    resp = svc.events().list(calendarId="primary", timeMin=start.isoformat(), timeMax=(start + timedelta(days=days)).isoformat(),
                             singleEvents=True, orderBy="startTime", maxResults=250).execute()
    out = []
    for e in resp.get("items", []):
        if e.get("status") == "cancelled" or "start" not in e:
            continue
        s, all_day = _when(e["start"])
        end, _ = _when(e["end"])
        out.append({"id": e["id"], "start": s, "end": end, "subject": e.get("summary") or "(no title)",
                    "location": e.get("location", ""), "all_day": all_day,
                    "organizer": (e.get("organizer") or {}).get("displayName") or (e.get("organizer") or {}).get("email", ""),
                    "body": (e.get("description") or "")[:4000]})
    return out


@_wrap
def archive(mid: str) -> None:
    _service("gmail", "v1").users().messages().modify(userId="me", id=mid, body={"removeLabelIds": ["INBOX"]}).execute()


@_wrap
def trash(mid: str) -> None:
    _service("gmail", "v1").users().messages().trash(userId="me", id=mid).execute()


@_wrap
def set_unread(mid: str, unread: bool) -> None:
    body = {"addLabelIds": ["UNREAD"]} if unread else {"removeLabelIds": ["UNREAD"]}
    _service("gmail", "v1").users().messages().modify(userId="me", id=mid, body=body).execute()


@_wrap
def draft_reply(msg: dict) -> str:
    """Create a threaded reply draft and open it in Gmail for review; nothing is sent."""
    subject = msg["subject"] if msg["subject"].lower().startswith("re:") else "Re: " + msg["subject"]
    reply = EmailMessage()
    reply["To"], reply["Subject"] = msg["reply_to"], subject
    if msg.get("message_id"):
        reply["In-Reply-To"] = msg["message_id"]
        reply["References"] = f"{msg.get('references', '')} {msg['message_id']}".strip()
    quoted = "\n".join("> " + ln for ln in msg["body"].splitlines())
    reply.set_content(f"\n\nOn {msg['received']:%Y-%m-%d %H:%M}, {msg['from']} wrote:\n{quoted}")
    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
    d = _service("gmail", "v1").users().drafts().create(
        userId="me", body={"message": {"raw": raw, "threadId": msg["thread"]}}).execute()
    webbrowser.open(f"https://mail.google.com/mail/u/0/#drafts?compose={d['message']['id']}")
    return d["id"]
