# Technical Specification — Microsoft Teams Chat (read-only) for LCARS Dashboard

Document root: `docs/` · Input: `docs/design/requirements.md` (APPROVED 2026-11-10) · Date: 2026-11-10 ·
Author: Software Architect

## Overview

Add read-only Microsoft Teams **chat** support (1:1, group, meeting chats) to `lcars_dash`:

1. New data module `lcars_dash/teams_ops.py` — config, MSAL device-code auth (thread-safe, non-blocking, single
   flow per process), DPAPI-encrypted token cache with in-memory fallback, Graph GET calls, parsing, HTML stripping,
   unread / @mention computation, `summary()`.
2. Shared formatting in `lcars_dash/home_ops.py` — HOME lines, TEAMS list cells, message lines, state/error lines.
3. TUI (Textual): `TeamsView` in `tui_panes.py`, wiring in `app.py`, HOME box in `tui_home.py`, styles in `lcars.tcss`.
4. GUI (Tkinter): `TeamsPane` + `HomePane` box + wiring in `gui.py`.
5. `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, and `tests/`.

Nothing is ever written to Teams. No channel/team endpoints. Every network/auth call runs off the UI thread.

Environment facts observed (2026-11-10): Python 3.13.15, textual 8.2.8, rich 15.0.0, pytest 9.0.3, requests 2.34.2
installed; `msal` / `msal-extensions` **not installed**; no `tests/`, `requirements.txt` or `pyproject.toml`;
`~/.lcars_dash.json` = `{"theme": "DEEP SPACE 9"}`; `~/.lcars_dash/` exists (Google files only); existing `.py`
files use CRLF.

## Architecture Summary

```text
            GUI (gui.py, Tk main loop)                    TUI (app.py / tui_panes.py / tui_home.py, Textual loop)
   TeamsPane      HomePane (TEAMS CHAT box)          TeamsView (v-teams)     HomeView (#hm-teams FocusBox)
        \            /                                     \                    /
         Dashboard.run_bg (thread + queue + _pump)          LcarsDash.run_bg (thread worker + call_from_thread)
                         \                                  /
                          \        auth_state() (non-blocking poll from UI timers)
                           v                               v
                 home_ops.py  (pure formatting: (tag, text) lines, table cells, status text)
                           |
                 teams_ops.py (no UI code)
                   ├─ config:   ~/.lcars_dash/teams_config.json  (read-only)
                   ├─ auth:     msal.PublicClientApplication + device flow thread (daemon)
                   │            token cache: msal_extensions PersistedTokenCache (DPAPI) → ~/.lcars_dash/teams_token.bin
                   │                         or msal.TokenCache() in memory (fallback, never written)
                   └─ graph:    requests.get → https://graph.microsoft.com/v1.0  (GET only)
```

Pattern compliance: `teams_ops` mirrors `outlook_ops`/`google_ops` (module `XxxError`, lazy third-party imports,
all exceptions wrapped). Views mirror `OutlookView`/`OutlookPane`. HOME formatting mirrors `home_ops.mail_lines`.

## Requirements Mapping

| Req | Design element (section) |
|---|---|
| FR-001 | `teams_ops._load_config`, `CONFIG_FILE`, `_authority` (C1, C2) |
| FR-002 | `TeamsNotConfigured`, `NOT_CONFIGURED_MSG` (C2, Error Handling) |
| FR-003 | lazy `_import_msal`, `_import_requests`, `TeamsMissingLibrary` (C3) |
| FR-004 | `SCOPES = ["Chat.Read", "User.Read"]` (C4) |
| FR-005 | `TeamsSignInRequired(user_code, verification_uri, message)` (C4) |
| FR-006 | device-flow daemon thread; UI `run_bg`; UI poll of `auth_state()` (C4, Threading) |
| FR-007 | `_init_lock` + `_Auth.flow` single slot (C4) |
| FR-008 | flow thread result → state `signed_in`/`failed`; UI poll reloads; `retry_sign_in()` (C4) |
| FR-009 | `msal_extensions.build_encrypted_persistence(TOKEN_FILE)` + `PersistedTokenCache` (C5) |
| FR-010 | in-memory `msal.TokenCache()` fallback + `cache_notice` (C5) |
| FR-011 | `_token()` silent first; `TeamsSignInRequired` (C4) |
| FR-012 | public API list (Interface Contracts) |
| FR-013 | `chats()` + `_parse_chat` (C7) |
| FR-014 | `messages()` + `_parse_message` (C7) |
| FR-015 | `html_to_text()` (C8) |
| FR-016 | `summary()` (C9) |
| FR-017 | `_me()` cached (C6) |
| FR-018 | `_get()` sole HTTP entry, GET only, URL guard (C6) |
| FR-019 | `_get()` status handling table (C6) |
| FR-020/021 | `app.py` NavBlock + bindings; `lcars.tcss` `#n-teams` (U1) |
| FR-022/023/024 | `tui_panes.TeamsView` (U2) |
| FR-025 | `app.HELP["teams"]`, `GLOBAL_HELP`, `HELP["home"]` (U1) |
| FR-026/027/028 | `gui.py` nav pill, keys, `TeamsPane`, help (U4, U5) |
| FR-029 | `home_ops.teams_lines` (C10) |
| FR-030 | TUI third column in `.hm-mail` row; GUI 6-column grid (U3, U6) |
| FR-031 | `GO["hm-teams"]`; GUI `panel(..., go=go("show_teams"))` (U3, U6) |
| FR-032 | HOME teams job + compact error lines + 2 s sign-in poll (U3, U6) |
| FR-033 | `requirements.txt`, `requirements-dev.txt` (Deployment) |
| FR-034–037 | Test Plan |
| NFR-001 | Threading section; `auth_state()`/`retry_sign_in()` never block |
| NFR-002 | timeouts, scan caps, 4-worker mention scan |
| NFR-003 | Security section |
| NFR-005 | all Teams exceptions delivered as values to UI callbacks |
| NFR-006 | patterns + CRLF rule |
| NFR-007 | tests redirect `config.CONFIG_FILE`, `teams_ops.*` paths |
| NFR-008 | colours only via theme roles (ORANGE, PEACH, LAVENDER, BLUE, PERIWINKLE, RED, BLACK) |

## System Components

| Id | Component | File | New/Changed |
|---|---|---|---|
| C1–C9 | Teams data module | `lcars_dash/teams_ops.py` | NEW |
| C10 | Teams formatting helpers | `lcars_dash/home_ops.py` | CHANGED (additions only) |
| U1 | TUI app wiring (nav, keys, help, view switch, theme) | `lcars_dash/app.py` | CHANGED |
| U2 | TUI `TeamsView` | `lcars_dash/tui_panes.py` | CHANGED (new class) |
| U3 | TUI HOME Teams box | `lcars_dash/tui_home.py` | CHANGED |
| U3b | TUI styles | `lcars_dash/lcars.tcss` | CHANGED |
| U4 | GUI `TeamsPane` | `lcars_dash/gui.py` | CHANGED (new class) |
| U5 | GUI `Dashboard` wiring | `lcars_dash/gui.py` | CHANGED |
| U6 | GUI `HomePane` Teams box | `lcars_dash/gui.py` | CHANGED |
| T | Tests / packaging | `tests/`, `pytest.ini`, `requirements*.txt` | NEW |

## Component Responsibilities

### teams_ops.py (C1–C9)

Module docstring: `"""Read-only Microsoft Teams chats via Microsoft Graph (device code sign-in). No UI code here.`
+ config/token paths. Top-level imports: **stdlib only** (`html`, `json`, `logging`, `re`, `threading`, `time`,
`concurrent.futures`, `datetime`, `pathlib`, `urllib.parse`). `msal`, `msal_extensions`, `requests` are imported
inside functions.

#### C1 — Constants (module globals; functions must read them at call time so tests can monkeypatch)

```python
DIR = Path.home() / ".lcars_dash"
CONFIG_FILE = DIR / "teams_config.json"
TOKEN_FILE = DIR / "teams_token.bin"
GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SCOPES = ["Chat.Read", "User.Read"]          # MSAL adds openid/profile/offline_access itself
TIMEOUT = 20                                  # seconds per HTTP request (NFR-002)
MAX_RETRY_AFTER = 10                          # seconds, cap on honoured Retry-After
PAGE_MAX = 50                                 # Graph $top maximum for chats and messages
MAX_PAGES = 5                                 # safety stop for @odata.nextLink loops
MENTION_SCAN = 20                             # recent messages scanned per unread chat
MAX_SCAN_CHATS = 15                           # unread chats scanned for mentions
SCAN_WORKERS = 4                              # parallel mention scans
INSTALL_HINT = "pip install msal msal-extensions requests"
TYPE_LABELS = {"oneOnOne": "1:1 chat", "group": "Group chat", "meeting": "Meeting chat"}
log = logging.getLogger("lcars_dash.teams")   # no handler is configured; debug only
```

#### C2 — Configuration

`_load_config() -> tuple[str, str]` returns `(client_id, tenant_id)` or raises `TeamsNotConfigured`.

- Read `CONFIG_FILE` (UTF-8, `utf-8-sig` tolerated). Reasons → raise `TeamsNotConfigured(reason)`:
  file missing (`"file not found"`), `OSError` (`"cannot read file: <errno text>"`), invalid JSON (`"invalid JSON"`),
  not a dict (`"not a JSON object"`), `client_id`/`tenant_id` missing, not str, or blank after `strip()`
  (`"missing client_id"` / `"missing tenant_id"`).
- Validation (security, see Security): `client_id` must match `^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$`;
  `tenant_id` must match `^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$` (GUID or domain). Failure → reason
  `"client_id is not a GUID"` / `"tenant_id has invalid characters"`.
- Read on **every** `_token()` call (tiny file); never written by the app.
- `_authority(tenant_id) -> str` = `f"{LOGIN}/{tenant_id}"`.

#### C3 — Lazy library imports

- `_import_msal()` → `msal` module; `ImportError` → `TeamsMissingLibrary`.
- `_import_requests()` → `requests` module; `ImportError` → `TeamsMissingLibrary`.
- `msal_extensions` is optional (C5); its absence is **not** an error.
- Message: `f"Teams libraries missing ({name}): {INSTALL_HINT}"`.
- Order of checks in every public data function: config (C2) → libraries (C3) → auth (C4) → Graph (C6).
  The not-configured message includes the install step, so a user missing both sees all steps at once.

#### C4 — Authentication (thread-safe, non-blocking, one device flow per process)

Single module-level `_Auth` instance `_auth` holding:

| Field | Type | Meaning |
|---|---|---|
| `key` | `tuple[str, str] \| None` | `(client_id, tenant_id)` the app was built for |
| `app` | `msal.PublicClientApplication \| None` | MSAL client |
| `cache_notice` | `str` | `""` or FR-010 notice |
| `state` | `str` | `"idle"`, `"pending"`, `"signed_in"`, `"failed"` |
| `flow` | `dict \| None` | MSAL device flow while `pending` |
| `error` | `str` | failure reason while `failed` |
| `me` | `dict \| None` | `{"id", "name"}` from `/me` (FR-017) |

Locks:

- `_lock = threading.Lock()` guards the fields above. **Never held across I/O or any MSAL call.**
- `_init_lock = threading.Lock()` serialises app construction and device-flow initiation (network I/O allowed).
  Only ever acquired on worker threads (inside data functions).

Algorithm `_token(force_refresh: bool = False) -> str`:

1. `cid, tid = _load_config()`; `msal = _import_msal()`.
2. `app = _ensure_app(msal, (cid, tid))`: under `_init_lock`, if `_auth.key != key` build a new
   `msal.PublicClientApplication(cid, authority=_authority(tid), token_cache=cache)` with `cache, notice = _make_cache(msal)`
   (C5); on success set (under `_lock`) `key, app, cache_notice`, and reset `state="idle", flow=None, error="", me=None`.
   Construction errors (MSAL performs authority discovery) → `TeamsError(f"Cannot reach Microsoft sign-in: {e}")`;
   `ValueError` from MSAL for a bad authority → `TeamsNotConfigured("tenant_id rejected by Microsoft sign-in")`.
3. Silent: `accounts = app.get_accounts()`; if any, `res = app.acquire_token_silent(SCOPES, account=accounts[0],
   force_refresh=force_refresh)`; if `res` and `"access_token" in res`: set `state="signed_in"`; return token.
4. Under `_init_lock` (re-check, so concurrent callers share one flow — FR-007):
   - copy state under `_lock`;
   - `failed` → raise `TeamsError(f"Teams sign-in failed: {error} (press r to retry)")` (no new flow; avoids HOME
     auto-refresh starting flows; only `retry_sign_in()` clears it);
   - `pending` and `time.time() < flow["expires_at"]` → raise `TeamsSignInRequired.from_flow(flow)`;
   - `signed_in` (another thread just finished) → release lock and go to step 3 once more (at most one repeat);
   - otherwise: `flow = app.initiate_device_flow(scopes=SCOPES)`; if `"user_code" not in flow` → set `failed` with
     `flow.get("error_description") or flow.get("error") or "could not start device code flow"` and raise as above;
     else set `state="pending", flow=flow`, start
     `threading.Thread(target=_complete_flow, args=(app, flow), daemon=True, name="teams-device-flow")`,
     raise `TeamsSignInRequired.from_flow(flow)`.
5. `_complete_flow(app, flow)` (device-flow thread): `res = app.acquire_token_by_device_flow(flow)` (blocks up to
   `expires_in`, MSAL default exit condition = expiry). Wrap in `try/except Exception as e` → reason `str(e)`.
   Under `_lock`, only if `_auth.flow is flow` (a config change may have replaced it):
   - `"access_token" in res` → `state="signed_in", flow=None, error=""` (cache persisted by MSAL/PersistedTokenCache);
   - else → `state="failed", flow=None, error=_flow_reason(res)`.
   `_flow_reason`: `expired_token`/`code_expired` → `"code expired"`; `authorization_declined` → `"sign-in declined"`;
   otherwise first line of `error_description`, else `error`, else `"unknown error"`. This thread never touches UI.

Public auth helpers (UI-thread safe; take `_lock` only, microseconds):

```python
def auth_state() -> dict:
    """Snapshot: {"state", "user_code", "verification_uri", "message", "error", "cache_notice"}; no I/O."""
def retry_sign_in() -> None:
    """If state == "failed": state = "idle", error = "". No-op otherwise (a pending flow is kept)."""
```

Sign-out is manual (delete `teams_token.bin`, ASSUMPTION-009); no API.

Test hook: `_reset() -> None` — resets `_auth` to defaults and clears the summary cache (C9). Not used by UI.

#### C5 — Token cache

`_make_cache(msal) -> tuple[object, str]`:

```text
try:
    import msal_extensions                                     # ImportError → fallback
    DIR.mkdir(parents=True, exist_ok=True)
    p = msal_extensions.build_encrypted_persistence(str(TOKEN_FILE))   # Windows: DPAPI file persistence
    try: p.load()                                               # probe; PersistenceNotFound (no file yet) is OK
    except Exception as e: if type(e).__name__ != "PersistenceNotFound": raise
    return msal_extensions.PersistedTokenCache(p), ""
except Exception as e:
    reason = "msal-extensions not installed" if isinstance(e, ImportError) else f"{type(e).__name__}: {e}"
    return msal.TokenCache(), f"Teams token cache unavailable ({reason}); sign-in will not be remembered. pip install msal-extensions"
```

Rules: never use `msal_extensions.FilePersistence` (plaintext) or `SerializableTokenCache.serialize()` to disk; the
fallback cache is never serialised. Cache write failures surfacing later from MSAL calls → `TeamsError(f"Teams token
cache error: {e}")`.

#### C6 — Graph HTTP layer

`_get(path_or_url: str, params: dict | None = None) -> dict` — the **only** function that performs HTTP to Graph.

- URL: `path_or_url` if it starts with `GRAPH + "/"`, else `GRAPH + path_or_url` (path must start with `/`).
  Guard (FR-018, Security): raise `TeamsError("Refusing non-Graph URL")` unless the final URL starts with
  `GRAPH + "/"`; raise `TeamsError("Channel/team endpoints are not allowed")` if `"/teams/"` or `"/channels/"` in URL.
- `requests = _import_requests()`; headers `{"Authorization": f"Bearer {token}", "Accept": "application/json"}`;
  `requests.get(url, headers=headers, params=params, timeout=TIMEOUT)`. No other `requests` verb is used anywhere.
- Status handling (FR-019):

| Condition | Behaviour |
|---|---|
| `requests.Timeout` / `requests.RequestException` | `TeamsError(f"Cannot reach Microsoft Graph: {type(e).__name__}: {e}")` |
| 2xx | `r.json()`; `ValueError` or non-dict → `TeamsError("Microsoft Graph returned an invalid response")` |
| 401, first time | `_token(force_refresh=True)` then retry once |
| 401, second time | `app.remove_account(account)` for the cached account(s), set `state="idle"`, `me=None`, then `_token()` (raises `TeamsSignInRequired`) |
| 403 | `TeamsError("Microsoft Graph denied access (403): Chat.Read consent is missing - grant consent for Chat.Read and User.Read in the app registration")` |
| 429 / 503, first time | sleep `min(max(int(Retry-After or 2), 1), MAX_RETRY_AFTER)` via `time.sleep`, retry once (non-numeric header → 2) |
| 429 / 503, second time | `TeamsError("Teams is throttling requests, try again later")` |
| 400 | `TeamsBadRequest(f"Microsoft Graph error 400: {msg}")` (subclass of `TeamsError`; used by C7 fallback) |
| other ≥ 400 | `TeamsError(f"Microsoft Graph error {status}: {msg}")`, `msg` = `error.message` from JSON body or reason phrase, truncated 200 chars |

- `_pages(path, params, limit) -> list[dict]`: calls `_get`, collects `value` lists, follows `@odata.nextLink`
  (passed with `params=None`) until `len >= limit`, no link, or `MAX_PAGES` reached; returns `items[:limit]`.
- `_me() -> dict`: cached `_auth.me`, else `_get("/me", {"$select": "id,displayName"})` →
  `{"id": d["id"], "name": d.get("displayName") or ""}`; stored under `_lock`.
- `log.debug` may record method, URL path (no query values beyond `$top`), status, elapsed ms. **Never** headers,
  tokens, or message content.

#### C7 — chats() and messages()

`chats(limit: int = 50) -> list[Chat]`

1. `me = _me()`.
2. Primary request: `_pages("/me/chats", {"$expand": "members,lastMessagePreview", "$orderby":
   "lastMessagePreview/createdDateTime desc", "$top": min(limit, PAGE_MAX)}, limit)`.
3. If `TeamsBadRequest` (expand combination rejected), set module flag `_expand_members = False` (sticky for the
   process) and use `{"$expand": "lastMessagePreview", "$orderby": ..., "$top": ...}`; then for each returned chat
   without `topic` fetch members with `_get(f"/me/chats/{_chat_path(id)}/members")["value"]` (bounded by `limit`).
4. `_parse_chat(raw, me_id)` per item; sort by `time_utc` desc, `None` last (stable); return.

`_parse_chat(raw, me_id) -> Chat`:

- `members` = `[m.get("displayName") or "" for m in raw.get("members") or []]` minus blanks (all members, incl. me).
- `others` = display names of members whose `userId != me_id`.
- `title` = `raw["topic"].strip()` if truthy, else `", ".join(others)` if any, else
  `TYPE_LABELS.get(chatType, chatType or "Chat")`.
- `p = raw.get("lastMessagePreview")`: if `p`: `time_utc = _parse_utc(p.get("createdDateTime"))`,
  `sender = _sender(p.get("from"))`, `preview = "[deleted]" if p.get("isDeleted") else
  ("[event]" if p.get("messageType") not in (None, "message") else html_to_text(body.content, body.contentType,
  single_line=True))`; else `time_utc=None, sender="", preview=""`.
- `last_read_utc = _parse_utc(((raw.get("viewpoint") or {}).get("lastMessageReadDateTime")))`.
- `unread = p is not None and time_utc is not None and (last_read_utc is None or last_read_utc < time_utc)`
  (Definitions; preview without timestamp → read).
- Result dict keys: `id, title, chat_type, members, preview, sender, time, time_utc, last_read_utc, unread, web_url,
  mentions (0), mentions_capped (False)`.

`messages(chat_id: str, limit: int = 50) -> list[Message]`

- `_chat_path(chat_id)`: validate `^[A-Za-z0-9:@._=\-]{1,400}$` else `TeamsError("Invalid chat id")`; return
  `urllib.parse.quote(chat_id, safe=":@._=-")`.
- `me = _me()`; `_pages(f"/me/chats/{path}/messages", {"$top": min(limit, PAGE_MAX), "$orderby":
  "createdDateTime desc"}, limit)` → parse each → sort by `time_utc` ascending (oldest → newest, `None` first).

`_parse_message(raw, me_id) -> Message`:

- `deleted = bool(raw.get("deletedDateTime"))`; `system = raw.get("messageType", "message") != "message"`.
- `sender = "" if system else _sender(raw.get("from"))`; `sender_id = ((raw.get("from") or {}).get("user") or {}).get("id") or ""`.
- `text = "[deleted]" if deleted else "[event]" if system else html_to_text(body.content, body.contentType)`;
  if text is empty and `raw.get("attachments")` → `"[attachment]"`.
- `mentions_me = not deleted and not system and any(((m.get("mentioned") or {}).get("user") or {}).get("id") == me_id
  for m in raw.get("mentions") or [])`.
- Keys: `id, time, time_utc, sender, sender_id, text, mentions_me, deleted, system`.

Helpers: `_sender(frm) -> str` = `user.displayName` → `application.displayName` → `device.displayName` → `""`.
`_parse_utc(s) -> datetime | None` = `datetime.fromisoformat(s.replace("Z", "+00:00"))` (Python ≥ 3.11 accepts 7
fractional digits), `None` on falsy/invalid; naive results assumed UTC. `_local(dt_utc) -> datetime | None` =
`dt.astimezone().replace(tzinfo=None)` (same as `google_ops._local`).

#### C8 — HTML stripping

`html_to_text(content: str | None, content_type: str = "html", single_line: bool = False) -> str` (public, pure):

1. `content = content or ""`. If `content_type.lower() != "html"`: `text = content` (skip to step 9).
2. Remove `(?is)<(script|style)\b.*?</\1>`.
3. `(?is)<at\b[^>]*>(.*?)</at>` → `"@" + <inner with tags removed, stripped>`.
4. `(?is)<emoji\b[^>]*\balt="([^"]*)"[^>]*>(?:</emoji>)?` → the `alt` value (unescaped later).
5. `(?is)<img\b[^>]*>` → `"[image]"`.
6. `(?is)<attachment\b[^>]*>.*?</attachment>` and `(?is)<attachment\b[^>]*/>` → `"[attachment]"`.
7. `(?i)<br\s*/?>|</p>|</div>|</li>|</tr>` → `"\n"`.
8. Remove remaining tags `<[^>]+>`; then `html.unescape`; replace `\xa0` with space.
9. Remove control characters `[\x00-\x08\x0b-\x1f\x7f]` (incl. ESC; keeps `\n`, `\t`).
10. Multi-line: normalise `\r\n` → `\n`, `rstrip` each line, collapse `\n{3,}` → `\n\n`, `strip()`.
    Single-line: `re.sub(r"\s+", " ", text).strip()`.

Unescape happens after tag removal so `&lt;b&gt;` renders as the literal `<b>`.

#### C9 — summary()

```python
def summary(limit: int = 50, latest: int = 5, scan: int = MENTION_SCAN,
            max_age: float = 0.0, retry: bool = False) -> dict
```

1. If `retry`: `retry_sign_in()`.
2. If a cached result (module `_last = (monotonic_time, args, result)`, guarded by `_lock`) has the same
   `(limit, latest, scan)` and age ≤ `max_age` → return it (TEAMS tab open uses `max_age=60`; HOME and `r` use 0).
3. `me = _me()`; `rows = chats(limit)`.
4. `unread = [c for c in rows if c["unread"]]`; `targets = unread[:MAX_SCAN_CHATS]`;
   `capped = len(unread) > MAX_SCAN_CHATS`.
5. Scan targets with `ThreadPoolExecutor(SCAN_WORKERS)`: `msgs = messages(c["id"], scan)`;
   `count = sum(1 for m in msgs if m["mentions_me"] and (c["last_read_utc"] is None or (m["time_utc"] and
   m["time_utc"] > c["last_read_utc"])))`; `c["mentions"] = count`;
   `c["mentions_capped"] = len(msgs) >= scan and (c["last_read_utc"] is None or    (msgs[0]["time_utc"] or MIN_UTC) >
      c["last_read_utc"])` where `msgs[0]` is the oldest scanned message and
      `MIN_UTC = datetime.min.replace(tzinfo=timezone.utc)` (i.e. the window is full and still newer than last read). If a scan raises `TeamsSignInRequired` or `TeamsNotConfigured`/`TeamsMissingLibrary`,
   re-raise; any other `TeamsError` → `c["mentions"] = 0`, `capped = True` (best effort).
6. `capped = capped or any(c["mentions_capped"] for c in targets)`.
7. Return and cache:

```python
{"unread_chats": len(unread), "mentions": sum(c["mentions"] for c in rows), "latest": rows[:latest],
 "chats": rows, "me": me["name"], "capped": capped, "loaded_at": datetime.now(),
 "cache_notice": auth_state()["cache_notice"]}
```

#### Public API (FR-012)

`TeamsError`, `TeamsNotConfigured`, `TeamsMissingLibrary`, `TeamsSignInRequired`, `TeamsBadRequest`,
`chats(limit=50)`, `messages(chat_id, limit=50)`, `summary(...)`, `auth_state()`, `retry_sign_in()`,
`html_to_text(...)`, constants `CONFIG_FILE`, `TOKEN_FILE`, `SCOPES`. All other names are private (`_`).
Every public data function is wrapped by `_wrap` (same as `google_ops._wrap`): `TeamsError` passes through, any
other `Exception` → `TeamsError(str(e))`.

### home_ops.py additions (C10)

Docstring becomes "Shared data/formatting for the HOME pane and the TEAMS views (GUI and TUI)." Add
`from . import teams_ops`. Tags used: `h`, `today`, `row`, `dim`, `err`, `unread`, `mention`.

```python
def teams_cells(chat: dict) -> tuple[str, str, str, str]:
    """(marker, time, title, last) for the TEAMS list. marker = ('*' if unread else ' ') + ('@' if mentions else ' ');
    time = f"{t:%m-%d %H:%M}" or '-'; last = f"{sender}: {preview}" if sender else preview."""

def teams_lines(summary: dict, width: int, rows: int = 5) -> list[tuple[str, str]]:
    """HOME box. Line 1: header f"Unread chats: {u}  //  Mentions: {m}{'+' if capped else ''}" tagged
    'mention' if m else 'unread' if u else 'dim'. Then up to `rows` of summary['latest']:
    short(f"{marker} {time:<11}  {short(title, 20):<20}  {last}", width), tagged 'mention' if chat mentions
    else 'unread' if unread else 'row'. No chats → ('dim', 'No chats')."""

def teams_error_lines(err: BaseException, width: int, compact: bool) -> list[tuple[str, str]]:
    """State lines for an exception from teams_ops (compact = HOME box; full = TEAMS text pane). See table below."""

def teams_message_lines(messages: list[dict]) -> list[tuple[str, str]]:
    """Day header per date ('today' tag + '  (today)' for today, else 'h', text f"{d:%a %Y-%m-%d}"); each message
    f"{t:%H:%M}  {sender}: {text}" (no 'sender: ' when sender == ''; '--:--' when time is None), continuation lines
    indented 7 spaces; tag 'mention' if mentions_me, 'dim' if system or deleted, else 'row'.
    Empty → [('dim', 'No messages')]."""

def teams_status(summary: dict) -> str:
    """f"{n} chat(s)  //  {u} unread  //  {m}{'+' if capped else ''} mention(s)  //  loaded {loaded_at:%H:%M:%S}
    //  r reload  l read  Esc back" + (f"  //  {cache_notice}" if cache_notice else "")."""
```

`teams_error_lines` mapping:

| Exception | compact (HOME) | full (TEAMS text pane) |
|---|---|---|
| `TeamsNotConfigured` | `("err", "Teams not configured - open TEAMS (y) for setup")` | `("h", "TEAMS NOT CONFIGURED")` + `("row", line)` per line of `str(err)` |
| `TeamsMissingLibrary` | `("err", "Teams libraries missing - pip install msal msal-extensions requests")` | `("h", "TEAMS LIBRARIES MISSING")`, `("row", str(err))` |
| `TeamsSignInRequired` | `("unread", f"Sign in: {uri}  code {code}")`, `("dim", "Waiting for sign-in... (r to retry)")` | `("h", "SIGN IN TO MICROSOFT TEAMS")`, `("row", f"1. Open  {uri}")`, `("mention", f"2. Enter code  {code}")`, `("row", "3. Sign in with your work account and accept Chat.Read / User.Read")`, `("dim", "Waiting for sign-in... (r to retry)")`, `("dim", message)` |
| any other | `("err", short(f"Error: {first line}", width))` | `("err", f"Error: {err}")` |

Compact lines are shortened with `short(..., width)`; full lines are not (text pane wraps).

### TUI (U1–U3)

#### U1 — app.py

| Location | Change |
|---|---|
| imports | add `TeamsView` to the `from .tui_panes import (...)` list |
| `HELP` dict | add `"teams": ("MICROSOFT TEAMS (READ-ONLY)", [...])` with rows: `("(what)", "Your 1:1, group and meeting chats, newest first. * = unread, @ = unread message mentions you. Nothing is ever sent or marked read")`, `("j / k, g / G", "Move through chats (or scroll the messages)")`, `("Ctrl+d / Ctrl+u", "Page down / up")`, `("l / Enter", "Read the selected chat (focus the messages)")`, `("h", "Back to the chat list")`, `("Tab", "Switch between list and messages")`, `("r", "Reload chats; restarts sign-in if it failed or expired")`, `("Esc", "Back to the repo list")`, `("(setup)", "~/.lcars_dash/teams_config.json {\"client_id\", \"tenant_id\"}; first use shows a sign-in code for microsoft.com/devicelogin")`, `("(sign out)", "Delete ~/.lcars_dash/teams_token.bin")` |
| `HELP["home"]` | `(what)` adds "Teams unread chats and mentions"; `click / Tab + Enter` row lists "... Outlook, Gmail, Teams"; `r` row: "Reload usage, calendars, mail and Teams now ..." |
| `GLOBAL_HELP` | insert `("⇧F11 / y", "Microsoft Teams chats (read-only)")` right after the `("F11 / i", ...)` entry |
| `StatusView.BINDINGS` | add `Binding("y", "app.show_teams", "Teams", show=False)` after the `"i"` binding |
| `LcarsDash.BINDINGS` | add `Binding("shift+f11,f23", "show_teams", show=False)` after `f11` (`f23` = how some terminals report Shift+F11) |
| `compose()` sidebar | `yield NavBlock("TEAMS\n[⇧F11 / Y]", "show_teams", id="n-teams", classes="block")` directly after `n-google` |
| `compose()` views | `yield TeamsView(id="v-teams")` after `GoogleView` |
| statusbar text | append `y teams` before `? help` |
| new action | `def action_show_teams(self): self._switch("teams"); self.query_one(TeamsView).open()` (after `action_show_google`) |
| `action_cycle_theme` | after `self.query_one(HomeView).render_all()` add `self.query_one(TeamsView).render_all()` |

`action_toggle_focus` and `action_show_help` need no change (`TeamsView` is a `ListTextView`; `HELP["teams"]` exists).

#### U2 — tui_panes.py `TeamsView(ListTextView)` (place after `GoogleView`)

```python
class TeamsView(ListTextView):
    PREFIX = "tm"
    TITLE = "MICROSOFT TEAMS  //  CHATS (READ-ONLY)"
    BINDINGS = [Binding("r", "reload(True)", "Reload"), Binding("enter", "focus_text", show=False)]
    STALE_S = 60
```

State: `self.summary: dict | None`, `self.rows: dict[str, dict]`, `self.err: Exception | None`,
`self.state` ∈ `{"idle","loading","signin","error","loaded"}`, `self.last_load = 0.0`, `self.token = 0`,
`self.msg_token = 0`, `self.msg_timer = None`, `self.msg_cache: dict[str, tuple[datetime | None, list]]`,
`self.messages_for: str | None`.

| Method | Contract |
|---|---|
| `on_mount()` | `table.add_columns("", "TIME", "CHAT", "LAST MESSAGE")`; `self.set_interval(2, self._poll)` |
| `open()` | focus table; if `state in ("idle","signin","error")` or `time.time() - last_load > STALE_S` → `action_reload(False, max_age=60)`; else `render_all()` |
| `action_reload(retry=True, max_age=0.0)` | `state="loading"`; `say("Reading Microsoft Teams...")`; `token += 1`; `self.app.run_bg(lambda: teams_ops.summary(latest=5, retry=retry, max_age=max_age), done)` (not `self.bg`: exceptions are states, not just status text). `done(res)`: ignore if token changed; `last_load = time.time()`; exception → `err=res`, `state="signin"` if `TeamsSignInRequired` else `"error"`, clear table, `rows={}`, `render_all()`; else `summary=res`, `rows={c["id"]: c for c in res["chats"]}`, `state="loaded"`, `render_all()` keeping selection via `reselect(keep)` |
| `render_all()` | Re-styles everything from `self.app.colors` (called on theme cycle). loaded: clear table, add one row per chat with **`rich.text.Text` cells** (never raw `str` — DataTable parses str as markup): cells from `home_ops.teams_cells`, style `bold <ORANGE>` for unread, marker cell `bold <RED>` when mentions; empty → `show_text(Text("No chats"))`; status `home_ops.teams_status(summary)`. error/signin: `show_text(self._lines(home_ops.teams_error_lines(err, 80, compact=False)))`; status `"Sign-in pending - r retries"` / `f"Error - r reload"` + cache notice from `teams_ops.auth_state()` if any |
| `_lines(lines)` | same as `HomeView._lines` using `_styles()`: `h` ORANGE, `today` `bold BLACK on ORANGE`, `unread` ORANGE, `mention` `bold RED`, `dim` LAVENDER, `err` RED, `row` "" |
| `on_select()` | debounce: cancel `msg_timer`; `msg_timer = self.set_timer(0.3, self._load_messages)` |
| `_load_messages()` | chat = selected; if `msg_cache[id][0] == chat["time"]` → render cached; else `msg_token += 1`, show "Loading messages...", `run_bg(lambda: teams_ops.messages(id), done)`; `done` ignores stale token; exception → `show_text(self._lines(teams_error_lines(e, 80, False)))`; else cache and render header (`bold` title + `dim` members line) + `home_ops.teams_message_lines(msgs)` |
| `on_data_table_row_selected(e)` | for `tm-table`: `e.stop()`; `action_focus_text()` (Enter on list) |
| `_poll()` | return unless `self.app.current_view == "teams"` and `state == "signin"`; if `teams_ops.auth_state()["state"] in ("signed_in", "failed")` → `action_reload(False)` |

Inherited: `j/k/g/G/Ctrl+d/Ctrl+u` (Navigable), `l`/`h` (ListTextView), `Esc` → `app.show_status`.
No binding performs a write. Import `time` and `teams_ops`, `home_ops` at module top (`teams_ops` is import-safe).

#### U3 — tui_home.py

| Location | Change |
|---|---|
| imports | add `teams_ops` to `from . import ...` |
| `GO` | append `"hm-teams": "show_teams"` as the **last** entry (Tab order: ... Gmail inbox → Teams) |
| `BINDINGS` | `Binding("r", "reload(True)", "Reload")` (was `"reload"`) |
| `compose()` | inside `Horizontal(classes="hm-row hm-mail")`, after the `for src` loop: `yield FocusBox("", id="hm-teams", classes="hm-box")`; status text: `"r reload  //  n quick entry ..."` unchanged except "Teams" needs no mention |
| `on_mount()` titles | add `"#hm-teams": "TEAMS CHAT"` |
| `__init__` | add `self.teams_busy = False` |
| `action_reload(retry: bool = False)` | keep existing jobs; then `self.reload_teams(retry)` |
| new `reload_teams(retry=False)` | if `teams_busy` return; `teams_busy=True`; `run_bg(lambda: teams_ops.summary(latest=5, retry=retry), done)`; `done`: `teams_busy=False`, `data["teams"]=res`, `render_teams()` |
| `_auto()` | after `refresh_monitor()`: if `isinstance(self.data.get("teams"), teams_ops.TeamsSignInRequired)` and `teams_ops.auth_state()["state"] in ("signed_in","failed")` → `reload_teams()` |
| `_styles()` | add `"mention": f"bold {c['RED']}"` |
| `render_all()` | add `self.render_teams()` |
| new `render_teams()` | `res = data.get("teams")`; None → return; `w = self._width("#hm-teams")`; exception → `home_ops.teams_error_lines(res, w, compact=True)` else `home_ops.teams_lines(res, w)`; `query_one("#hm-teams", Static).update(self._lines(lines))` |

#### U3b — lcars.tcss

- After `#n-google { ... }`: `#n-teams { background: $lc-blue; }`.
- Focus rule: add `#hm-teams:focus` to the existing `#hm-mon:focus, ... #hm-mail-google:focus { ... }` selector list.
- After `#hm-calbox-google, #hm-mail-google { ... }`: `#hm-teams { border: round $lc-blue; }`.
- No height changes (`.hm-mail { height: 10; }` gives 8 content lines: header + 5 chats + spare).
- Sidebar at 45 rows: 13 blocks × 3 − 1 = 38 rows + spacer within the 40-row body — fits; documented as risk R-A5.

### GUI (U4–U6) — gui.py

#### U4 — `TeamsPane(tk.Frame)` (place after `GooglePane`)

Layout copies `OutlookPane.__init__`: title `Label` ("MICROSOFT TEAMS  //  CHATS (READ-ONLY)", ORANGE); pill bar
with `("RELOAD [R]", BLUE, lambda: self.reload(True))` and `("READ [L]", PERIWINKLE, self.view.focus_set)` (create
the bar after `self.view` exists or use a lambda); `RoundFrame` list (PERIWINKLE) holding `ttk.Treeview(columns=("m",
"a","b","c"), show="headings", selectmode="browse")` with headings `("", "TIME", "CHAT", "LAST MESSAGE")`, widths
`(50, 130, 260, 700)`, only `c` stretches; `RoundFrame` text (LAVENDER) holding a disabled `tk.Text` (`wrap="word"`,
`BODY_FONT`); status `Label` (BLUE).

Tags — Treeview: `unread` fg ORANGE + bold `BODY_FONT`; `mention` fg RED + bold. Text: `h` (LAVENDER bg, BLACK fg,
`LABEL_FONT`), `today` (ORANGE bg, BLACK fg, bold), `unread` ORANGE, `mention` RED bold, `dim` LAVENDER, `err` RED,
`row` default.

State fields identical to `TeamsView` plus `self.poll_job`, `self.msg_job` (Tk `after` ids).

| Method | Contract |
|---|---|
| keys (bound on both `tree` and `view`, returning `"break"`) | `r` → `reload(True)`; `j/k/g/G` → `move`; `<Control-d>`/`<Control-u>` → `move(±10)`; `l` → view focus; `h` → tree focus; `<Escape>` → `app.show_status`; tree `<Return>` → view focus; `bind_tab(tree, view)`; focus-ring `FocusIn` handlers as `OutlookPane` |
| `move(step)` | identical to `OutlookPane.move` |
| `open()` | `tree.focus_set()`; reload rule as `TeamsView.open` (`max_age=60`); start `_poll` if `poll_job is None` |
| `reload(retry=False, max_age=0.0)` | as TUI; uses `self.app.run_bg`; populates via `teams_cells`; `tree.insert(..., iid=chat_id, values=cells, tags=("mention",) if mentions else ("unread",) if unread else ())`; selects first row; exceptions → clear tree, `show_lines(teams_error_lines(e, 80, False))` |
| `show_lines(lines)` | write `(tag, text)` lines into `self.view` (normal → insert → disabled, `yview_moveto(0)`) |
| `<<TreeviewSelect>>` | debounce: `after_cancel(msg_job)`; `msg_job = self.after(300, self._load_messages)` |
| `_load_messages()` | same as TUI (cache by chat time, token check) |
| `_poll()` | `poll_job = None`; return if `app.view != "teams"`; if `state == "signin"` and `teams_ops.auth_state()["state"] in ("signed_in","failed")` → `reload()`; `poll_job = self.after(2000, self._poll)` |

#### U5 — `Dashboard` changes

| Location | Change |
|---|---|
| imports | add `teams_ops` to `from . import ...` |
| `_build()` nav tuple | add `("TEAMS\n[⇧F11 / Y]", BLUE, self.show_teams)` after the GMAIL entry; change nav `Pill(..., height=58)` to `height=54` (11 nav pills + theme + help must fit the 940-px default geometry, see R-A6) |
| `_build()` panes | `self.teams = TeamsPane(self.content, self)` after `self.google`; add `"teams": self.teams` to `self.panes` |
| `_bind_keys()` `on()` | add `"<Shift-F11>"` to the tuple of keys that work from any view; register `on("<Shift-F11>", self.show_teams)` and `on("<Key-y>", self.show_teams)` (letter acts from the status view only). Tk picks the more specific `<Shift-F11>` over `<F11>`, so GMAIL is unaffected |
| `HELP` | add `"teams"` entry with the same rows as TUI (`"Enter"` wording; `Ctrl+d / Ctrl+u` included); update `"home"` rows as in TUI |
| `GLOBAL_HELP` | insert `("⇧F11 / y", "Microsoft Teams chats (read-only)")` after the `F11 / i` entry |
| new `show_teams()` | `self.switch("teams"); self.teams.open()` (after `show_google`) |
| `apply_theme()` | Treeview tag tuple `("behind", "ahead", "bad", "busy")` → add `"unread", "mention"` |

#### U6 — `HomePane` changes

| Location | Change |
|---|---|
| `__init__` grid | `self.columnconfigure(tuple(range(6)), weight=1, uniform="col")` (6 uniform columns) |
| panels | monitor `col=0, span=6`; usage `col=0, span=3`; quick `col=3, span=3`; calendars `0/3, span=3`; inboxes `outlook col=0 span=2`, `google col=2 span=2`; **new** `self.teams_box = self.panel("TEAMS CHAT  //  UNREAD + MENTIONS", BLUE, 3, 4, span=2, go=go("show_teams"))` created last (so it is last in `self.order`, Tab cycle) |
| `panel()` | padx rule becomes `padx=(0, 6) if col + span < 6 else 0`; tag list adds `("mention", RED)` with bold font |
| status label | `grid(row=4, column=0, columnspan=6, ...)` |
| key bindings loop | include `self.teams_box`; `r` → `lambda: self.reload(retry=True)` |
| `__init__` | `self.teams_busy = False` |
| `reload(retry=False)` | status text `"Loading Outlook / Gmail / Teams / usage..."`; existing jobs unchanged; then `self.reload_teams(retry)` |
| new `reload_teams(retry=False)` | identical logic to TUI (`teams_busy` guard, `data["teams"]`, `render_teams()`) |
| `_auto()` | same sign-in completion check as TUI before rescheduling |
| `render_all()` | add `self.render_teams()` |
| new `render_teams()` | `put(self.teams_box, teams_error_lines(res, self.cols(t), True) if exception else teams_lines(res, self.cols(t)))` |

Row heights (`rowconfigure` weights `2,3,10,5`) unchanged; the Teams box shares the inbox row (FR-030).

## Data Design

No database. All Teams data is in memory, owned by the user's Microsoft 365 tenant; not retained beyond the
process (NFR-003). Caches: `_auth.me` (process lifetime), `summary` result (≤ `max_age`), UI `msg_cache` per view
(process lifetime, keyed by chat id, invalidated when the chat's last-message time changes).

### Files

| Path | Owner | Access | Format |
|---|---|---|---|
| `~/.lcars_dash/teams_config.json` | user | read only | `{"client_id": "<GUID>", "tenant_id": "<GUID or domain>"}` (extra keys ignored) |
| `~/.lcars_dash/teams_token.bin` | MSAL / msal-extensions | read/write | DPAPI-encrypted MSAL cache; never plaintext |
| `~/.lcars_dash.json` | existing config | **not touched** by this feature | — |

### Entities (dicts; documented as `TypedDict`s in `teams_ops.py` for readability)

`Chat`: `id: str`, `title: str`, `chat_type: str`, `members: list[str]`, `preview: str` (single line),
`sender: str`, `time: datetime | None` (naive local), `time_utc: datetime | None` (aware),
`last_read_utc: datetime | None`, `unread: bool`, `web_url: str` (`""` if absent), `mentions: int`,
`mentions_capped: bool`.

`Message`: `id: str`, `time: datetime | None`, `time_utc: datetime | None`, `sender: str`, `sender_id: str`,
`text: str` (multi-line plain text), `mentions_me: bool`, `deleted: bool`, `system: bool`.

`Summary`: `unread_chats: int`, `mentions: int`, `latest: list[Chat]`, `chats: list[Chat]`, `me: str`,
`capped: bool`, `loaded_at: datetime`, `cache_notice: str`.

`AuthState` (from `auth_state()`): `state: str`, `user_code: str`, `verification_uri: str`, `message: str`,
`error: str`, `cache_notice: str`.

## Interface Contracts

### Exceptions

```python
class TeamsError(Exception): ...
class TeamsNotConfigured(TeamsError):      # str() == NOT_CONFIGURED_MSG + f"\nReason: {reason}"
    def __init__(self, reason: str = ""): ...
class TeamsMissingLibrary(TeamsError): ...
class TeamsBadRequest(TeamsError): ...
class TeamsSignInRequired(TeamsError):
    user_code: str; verification_uri: str; message: str; expires_at: float
    @classmethod
    def from_flow(cls, flow: dict) -> "TeamsSignInRequired"   # str() == f"Sign in at {uri} with code {code}"
```

`NOT_CONFIGURED_MSG` (exact):

```text
Teams not configured: create ~/.lcars_dash/teams_config.json
Setup:
1. Entra ID (Azure AD) > App registrations > New registration (single tenant).
2. Authentication > enable "Allow public client flows" (device code flow).
3. API permissions > Microsoft Graph > Delegated > Chat.Read and User.Read, then grant consent.
4. Copy the Application (client) ID and Directory (tenant) ID into the file as
   {"client_id": "...", "tenant_id": "..."}
5. pip install msal msal-extensions requests
```

### MSAL surface used (and faked in tests)

`msal.PublicClientApplication(client_id, authority=..., token_cache=...)`, `.get_accounts()`,
`.acquire_token_silent(scopes, account=, force_refresh=)`, `.initiate_device_flow(scopes=)`,
`.acquire_token_by_device_flow(flow)`, `.remove_account(account)`; `msal.TokenCache()`;
`msal_extensions.build_encrypted_persistence(path)`, `msal_extensions.PersistedTokenCache(persistence)`.
Device flow dict keys used: `user_code`, `verification_uri`, `message`, `expires_at`, `error`, `error_description`.

### UI ↔ teams_ops contract

- UI threads may call only `auth_state()` and `retry_sign_in()` directly (non-blocking).
- `chats`, `messages`, `summary` are called **only** inside `run_bg` workers.
- Exceptions are delivered as values to `done` callbacks and rendered via `home_ops.teams_error_lines`.

## API Definitions

All requests: `GET`, `Authorization: Bearer <token>`, `Accept: application/json`, timeout 20 s.

| Purpose | Request | Fields consumed |
|---|---|---|
| Identity | `GET /me?$select=id,displayName` | `id`, `displayName` |
| Chats | `GET /me/chats?$expand=members,lastMessagePreview&$orderby=lastMessagePreview/createdDateTime desc&$top=50` | `value[].id, topic, chatType, webUrl, viewpoint.lastMessageReadDateTime, members[].displayName, members[].userId, lastMessagePreview.{createdDateTime, isDeleted, messageType, body.{contentType,content}, from.user.{id,displayName}}`, `@odata.nextLink` |
| Chats (fallback on 400) | `GET /me/chats?$expand=lastMessagePreview&$orderby=...&$top=50` + `GET /me/chats/{id}/members` per untitled chat | same |
| Messages | `GET /me/chats/{id}/messages?$top=N&$orderby=createdDateTime desc` | `value[].id, messageType, createdDateTime, deletedDateTime, from, body, mentions[].mentioned.user.id, attachments` |
| Paging | `GET <@odata.nextLink>` (must start with `https://graph.microsoft.com/v1.0/`) | as above |

Auth endpoints are called by MSAL only: `https://login.microsoftonline.com/<tenant_id>/...` (discovery, devicecode, token).

## Configuration Strategy

- Teams settings only in `~/.lcars_dash/teams_config.json` (FR-001); no env vars, no CLI flags, no defaults for ids.
- Tunables are module constants in `teams_ops.py` (C1); not user-configurable (YAGNI).
- `~/.lcars_dash.json` unchanged; `config.py` unchanged.
- No secrets: public client (no client secret); ids are not secrets but live only in the user file.

## Logging Strategy

The project has no log files; diagnostics are surfaced in UI status lines. Consistent with that:

- User-visible diagnostics: TEAMS status line (`teams_status`, state, cache notice), TEAMS text pane (full error /
  setup / sign-in text), HOME box (compact lines), and the existing statusbar.
- `logging.getLogger("lcars_dash.teams")` at `DEBUG` only (request path, status, elapsed; flow state transitions).
  No handler is installed by the app, so nothing is emitted unless a developer configures logging.
- Never logged/printed/included in exceptions: access/refresh tokens, `Authorization` header, token cache contents,
  message bodies.

## Error Handling Strategy

| Failure | Raised as | TEAMS tab | HOME box |
|---|---|---|---|
| Config missing/invalid | `TeamsNotConfigured` | full setup text | `Teams not configured - open TEAMS (y) for setup` |
| msal/requests missing | `TeamsMissingLibrary` | `TEAMS LIBRARIES MISSING` + pip line | `Teams libraries missing - pip install ...` |
| Sign-in needed / pending | `TeamsSignInRequired` | URL, code, "Waiting for sign-in... (r to retry)"; 2 s poll auto-reloads | `Sign in: <url>  code <code>` |
| Sign-in expired/declined/error | `TeamsError("Teams sign-in failed: <reason> (press r to retry)")` | `Error: ...`; `r` → `retry_sign_in()` + new flow | `Error: ...` (HOME `r` also retries) |
| Token cache not encrypted-capable | notice string (not an exception) | appended to status line | — |
| 401 / 403 / 429 / 503 / network / bad JSON / other | per C6 table | `Error: ...` | `Error: ...` |
| Messages load failure | any `TeamsError` | error lines in message pane; list stays | — |
| Unexpected exception | wrapped to `TeamsError(str(e))` by `_wrap`; `run_bg` also catches all `Exception` | `Error: ...` | `Error: ...` |

Recovery: every state is recoverable with `r` (TEAMS / HOME) or automatically (sign-in completion poll, 5-min HOME
refresh, stale reload on tab open). A Teams failure never affects other boxes/tabs (NFR-005): HOME jobs are
independent `run_bg` calls; each render function handles its own key.

## Threading Approach

| Toolkit | Worker mechanism | Result delivery | Timers |
|---|---|---|---|
| Textual | `LcarsDash.run_bg(fn, then)` → `run_worker(thread=True, exit_on_error=False)` | `call_from_thread(then, res)` (event loop) | `set_interval(2, _poll)` (TeamsView), HomeView `_auto` (2 s), `set_timer(0.3)` debounce |
| Tk | `Dashboard.run_bg(fn, then)` → daemon `threading.Thread` | `queue.Queue` drained by `_pump` every 100 ms on Tk main thread | `after(2000, _poll)`, HomePane `_auto` (2 s), `after(300)` debounce |
| teams_ops | device-flow daemon thread `teams-device-flow`; `ThreadPoolExecutor(4)` inside `summary()` (runs within a worker) | state fields under `_lock`; UIs poll `auth_state()` | none |

Invariants: no Tk/Textual widget is touched off the UI thread; no UI thread call performs I/O or waits on
`_init_lock`; `_lock` is never held across I/O; at most one device flow exists (`_init_lock` + state check); stale
results are discarded via per-view tokens; `teams_busy` prevents overlapping HOME Teams loads.

## Security Considerations

- **Trust boundaries**: (1) Graph responses — untrusted content; (2) user config file — semi-trusted input;
  (3) token cache file — sensitive at rest; (4) MSAL/Microsoft endpoints — trusted via HTTPS.
- **Least privilege**: delegated `Chat.Read`, `User.Read` only (+ implicit `offline_access`, `openid`, `profile`).
  Test asserts the exact scope list.
- **Read-only**: only `requests.get`; URL guard rejects non-Graph hosts and `/teams/`, `/channels/` paths.
- **Token protection**: DPAPI-encrypted cache or memory only; tokens never logged/displayed/in exception text;
  `@odata.nextLink` host check prevents sending the bearer token to another host.
- **Input validation**: `client_id` GUID regex and `tenant_id` hostname-safe regex (authority URL injection);
  `chat_id` regex + percent-encoding (path traversal); JSON shape checks (`dict`, `list`) with `.get` defaults.
- **Output encoding**: chat text rendered as plain text — TUI uses `rich.text.Text` objects (never markup strings,
  including DataTable cells); control characters (incl. ESC) stripped in `html_to_text` (terminal injection);
  Tk widgets are plain text.
- **Privacy**: no on-disk storage of chat content; no telemetry.
- **Device code phishing**: the app displays only the `verification_uri`/`user_code` returned by MSAL; it never
  opens URLs from chat content.
- For the Security Engineer: review DPAPI fallback, URL guard, markup-injection handling, and lock usage.

## Deployment Considerations

New files (repo root):

`requirements.txt`

```text
textual>=8.0
rich>=13.0
pywin32>=306; sys_platform == "win32"
google-api-python-client>=2.100
google-auth-oauthlib>=1.0
msal>=1.28
msal-extensions>=1.3
requests>=2.32.4
```

`requirements-dev.txt`

```text
-r requirements.txt
pytest>=8.0
```

`pytest.ini`

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- Install: `pip install -r requirements.txt` (Teams works only after `msal`, `msal-extensions` are installed).
- Local execution only; Windows (DPAPI). Network needed only for Teams features.
- Line endings: all new/edited `.py` files **CRLF** (verify: every `\n` in the file is preceded by `\r`).
  `.md`, `.txt`, `.ini`, `.tcss` keep whatever the editor writes (CRLF preferred for consistency).
- No change to launch commands (`python -m lcars_dash`, GUI `python -m lcars_dash.gui`).

## Test Plan and File Layout

```text
tests/
  conftest.py                  autouse fixtures (below)
  teams_fakes.py               FakeMsalModule/FakeApp, FakeExtensions, FakeResponse, graph JSON builders
  test_teams_config.py         FR-001, FR-002, FR-003, FR-004
  test_teams_auth.py           FR-005, FR-007, FR-008, FR-009, FR-010, FR-011
  test_teams_graph.py          FR-018, FR-019, URL guard, paging
  test_teams_parse.py          FR-013, FR-014, FR-015, FR-016, FR-017
  test_home_teams_lines.py     FR-029, teams_error_lines, teams_message_lines, teams_cells, teams_status
  test_tui_teams_smoke.py      FR-030 (TUI), FR-031, FR-035, FR-037
  test_gui_teams_smoke.py      FR-030 (GUI), FR-036, FR-037
```

`conftest.py` autouse fixtures:

1. **No network**: monkeypatch `socket.socket.connect`, `socket.socket.connect_ex`, `socket.create_connection`
   to raise `RuntimeError("network access in tests")`.
2. **Paths**: `teams_ops.DIR/CONFIG_FILE/TOKEN_FILE` → `tmp_path/".lcars_dash"/...`; `config.CONFIG_FILE` →
   `tmp_path/"lcars_dash.json"`; `tests_ops.RESULTS_FILE` → tmp; `google_ops.DIR/SECRET/TOKEN` → tmp (NFR-007).
3. **Mindchuk**: `mindchuk_ops.add` and `mindchuk_ops.run` patched to raise `AssertionError("mindchuk called")`.
4. **State**: `teams_ops._reset()` before and after each test; `time.sleep` patched in `teams_ops` where needed.
5. A `fake_msal` fixture installs `FakeMsalModule` via `monkeypatch.setitem(sys.modules, "msal", ...)`; a
   `graph` fixture patches `requests.get` with a routed fake and `requests.post/put/patch/delete/request` with
   failures; missing-library tests use `monkeypatch.setitem(sys.modules, "msal", None)`.
6. Smoke fixture `quiet_ops`: patch `git_ops.discover_all → []`, `live_ops.snapshot → []`,
   `copilot_ops.today_usage → minimal dict`, `outlook_ops.mail/events → []`, `google_ops.mail/events → []`,
   `teams_ops.summary → (configurable: TeamsNotConfigured or sample summary)`, `teams_ops.messages → sample`.

Required cases (each maps to acceptance criteria below): no config / invalid JSON / not object / missing key /
bad GUID → `TeamsNotConfigured` with exact prefix and "public client", "device code", "Chat.Read", and zero HTTP
calls; `import lcars_dash.teams_ops` with `sys.modules["msal"] = None` succeeds and `chats()` raises
`TeamsMissingLibrary` containing `pip install msal msal-extensions requests`; scopes passed to
`initiate_device_flow` and `acquire_token_silent` equal `["Chat.Read", "User.Read"]`; device flow exposes code/URL
before completion (fake completion blocked on `threading.Event`); two threads → one `initiate_device_flow` and the
same code; completion success → `auth_state()["state"] == "signed_in"`; expiry → `failed` and message contains
"press r to retry"; `retry_sign_in()` → next call starts a new flow; FR-010 with `msal_extensions` = None → no
`teams_token.bin`, notice text exposed in `auth_state()` and `summary()["cache_notice"]`; FR-009 with a fake
encrypted persistence → `PersistedTokenCache` used with `TOKEN_FILE`; FR-013 oneOnOne / group+topic /
group-no-topic / meeting / no preview / two pages / 400 fallback; FR-014 text / html / mention me / mention other /
system / deleted, oldest→newest; FR-015 table (`<br>`, `</p>`, `</div>`, entities, `<at>`, `<img>`,
`<attachment>`, `<emoji alt>`, blank-line collapse, plain passthrough, single-line preview, ESC stripped,
`&lt;b&gt;` stays literal); FR-016 3 chats (2 unread, one with 2 me-mentions + 1 other) → `unread_chats == 2`,
`mentions == 2`, plus capped cases; FR-017 `/me` called once across two calls; FR-018 every recorded call is GET and
no URL has `/teams/` or `/channels/`, foreign `nextLink` rejected; FR-019 401→refresh→success, 401×2 →
`TeamsSignInRequired`, 403 text, 429 with `Retry-After: 3` → `sleep(3)` then success, 429×2 → throttling text,
`Retry-After: 99` → `sleep(10)`, timeout → "Cannot reach Microsoft Graph", invalid JSON; FR-029 loaded / empty /
width truncation / header tag selection.

TUI smoke (`asyncio.run` of `LcarsDash([tmp_path]).run_test(size=(160, 45))`, no pytest-asyncio needed): press
`shift+f11` → `current_view == "teams"`; `escape` → status; `y` (table focused) → teams; `pilot.click("#n-teams")`
→ teams; `f12` → home; press `tab` until `focused.id == "hm-teams"` (≤ `len(GO)` presses); `enter` → teams. Run
with summary mocked as not-configured and as loaded (rows rendered, no crash). FR-030: on HOME every `GO` widget
plus `#hm-cal-outlook/google` has non-zero `size`, and `HomeView.max_scroll_y == 0`. Cycle theme (`f5`) once and
re-check no crash (FR-037). Restore: `config.CONFIG_FILE` is the tmp file, so the theme save is isolated.

GUI smoke (skip if `tk.Tk()` raises `TclError`): build `gui.Dashboard([tmp_path])`, pump
(`for _ in range(40): app.update(); time.sleep(0.05)`), `show_teams()`, pump, assert tree rows for loaded summary;
`show_home()`, pump, assert every `HomePane.order` widget `winfo_ismapped()` and `winfo_height() > 10`; `destroy()`.

Command: `python -m pytest` from the repo root.

## Acceptance Criteria

| Req | Measurable criteria |
|---|---|
| FR-001 | Fake MSAL records `client_id` from file and `authority == "https://login.microsoftonline.com/<tenant_id>"` |
| FR-002 | Each invalid-config case raises `TeamsNotConfigured`; `str(e).startswith("Teams not configured: create ~/.lcars_dash/teams_config.json")`; contains "public client", "device code", "Chat.Read"; 0 HTTP calls |
| FR-003 | Import succeeds with `msal` absent; public calls raise `TeamsMissingLibrary` with install hint; TUI/GUI smoke pass with `msal` absent |
| FR-004 | Scope list asserted equal to `["Chat.Read", "User.Read"]` in every MSAL call |
| FR-005 | `TeamsSignInRequired.user_code/verification_uri/message` set while completion still blocked |
| FR-006 | TUI smoke: during pending sign-in, switching tabs works; TEAMS text pane contains URL and code |
| FR-007 | Two concurrent callers → `initiate_device_flow` call count == 1; both exceptions carry the same code |
| FR-008 | Success → `signed_in` and TEAMS poll reloads (state `loaded`); expiry → message contains "Teams sign-in failed" and "press r to retry"; after `retry_sign_in()` a new flow is initiated |
| FR-009 | With fake extensions: `build_encrypted_persistence(str(TOKEN_FILE))` called; `DIR` created. Manual: file exists after sign-in and is not valid JSON |
| FR-010 | With `msal_extensions` absent: `TOKEN_FILE` not created; notice starts with "Teams token cache unavailable"; TEAMS status shows it |
| FR-011 | Cached account → `acquire_token_silent` used, no device flow; silent failure → `TeamsSignInRequired` |
| FR-012 | `teams_ops` imports no UI modules (test greps `tkinter`/`textual`/`rich` absence); all failures are `TeamsError` |
| FR-013 | Six fixture scenarios produce exact expected dicts and order; pagination follows `nextLink` |
| FR-014 | Six message scenarios produce expected `text`, `sender`, `mentions_me`, `deleted`, order oldest→newest |
| FR-015 | All table rows in the C8 test table pass |
| FR-016 | `unread_chats == 2`, `mentions == 2` for the specified fixture; `capped` true when > 15 unread chats or full scan window |
| FR-017 | `/me` requested once per process (until `_reset()`/account removal) |
| FR-018 | All recorded requests GET; no `/teams/` or `/channels/`; non-Graph `nextLink` → `TeamsError` |
| FR-019 | Each status-code test passes as per C6 table |
| FR-020/021 | Pill `#n-teams` directly after `#n-google`; `shift+f11`, `y` (status view), pill click open TEAMS; existing bindings unchanged |
| FR-022–024 | Loaded rows show markers/time/title/last; selecting loads messages; each state renders the specified text without exception |
| FR-025/028 | `HELP["teams"]` exists in TUI and GUI with sign-out row; `GLOBAL_HELP` contains `("⇧F11 / y", ...)`; HOME help lists Teams |
| FR-026/027 | GUI pill after GMAIL; `<Shift-F11>` from any view, `y` from status view; `TeamsPane` states as TUI |
| FR-029 | `teams_lines` tests pass |
| FR-030 | TUI 160×45 and GUI default geometry: all HOME boxes non-zero; no HOME vertical scroll |
| FR-031 | Tab cycle reaches `hm-teams`; Enter/click opens TEAMS (both UIs) |
| FR-032 | HOME shows compact lines for each state; other boxes render with Teams raising; HOME `r` includes Teams |
| FR-033 | `requirements.txt` lists `msal`, `msal-extensions`, `requests` |
| FR-034–036 | `python -m pytest` green with network blocked and mindchuk guarded |
| FR-037 | Existing smoke paths (F1–F12 views, theme cycle) still pass; `~/.lcars_dash.json` unchanged |

## Risks

| Id | Description | Impact | Mitigation |
|---|---|---|---|
| R-A1 | `$expand=members,lastMessagePreview` combination may be rejected (400) by Graph | Titles unavailable | Sticky fallback to preview-only + per-chat `/members` (bounded by limit) |
| R-A2 | `$expand=members` caps at 25 members | Group titles truncated | Acceptable; title is a hint; topic used when set |
| R-A3 | `viewpoint` missing/stale (incl. own last message) over-reports unread (R-3) | Inflated counts | Follow approved definition; document; revisit with stakeholder |
| R-A4 | Mention scanning many unread chats → throttling / latency | Slow HOME, 429 | Caps (15 chats × 20 msgs), 4 workers, Retry-After once, `capped` flag shown as `+` |
| R-A5 | TUI sidebar height at 45 rows is exactly enough for 13 blocks | Help pill clipped on shorter terminals | Spacer absorbs; `y`/`?` keys remain; smoke at 160×45 |
| R-A6 | GUI sidebar at default 940 px height | Clipped pills | Nav pill height 58 → 54 |
| R-A7 | Terminals intercept Shift+F11 (R-6) | Key unavailable | `f23` alias, `y`, pill click |
| R-A8 | MSAL authority discovery at app construction needs network | Construction failure offline | Wrapped as "Cannot reach Microsoft sign-in"; retried on next call (app not cached on failure) |
| R-A9 | Device-flow thread keeps polling up to ~15 min | Minor background traffic | Daemon thread; ends at expiry or app exit |
| R-A10 | DPAPI cache probe passes but later write fails | Sign-in not remembered | Error surfaced as "Teams token cache error"; no plaintext fallback |
| R-A11 | Tenant blocks consent / device flow (R-1) | Feature unusable | Clear 403 and sign-in failure messages |
| R-A12 | Editors writing LF for new `.py` files | NFR-006 breach | Explicit CRLF check in review |

## Assumptions

- ASSUMPTION-A1: Graph v1.0 supports `$orderby=lastMessagePreview/createdDateTime desc` and `$top` ≤ 50 for
  `/me/chats` (documented); client-side sort is applied anyway.
- ASSUMPTION-A2: `$orderby=createdDateTime desc` is supported on `/me/chats/{id}/messages` with `$top` ≤ 50.
- ASSUMPTION-A3: `msal_extensions.build_encrypted_persistence` selects DPAPI file persistence on Windows.
- ASSUMPTION-A4: Textual reports Shift+F11 as `shift+f11` or `f23`; Tk reports `<Shift-F11>`.
- ASSUMPTION-A5: Mention scan caps `MENTION_SCAN = 20`, `MAX_SCAN_CHATS = 15` are acceptable (FR-016 tunable).
- ASSUMPTION-A6: Chat list colour: BLUE pill/border (distinct from GMAIL PEACH) in both UIs.
- ASSUMPTION-A7: System/event messages are shown as `[event]` (dimmed), not skipped.
- ASSUMPTION-A8: `client_id` is always a GUID (Entra application ids are GUIDs).
- ASSUMPTION-A9: Opening the TEAMS tab within 60 s of a HOME load may reuse that summary (`max_age=60`).
- Requirements assumptions ASSUMPTION-001 … 010 apply unchanged.

## Approval Status

**APPROVED** — 2026-11-10, Software Architect. Stakeholder absent; design decisions taken under delegated
authority and recorded above (Risks, Assumptions A1–A9). Ready for the Senior Project Manager.
