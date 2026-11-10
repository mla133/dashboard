"""Read-only Microsoft Teams chats via Microsoft Graph (device code sign-in). No UI code here.

Config:  ~/.lcars_dash/teams_config.json  {"client_id": "<GUID>", "tenant_id": "<GUID or domain>"}  (read only)
Token:   ~/.lcars_dash/teams_token.bin    DPAPI-encrypted MSAL cache (or in memory only when unavailable)
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

DIR = Path.home() / ".lcars_dash"
CONFIG_FILE = DIR / "teams_config.json"
TOKEN_FILE = DIR / "teams_token.bin"
GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SCOPES = ["Chat.Read", "User.Read"]  # MSAL adds openid/profile/offline_access itself
TIMEOUT = 20  # seconds per HTTP request
MAX_RETRY_AFTER = 10  # seconds, cap on honoured Retry-After
PAGE_MAX = 50  # Graph $top maximum for chats and messages
MAX_PAGES = 5  # safety stop for @odata.nextLink loops
MENTION_SCAN = 20  # recent messages scanned per unread chat
MAX_SCAN_CHATS = 15  # unread chats scanned for mentions
SCAN_WORKERS = 4  # parallel mention scans
INSTALL_HINT = "pip install msal msal-extensions requests"
TYPE_LABELS = {"oneOnOne": "1:1 chat", "group": "Group chat", "meeting": "Meeting chat"}
MIN_UTC = datetime.min.replace(tzinfo=timezone.utc)
log = logging.getLogger("lcars_dash.teams")  # no handler is configured; debug only

NOT_CONFIGURED_MSG = (
    "Teams not configured: create ~/.lcars_dash/teams_config.json\n"
    "Setup:\n"
    "1. Entra ID (Azure AD) > App registrations > New registration (single tenant).\n"
    "2. Authentication > enable \"Allow public client flows\" (device code flow).\n"
    "3. API permissions > Microsoft Graph > Delegated > Chat.Read and User.Read, then grant consent.\n"
    "4. Copy the Application (client) ID and Directory (tenant) ID into the file as\n"
    "   {\"client_id\": \"...\", \"tenant_id\": \"...\"}\n"
    "5. pip install msal msal-extensions requests"
)

_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_CHAT_ID = re.compile(r"^(?!\.+$)(?!.*\.\.)[A-Za-z0-9:@._=\-]{1,400}$")  # no dot-only ids, no ".." anywhere
_TAG = re.compile(r"<[^<>]{0,2048}>")  # bounded, cannot backtrack across tags
_ALT = re.compile(r'\balt="([^"]*)"', re.I)
MAX_BODY_CHARS = 32768  # html_to_text input cap (ReDoS / CPU bound)
MAX_PREVIEW_CHARS = 4096  # cap for single-line previews
ALLOWED_EXACT = "/v1.0/me"  # Graph path allow-list: exactly this path ...
ALLOWED_PREFIX = "/v1.0/me/chats"  # ... or this path and anything below it (checked after normalisation)
_MAX_REASON = 200


def clean_text(value, multiline: bool = False) -> str:
    """Remove terminal-control and invisible/bidi characters (Unicode categories Cc, Cf, Zl, Zp) from untrusted text.

    Single-line mode (default) turns newlines/tabs into spaces; multiline mode keeps \\n and \\t.
    """
    out = []
    for ch in str(value if value is not None else ""):
        if ch in "\n\t":
            out.append(ch if multiline else " ")
        elif unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp"):
            out.append(ch)
    s = "".join(out)
    return s if multiline else re.sub(r" {2,}", " ", s).strip()


class Chat(TypedDict):
    id: str
    title: str
    chat_type: str
    members: list
    preview: str
    sender: str
    time: "datetime | None"
    time_utc: "datetime | None"
    last_read_utc: "datetime | None"
    unread: bool
    web_url: str
    mentions: int
    mentions_capped: bool


class Message(TypedDict):
    id: str
    time: "datetime | None"
    time_utc: "datetime | None"
    sender: str
    sender_id: str
    text: str
    mentions_me: bool
    deleted: bool
    system: bool


# --------------------------------------------------------------------------- exceptions

class TeamsError(Exception):
    def __init__(self, *args):
        # Messages may embed text from Graph/MSAL: sanitise at construction (SEC-001).
        super().__init__(*(clean_text(a, multiline=True) if isinstance(a, str) else a for a in args))


class TeamsNotConfigured(TeamsError):
    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(NOT_CONFIGURED_MSG + (f"\nReason: {reason}" if reason else ""))


class TeamsMissingLibrary(TeamsError):
    pass


class TeamsBadRequest(TeamsError):
    pass


class TeamsSignInRequired(TeamsError):
    def __init__(self, user_code: str = "", verification_uri: str = "", message: str = "", expires_at: float = 0.0):
        user_code, verification_uri, message = clean_text(user_code), clean_text(verification_uri), clean_text(message, True)
        self.user_code = user_code
        self.verification_uri = verification_uri
        self.message = message
        self.expires_at = expires_at
        super().__init__(f"Sign in at {verification_uri} with code {user_code}")

    @classmethod
    def from_flow(cls, flow: dict) -> "TeamsSignInRequired":
        return cls(str(flow.get("user_code") or ""), str(flow.get("verification_uri") or flow.get("verification_url") or ""),
                   str(flow.get("message") or ""), float(flow.get("expires_at") or 0))


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except TeamsError:
            raise
        except Exception as e:
            raise TeamsError(str(e)) from e
    inner.__name__, inner.__doc__ = fn.__name__, fn.__doc__
    return inner


# --------------------------------------------------------------------------- configuration

def _load_config() -> tuple[str, str]:
    """(client_id, tenant_id) from CONFIG_FILE (read on every call) or raise TeamsNotConfigured."""
    try:
        raw = Path(CONFIG_FILE).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise TeamsNotConfigured("file not found") from None
    except (OSError, UnicodeError) as e:
        raise TeamsNotConfigured(f"cannot read file: {getattr(e, 'strerror', None) or e}") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise TeamsNotConfigured("invalid JSON") from None
    if not isinstance(data, dict):
        raise TeamsNotConfigured("not a JSON object")
    vals = []
    for key in ("client_id", "tenant_id"):
        v = data.get(key)
        if not isinstance(v, str) or not v.strip():
            raise TeamsNotConfigured(f"missing {key}")
        vals.append(v.strip())
    cid, tid = vals
    if not _GUID.match(cid):
        raise TeamsNotConfigured("client_id is not a GUID")
    if not _TENANT.match(tid):
        raise TeamsNotConfigured("tenant_id has invalid characters")
    return cid, tid


def _authority(tenant_id: str) -> str:
    return f"{LOGIN}/{tenant_id}"


def _import_msal():
    try:
        import msal
    except ImportError:
        raise TeamsMissingLibrary(f"Teams libraries missing (msal): {INSTALL_HINT}") from None
    return msal


def _import_requests():
    try:
        import requests
    except ImportError:
        raise TeamsMissingLibrary(f"Teams libraries missing (requests): {INSTALL_HINT}") from None
    return requests


# --------------------------------------------------------------------------- authentication

class _Auth:
    def __init__(self):
        self.key = None
        self.app = None
        self.cache_notice = ""
        self.state = "idle"  # idle | pending | signed_in | failed
        self.flow = None
        self.error = ""
        self.me = None


_auth = _Auth()
_lock = threading.Lock()  # guards _auth fields and _last; never held across I/O or MSAL calls
_init_lock = threading.Lock()  # serialises app construction and device-flow initiation (worker threads only)
_expand_members = True
_last = None  # (monotonic time, (limit, latest, scan), result)


def _reset() -> None:
    """Test hook: forget all auth, identity and summary state."""
    global _auth, _last, _expand_members
    with _lock:
        _auth = _Auth()
        _last = None
        _expand_members = True


def _make_cache(msal) -> tuple[object, str]:
    """Encrypted persisted token cache, or an in-memory cache plus a user-visible notice. Never plaintext."""
    try:
        import msal_extensions
        DIR.mkdir(parents=True, exist_ok=True)
        p = msal_extensions.build_encrypted_persistence(str(TOKEN_FILE))
        try:
            p.load()
        except Exception as e:
            if type(e).__name__ != "PersistenceNotFound":
                raise
        return msal_extensions.PersistedTokenCache(p), ""
    except Exception as e:
        reason = "msal-extensions not installed" if isinstance(e, ImportError) else f"{type(e).__name__}: {e}"
        return msal.TokenCache(), (f"Teams token cache unavailable ({reason}); sign-in will not be remembered. "
                                   "pip install msal-extensions")


def _ensure_app(msal, key: tuple[str, str]):
    with _lock:
        if _auth.key == key and _auth.app is not None:
            return _auth.app
    with _init_lock:
        with _lock:
            if _auth.key == key and _auth.app is not None:
                return _auth.app
        cache, notice = _make_cache(msal)
        try:
            app = msal.PublicClientApplication(key[0], authority=_authority(key[1]), token_cache=cache)
        except ValueError:
            raise TeamsNotConfigured("tenant_id rejected by Microsoft sign-in") from None
        except TeamsError:
            raise
        except Exception as e:
            raise TeamsError(f"Cannot reach Microsoft sign-in: {e}") from e
        with _lock:
            _auth.key, _auth.app, _auth.cache_notice = key, app, notice
            _auth.state, _auth.flow, _auth.error, _auth.me = "idle", None, "", None
        log.debug("teams app built")
        return app


def _silent(app, force_refresh: bool) -> str:
    try:
        accounts = app.get_accounts()
        if not accounts:
            return ""
        res = app.acquire_token_silent(SCOPES, account=accounts[0], force_refresh=force_refresh)
    except OSError as e:
        raise TeamsError(f"Teams token cache error: {e}") from e
    if res and "access_token" in res:
        with _lock:
            _auth.state, _auth.flow, _auth.error = "signed_in", None, ""
        return res["access_token"]
    return ""


def _flow_reason(res) -> str:
    res = res if isinstance(res, dict) else {}
    err = res.get("error") or ""
    if err in ("expired_token", "code_expired"):
        return "code expired"
    if err == "authorization_declined":
        return "sign-in declined"
    desc = str(res.get("error_description") or "").strip()
    if desc:
        return clean_text(desc.splitlines()[0])[:_MAX_REASON] or "unknown error"
    return clean_text(err)[:_MAX_REASON] or "unknown error"


def _complete_flow(app, flow: dict) -> None:
    """Device-flow thread: block until the user finishes (or the code expires), then record the outcome."""
    try:
        res = app.acquire_token_by_device_flow(flow)
    except Exception as e:
        res = {"error_description": str(e) or type(e).__name__}
    with _lock:
        if _auth.flow is not flow:
            return
        if isinstance(res, dict) and "access_token" in res:
            _auth.state, _auth.flow, _auth.error = "signed_in", None, ""
        else:
            _auth.state, _auth.flow, _auth.error = "failed", None, _flow_reason(res)
    log.debug("teams device flow finished: %s", _auth.state)


def _token(force_refresh: bool = False) -> str:
    """Access token via silent refresh; otherwise start (or join) the single device flow and raise TeamsSignInRequired."""
    cid, tid = _load_config()
    msal = _import_msal()
    app = _ensure_app(msal, (cid, tid))
    for attempt in range(2):
        tok = _silent(app, force_refresh)
        if tok:
            return tok
        with _init_lock:
            with _lock:
                state, flow, error = _auth.state, _auth.flow, _auth.error
            if state == "failed":
                raise TeamsError(f"Teams sign-in failed: {error} (press r to retry)")
            if state == "pending" and flow is not None and time.time() < float(flow.get("expires_at") or 0):
                raise TeamsSignInRequired.from_flow(flow)
            if state == "signed_in" and attempt == 0:
                continue  # another thread just finished; look at the cache once more
            flow = app.initiate_device_flow(scopes=SCOPES)
            if not isinstance(flow, dict) or "user_code" not in flow:
                flow = flow if isinstance(flow, dict) else {}
                reason = flow.get("error_description") or flow.get("error") or "could not start device code flow"
                with _lock:
                    _auth.state, _auth.flow, _auth.error = "failed", None, str(reason).splitlines()[0]
                raise TeamsError(f"Teams sign-in failed: {_auth.error} (press r to retry)")
            with _lock:
                _auth.state, _auth.flow, _auth.error = "pending", flow, ""
            threading.Thread(target=_complete_flow, args=(app, flow), daemon=True, name="teams-device-flow").start()
            raise TeamsSignInRequired.from_flow(flow)
    raise TeamsError("Teams sign-in failed: could not obtain a token (press r to retry)")


def auth_state() -> dict:
    """Snapshot {state, user_code, verification_uri, message, error, cache_notice}; no I/O, never blocks."""
    with _lock:
        flow = _auth.flow if _auth.state == "pending" and _auth.flow else {}
        return {"state": _auth.state, "user_code": clean_text(flow.get("user_code") or ""),
                "verification_uri": clean_text(flow.get("verification_uri") or flow.get("verification_url") or ""),
                "message": clean_text(flow.get("message") or "", True), "error": clean_text(_auth.error),
                "cache_notice": clean_text(_auth.cache_notice)}


def retry_sign_in() -> None:
    """Clear a failed sign-in so the next call starts a new device flow. No-op otherwise."""
    with _lock:
        if _auth.state == "failed":
            _auth.state, _auth.error = "idle", ""


# --------------------------------------------------------------------------- Graph HTTP layer

def _retry_after(r) -> int:
    try:
        n = int((r.headers or {}).get("Retry-After") or 2)
    except (TypeError, ValueError):
        n = 2
    return min(max(n, 1), MAX_RETRY_AFTER)


def _error_message(r) -> str:
    try:
        msg = r.json()["error"]["message"]
    except Exception:
        msg = ""
    msg = str(msg or getattr(r, "reason", "") or "")
    return clean_text(msg)[:_MAX_REASON]


def _forget_accounts() -> None:
    with _lock:
        app = _auth.app
    try:
        for acct in (app.get_accounts() if app else []):
            app.remove_account(acct)
    except Exception as e:  # best effort: the next _token() decides what to do
        log.debug("remove_account failed: %s", type(e).__name__)
    with _lock:
        _auth.state, _auth.flow, _auth.me = "idle", None, None


def _check_graph_url(url: str) -> None:
    """Validate a Graph URL after normalisation: https, fixed host, no dot segments/encoded separators, allow-listed path."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() != "graph.microsoft.com" \
            or parts.port not in (None, 443) or parts.username or parts.password:
        raise TeamsError("Refusing non-Graph URL")
    raw = parts.path
    if re.search(r"%2e|%2f|%5c|\\", raw, re.I):
        raise TeamsError("Endpoint not allowed (encoded path characters)")
    segments = urllib.parse.unquote(raw).split("/")
    if any(seg in (".", "..") for seg in segments):
        raise TeamsError("Endpoint not allowed (dot segments)")
    path = raw.lower()
    if "/teams" in path or "/channels" in path:
        raise TeamsError("Channel/team endpoints are not allowed")
    if not (path == ALLOWED_EXACT or path == ALLOWED_PREFIX or path.startswith(ALLOWED_PREFIX + "/")):
        raise TeamsError("Endpoint not allowed")


def _get(path_or_url: str, params: dict | None = None) -> dict:
    """The only function that performs HTTP to Graph (GET only)."""
    url = path_or_url if path_or_url.startswith(GRAPH + "/") else GRAPH + path_or_url
    if not url.startswith(GRAPH + "/"):
        raise TeamsError("Refusing non-Graph URL")
    _check_graph_url(url)
    requests = _import_requests()
    unauthorized = throttled = 0
    while True:
        token = _token(force_refresh=unauthorized == 1)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        started = time.monotonic()
        try:
            r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise TeamsError(f"Cannot reach Microsoft Graph: {type(e).__name__}: {e}") from e
        log.debug("GET %s -> %s (%d ms)", urllib.parse.urlsplit(url).path, r.status_code, (time.monotonic() - started) * 1000)
        code = r.status_code
        if 200 <= code < 300:
            try:
                data = r.json()
            except ValueError:
                data = None
            if not isinstance(data, dict):
                raise TeamsError("Microsoft Graph returned an invalid response")
            return data
        if code == 401:
            unauthorized += 1
            if unauthorized == 1:
                continue
            _forget_accounts()
            _token()  # raises TeamsSignInRequired (or returns if sign-in somehow succeeded)
            if unauthorized > 2:
                raise TeamsError("Microsoft Graph rejected the sign-in (401)")
            continue
        if code == 403:
            raise TeamsError("Microsoft Graph denied access (403): Chat.Read consent is missing - grant consent for "
                             "Chat.Read and User.Read in the app registration")
        if code in (429, 503):
            throttled += 1
            if throttled > 1:
                raise TeamsError("Teams is throttling requests, try again later")
            time.sleep(_retry_after(r))
            continue
        if code == 400:
            raise TeamsBadRequest(f"Microsoft Graph error 400: {_error_message(r)}")
        raise TeamsError(f"Microsoft Graph error {code}: {_error_message(r)}")


def _pages(path: str, params: dict | None, limit: int) -> list[dict]:
    items: list = []
    url, p = path, params
    for _ in range(MAX_PAGES):
        data = _get(url, p)
        value = data.get("value")
        if isinstance(value, list):
            items.extend(v for v in value if isinstance(v, dict))
        link = data.get("@odata.nextLink")
        if len(items) >= limit or not link or not isinstance(link, str):
            break
        url, p = link, None
    return items[:limit]


def _me() -> dict:
    with _lock:
        if _auth.me:
            return _auth.me
    d = _get("/me", {"$select": "id,displayName"})
    me = {"id": str(d.get("id") or ""), "name": clean_text(d.get("displayName"))}
    with _lock:
        _auth.me = me
    return me


# --------------------------------------------------------------------------- parsing

def _parse_utc(s) -> "datetime | None":
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local(dt: "datetime | None") -> "datetime | None":
    if dt is None:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _sender(frm) -> str:
    frm = frm if isinstance(frm, dict) else {}
    for kind in ("user", "application", "device"):
        who = frm.get(kind)
        if isinstance(who, dict) and who.get("displayName"):
            return clean_text(who["displayName"])
    return ""


def _chat_path(chat_id: str) -> str:
    if not isinstance(chat_id, str) or not _CHAT_ID.match(chat_id):
        raise TeamsError("Invalid chat id")
    return urllib.parse.quote(chat_id, safe=":@._=-")


def _strip_tags(text: str) -> str:
    """Single linear pass over bounded tags (no backtracking regexes): drop tags, keep text, map a few to placeholders."""
    out: list[str] = []
    pos = 0
    skip = ""  # name of an element whose content is being dropped
    for m in _TAG.finditer(text):
        if not skip:
            out.append(text[pos:m.start()])
        pos = m.end()
        tag = m.group(0)
        nm = re.match(r"</?\s*([A-Za-z][A-Za-z0-9]*)", tag)
        name = nm.group(1).lower() if nm else ""
        closing = tag.startswith("</")
        if skip:
            if closing and name == skip:
                skip = ""
            continue
        if name in ("script", "style", "attachment") and not closing:
            if name == "attachment":
                out.append("[attachment]")
            if not tag.endswith("/>"):
                skip = name
        elif name == "at" and not closing:
            out.append("@")
        elif name == "emoji" and not closing:
            alt = _ALT.search(tag)
            out.append(alt.group(1) if alt else "")
        elif name == "img" and not closing:
            out.append("[image]")
        elif name == "br" or (closing and name in ("p", "div", "li", "tr")):
            out.append("\n")
    if not skip:
        out.append(text[pos:])
    return "".join(out)


def html_to_text(content: "str | None", content_type: str = "html", single_line: bool = False) -> str:
    """Plain text from a Teams message body. Pure; strips control characters (incl. ESC)."""
    text = str(content or "")[:MAX_PREVIEW_CHARS if single_line else MAX_BODY_CHARS]
    if (content_type or "").lower() == "html":
        text = _strip_tags(text)
        text = html.unescape(text).replace("\xa0", " ")
    text = clean_text(text, multiline=True)
    if single_line:
        return re.sub(r"\s+", " ", text).strip()
    text = text.replace("\r\n", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _body_text(raw: dict, single_line: bool = False) -> str:
    body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
    return html_to_text(body.get("content"), body.get("contentType") or "html", single_line)


def _parse_chat(raw: dict, me_id: str) -> Chat:
    members = [m for m in (raw.get("members") or []) if isinstance(m, dict)]
    others = [clean_text(m.get("displayName")) for m in members if m.get("userId") != me_id]
    others = [n for n in others if n]
    chat_type = raw.get("chatType") or ""
    topic = clean_text(raw.get("topic"))
    title = topic or ", ".join(others) or TYPE_LABELS.get(chat_type, chat_type or "Chat")
    p = raw.get("lastMessagePreview")
    p = p if isinstance(p, dict) else None
    time_utc = None
    sender = preview = ""
    if p:
        time_utc = _parse_utc(p.get("createdDateTime"))
        sender = _sender(p.get("from"))
        if p.get("isDeleted"):
            preview = "[deleted]"
        elif p.get("messageType") not in (None, "message"):
            preview = "[event]"
        else:
            preview = _body_text(p, single_line=True)
    vp = raw.get("viewpoint") if isinstance(raw.get("viewpoint"), dict) else {}
    last_read = _parse_utc(vp.get("lastMessageReadDateTime"))
    unread = p is not None and time_utc is not None and (last_read is None or last_read < time_utc)
    return {"id": str(raw.get("id") or ""), "title": title, "chat_type": chat_type,
            "members": [n for n in (clean_text(m.get("displayName")) for m in members) if n],
            "preview": preview, "sender": sender, "time": _local(time_utc), "time_utc": time_utc,
            "last_read_utc": last_read, "unread": unread, "web_url": clean_text(raw.get("webUrl")),
            "mentions": 0, "mentions_capped": False}


def _parse_message(raw: dict, me_id: str) -> Message:
    deleted = bool(raw.get("deletedDateTime"))
    system = (raw.get("messageType") or "message") != "message"
    frm = raw.get("from") if isinstance(raw.get("from"), dict) else {}
    sender = "" if system else _sender(frm)
    sender_id = str(((frm.get("user") or {}) if isinstance(frm.get("user"), dict) else {}).get("id") or "")
    text = "[deleted]" if deleted else "[event]" if system else _body_text(raw)
    if not text and raw.get("attachments"):
        text = "[attachment]"
    mentions_me = False
    if not deleted and not system:
        for m in raw.get("mentions") or []:
            who = ((m or {}).get("mentioned") or {}).get("user") or {}
            if me_id and who.get("id") == me_id:
                mentions_me = True
                break
    time_utc = _parse_utc(raw.get("createdDateTime"))
    return {"id": str(raw.get("id") or ""), "time": _local(time_utc), "time_utc": time_utc, "sender": sender,
            "sender_id": sender_id, "text": text, "mentions_me": mentions_me, "deleted": deleted, "system": system}


# --------------------------------------------------------------------------- public data API

@_wrap
def chats(limit: int = 50) -> list[Chat]:
    """Chats (1:1, group, meeting), newest activity first."""
    global _expand_members
    me = _me()
    top = min(limit, PAGE_MAX)
    order = "lastMessagePreview/createdDateTime desc"
    raw = None
    if _expand_members:
        try:
            raw = _pages("/me/chats", {"$expand": "members,lastMessagePreview", "$orderby": order, "$top": top}, limit)
        except TeamsBadRequest:
            _expand_members = False
    if raw is None:
        raw = _pages("/me/chats", {"$expand": "lastMessagePreview", "$orderby": order, "$top": top}, limit)
        for c in raw:
            if not (c.get("topic") or "").strip() and "members" not in c:
                c["members"] = _get(f"/me/chats/{_chat_path(str(c.get('id') or ''))}/members").get("value") or []
    rows = [_parse_chat(c, me["id"]) for c in raw]
    rows.sort(key=lambda c: c["time_utc"] or MIN_UTC, reverse=True)  # stable; None last
    return rows


@_wrap
def messages(chat_id: str, limit: int = 50) -> list[Message]:
    """Messages of one chat, oldest -> newest."""
    path = _chat_path(chat_id)
    me = _me()
    raw = _pages(f"/me/chats/{path}/messages", {"$top": min(limit, PAGE_MAX), "$orderby": "createdDateTime desc"}, limit)
    rows = [_parse_message(m, me["id"]) for m in raw]
    rows.sort(key=lambda m: m["time_utc"] or MIN_UTC)
    return rows


def _scan_chat(chat: dict, scan: int) -> bool:
    """Count unread @mentions of me in one chat; returns True when the result is only a lower bound."""
    try:
        msgs = messages(chat["id"], scan)
    except (TeamsSignInRequired, TeamsNotConfigured, TeamsMissingLibrary):
        raise
    except TeamsError:
        chat["mentions"] = 0
        return True
    read = chat["last_read_utc"]
    chat["mentions"] = sum(1 for m in msgs if m["mentions_me"] and (read is None or (m["time_utc"] and m["time_utc"] > read)))
    chat["mentions_capped"] = bool(msgs) and len(msgs) >= scan and (read is None or (msgs[0]["time_utc"] or MIN_UTC) > read)
    return False


@_wrap
def summary(limit: int = 50, latest: int = 5, scan: int = MENTION_SCAN, max_age: float = 0.0, retry: bool = False) -> dict:
    """Unread chat / @mention overview used by HOME and the TEAMS views."""
    global _last
    if retry:
        retry_sign_in()
    key = (limit, latest, scan)
    with _lock:
        hit = _last
    if hit and max_age > 0 and hit[1] == key and time.monotonic() - hit[0] <= max_age:
        return hit[2]
    me = _me()
    rows = chats(limit)
    unread = [c for c in rows if c["unread"]]
    targets = unread[:MAX_SCAN_CHATS]
    capped = len(unread) > MAX_SCAN_CHATS
    if targets:
        with ThreadPoolExecutor(SCAN_WORKERS) as pool:
            for failed in pool.map(lambda c: _scan_chat(c, scan), targets):
                capped = capped or failed
    capped = capped or any(c["mentions_capped"] for c in targets)
    result = {"unread_chats": len(unread), "mentions": sum(c["mentions"] for c in rows), "latest": rows[:latest],
              "chats": rows, "me": me["name"], "capped": capped, "loaded_at": datetime.now(),
              "cache_notice": auth_state()["cache_notice"]}
    with _lock:
        _last = (time.monotonic(), key, result)
    return result
