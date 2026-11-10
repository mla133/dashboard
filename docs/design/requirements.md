# Project Requirements — Microsoft Teams Chat (read-only) for LCARS Dashboard

Document root: `docs/` · Work item: Teams integration · Date: 2026-11-10 · Author: Requirements Analyst

## Overview

Add a read-only **Microsoft Teams chat** capability to the existing `lcars_dash` package. The dashboard has two
front-ends sharing data modules:

- **GUI** — Tkinter, `lcars_dash/gui.py` (sidebar of nav pills, `OutlookPane`/`GooglePane` list+text panes, `HomePane`).
- **TUI** — Textual, `lcars_dash/app.py` (sidebar `NavBlock`s, `ContentSwitcher` views, `HELP`/`GLOBAL_HELP` tables),
  `lcars_dash/tui_panes.py` (views incl. `OutlookView`/`GoogleView`), `lcars_dash/tui_home.py` (`HomeView`),
  `lcars_dash/lcars.tcss` (styles).
- **Data modules** — `outlook_ops.py`, `google_ops.py` (pattern: module-level `XxxError`, lazy library imports
  raising a friendly error, no UI code), `home_ops.py` (shared HOME formatting returning `(tag, text)` lines).

This work adds a new data module `lcars_dash/teams_ops.py`, a new **TEAMS** tab in both GUI and TUI, and a compact
Teams section on the HOME pane. Scope is limited to **1:1 / group / meeting chats**: listing, reading, unread counts,
and @mentions of the signed-in user. Nothing is ever written to Teams.

## Problem Statement

The stakeholder uses the LCARS dashboard as a one-screen daily overview (Copilot activity, Outlook and Gmail mail and
calendars, Mindchuk). Teams chats are not visible, so the stakeholder must switch to the Teams client to learn whether
anyone is waiting on them (unread chats, @mentions). This breaks the "one screen" goal and causes missed or delayed
responses. Impact: context switching several times per day; risk of overlooking mentions.

## Business Goals

- BG-1: See at a glance, from HOME, how many Teams chats are unread and how many messages @mention the user.
- BG-2: Read recent chat conversations inside the dashboard without opening Teams.
- BG-3: Zero risk of side effects in Teams (strictly read-only; no channel access).
- BG-4: The dashboard must remain fully usable when Teams is not configured, not signed in, or unreachable.

Success: the stakeholder can identify unread chats and mentions from HOME and read their content from the TEAMS tab
without opening the Teams client; no regressions in existing tabs.

## Stakeholders

| Role | Who | Responsibility |
|---|---|---|
| Primary stakeholder / sole user | Dashboard owner (allenma) | Approves requirements; registers Entra app; supplies `client_id`/`tenant_id` |
| System owner (Teams / Entra ID) | Owner's Microsoft 365 tenant admins | Tenant policy for app registrations and consent to `Chat.Read` |
| Engineering team | Architect, Developer, Tester, Reviewers | Build and verify per this document |

## Users

- Single user: a software engineer running the dashboard locally on their own Windows workstation, keyboard-centric
  (vim-style keys), comfortable editing JSON config files and following short setup steps.
- Volume: one user, one Microsoft 365 account.

## Definitions

- **Chat**: a Microsoft Graph `chat` resource (oneOnOne, group, meeting chat). **Channel messages are out of scope.**
- **Unread chat**: a chat where `viewpoint.lastMessageReadDateTime` is earlier than
  `lastMessagePreview.createdDateTime` (from `GET /me/chats?$expand=lastMessagePreview`). If `viewpoint` or
  `lastMessageReadDateTime` is missing/null and a preview exists, the chat is unread. If there is no
  `lastMessagePreview`, the chat is read.
- **Mention of me**: a chat message whose `mentions[]` contains an entry with `mentioned.user.id` equal to the
  signed-in user's id (from `GET /me`).
- **Teams config file**: `~/.lcars_dash/teams_config.json` containing `{"client_id": "...", "tenant_id": "..."}`.
- **Token cache**: `~/.lcars_dash/teams_token.bin`, encrypted with DPAPI via msal-extensions.

## Functional Requirements

### A. Configuration and authentication (teams_ops)

**FR-001 — Config file location and format.** `teams_ops` shall read Teams settings only from
`~/.lcars_dash/teams_config.json`, a JSON object with string keys `client_id` and `tenant_id`.
*Acceptance:* with a valid file, `teams_ops` builds the MSAL public client with that `client_id` and authority
`https://login.microsoftonline.com/<tenant_id>`.

**FR-002 — Not configured: graceful degradation.** If the config file is missing, unreadable, not valid JSON, not an
object, or `client_id`/`tenant_id` is missing/empty, every public `teams_ops` function shall raise `TeamsError` whose
message begins with `Teams not configured: create ~/.lcars_dash/teams_config.json` and includes short setup steps:
(1) Entra ID (Azure AD) → App registrations → New registration (single tenant); (2) Authentication → enable
"Allow public client flows" (device code flow); (3) API permissions → Microsoft Graph → Delegated → `Chat.Read`
(plus `User.Read`), then grant/consent; (4) copy the Application (client) ID and Directory (tenant) ID into the file as
`{"client_id": "...", "tenant_id": "..."}`.
*Acceptance:* unit test with no config file → `TeamsError` raised; message starts with the exact prefix and contains
"public client", "device code" and "Chat.Read"; no network call; no exception other than `TeamsError` escapes. Same
for invalid JSON and missing keys.

**FR-003 — Missing libraries.** If `msal` or `requests` cannot be imported, public functions shall raise `TeamsError`
naming the packages to install (`pip install msal msal-extensions requests`). Imports shall be lazy (inside
functions) so importing `teams_ops` and launching GUI/TUI never fails because these packages are absent.
*Acceptance:* `import lcars_dash.teams_ops` succeeds with msal uninstalled; GUI/TUI start smoke tests pass without msal.

**FR-004 — Scopes.** Authentication shall request exactly the delegated scopes `Chat.Read` and `User.Read`
(MSAL adds `offline_access`/`openid`/`profile` implicitly; `offline_access` must be in effect so refresh tokens are
cached). No other scopes (in particular no `ChannelMessage.*`, `Chat.ReadWrite`, `Calendars.*`) shall be requested.
*Acceptance:* unit test asserts the scope list passed to MSAL.

**FR-005 — Device code flow.** When no token can be acquired silently, `teams_ops` shall start the MSAL device code
flow and expose `user_code`, `verification_uri` and the human-readable message to the caller so the UI can display
them. Interactive browser/local-server flows shall not be used.
*Acceptance:* with a mocked MSAL app returning a flow, the caller receives code and URL before completion is awaited.

**FR-006 — Non-blocking sign-in.** Sign-in (device-code polling) shall never block the Tk main loop or the Textual event
loop; it runs on a worker thread (same pattern as existing Outlook/Gmail loads). While waiting, the TEAMS pane shows the
verification URL, the user code, and "Waiting for sign-in... (r to retry)". Other tabs remain fully usable.
*Acceptance:* manual + smoke: switching tabs during a (mocked) pending sign-in works; the pane shows URL and code.

**FR-007 — Single sign-in at a time.** Only one device-code flow may be in progress per process. Concurrent callers
(TEAMS tab and HOME section) share it; a second caller receives the same pending code/URL state.
*Acceptance:* unit test with mocked MSAL: two concurrent requests → `initiate_device_flow` called once.

**FR-008 — Sign-in outcome.** On success the token is cached (FR-009) and the waiting pane reloads automatically. On
expiry, decline, or error, `TeamsError` is raised with a message such as `Teams sign-in failed: <reason> (press r to
retry)`; pressing `r` starts a new flow.

**FR-009 — Encrypted token cache.** The MSAL token cache shall be persisted at `~/.lcars_dash/teams_token.bin`,
encrypted with DPAPI via msal-extensions. The `~/.lcars_dash` directory is created if absent.
*Acceptance:* after sign-in the file exists and is not plaintext JSON; subsequent starts acquire tokens silently.

**FR-010 — Token cache fallback.** If msal-extensions is not installed or encrypted persistence cannot be created
(e.g. DPAPI unavailable), `teams_ops` shall **not** write an unencrypted token to disk. It continues with an in-memory
cache for the current process and surfaces a clear notice, e.g.
`Teams token cache unavailable (<reason>); sign-in will not be remembered. pip install msal-extensions`,
shown in the TEAMS pane status line. Teams features still work for the session.
*Acceptance:* unit test with msal_extensions import forced to fail → no `teams_token.bin` written; notice text exposed.

**FR-011 — Silent refresh.** Before Graph calls, `teams_ops` attempts `acquire_token_silent` for the cached account;
only if that fails is device-code sign-in required (FR-005). A call made while sign-in is required raises a
`TeamsError` subclass (or carries a flag) that the UI can identify as "sign-in required", carrying code and URL.

### B. Data API (teams_ops)

**FR-012 — Module contract.** `lcars_dash/teams_ops.py` contains no UI code and exposes: `TeamsError(Exception)`,
`chats(limit=...)`, `messages(chat_id, limit=...)`, `summary()`. All Graph/HTTP/auth exceptions are wrapped as
`TeamsError` (pattern of `outlook_ops`/`google_ops`). Base URL `https://graph.microsoft.com/v1.0`.

**FR-013 — chats().** Returns recent chats, most recent activity first, using
`GET /me/chats?$expand=lastMessagePreview` (members via `$expand=members` or a separate request; follows
`@odata.nextLink` until `limit` reached; default limit 50). Each item is a dict with at least:
`id`, `title` (topic if set; else comma-joined display names of other members, excluding me; else the chat type),
`chat_type`, `members` (list of display names), `preview` (HTML-stripped last message text, single line),
`sender` (display name of last message sender, or "" for system events), `time` (naive local `datetime` of last
message, or None), `unread` (bool per Definitions), `web_url` (if provided).
*Acceptance:* unit tests with mocked JSON for oneOnOne, group with topic, group without topic, meeting chat, chat with
no preview, and a paginated response produce the expected dicts and order.

**FR-014 — messages(chat_id).** Returns messages of one chat via `GET /me/chats/{id}/messages` (default limit 50),
oldest-to-newest for display; each dict has at least `id`, `time` (naive local datetime), `sender` (display name; ""
for system messages), `text` (HTML-stripped body), `mentions_me` (bool), `deleted` (bool). System/event messages are
shown with placeholder text `[event]` or skipped; deleted messages shown as `[deleted]`.
*Acceptance:* unit tests on mocked JSON cover text body, HTML body, mention of me, mention of someone else, system
event, deleted message.

**FR-015 — HTML stripping.** Bodies with `contentType == "html"` are converted to plain text: tags removed;
`<br>`, `</p>`, `</div>` become line breaks in `messages()` (collapsed to single spaces in `chats()` previews); HTML
entities unescaped; `<at>Name</at>` rendered as `@Name`; images/attachments rendered as `[image]`/`[attachment]`;
runs of blank lines collapsed. Plain-text bodies pass through unchanged (apart from trimming).
*Acceptance:* table-driven unit tests for each rule.

**FR-016 — summary().** Returns a dict with at least `unread_chats` (int, unread chats among `chats()`), `mentions`
(int, messages @mentioning me in unread chats that are newer than that chat's `lastMessageReadDateTime`), `latest`
(the first N chats from `chats()`, default 5), `me` (display name), and `capped` (bool, true if mention scanning hit
its limit). Mention scanning is limited to unread chats and to a fixed number of recent messages per chat (default 20;
tunable by the architect).
*Acceptance:* unit test with 3 mocked chats (2 unread; one containing 2 mentions of me and 1 of another user) →
`unread_chats == 2`, `mentions == 2`.

**FR-017 — Signed-in identity.** The user id used for mention matching comes from `GET /me` (User.Read) and may be
cached for the process lifetime.

**FR-018 — Read-only.** `teams_ops` issues only HTTP GET requests to Graph (plus MSAL auth endpoints). It never marks
chats read, sends, edits, reacts or deletes. No team/channel endpoints (`/teams/`, `/channels/`) are called.
*Acceptance:* unit tests assert every mocked HTTP call is a GET and no URL contains `/teams/` or `/channels/`.

**FR-019 — Graph error handling.** HTTP 401 → one silent re-acquire and retry, then "sign-in required"; 403 →
`TeamsError` mentioning missing `Chat.Read` consent; 429/503 → honour `Retry-After` once (max ~10 s) then
`TeamsError("Teams is throttling requests, try again later")`; network errors/timeouts (per-request timeout ≤ 20 s)
→ `TeamsError("Cannot reach Microsoft Graph: ...")`; malformed JSON → `TeamsError`.
*Acceptance:* unit tests per status code with mocked responses.

### C. TEAMS tab — TUI (Textual)

**FR-020 — Sidebar pill.** A `NavBlock("TEAMS\n[⇧F11 / Y]", "show_teams", id="n-teams")` placed directly under the
GMAIL pill in `app.py`, with a `#n-teams` rule in `lcars.tcss` using an LCARS palette colour distinct from the GMAIL
pill.

**FR-021 — Key bindings.** `shift+f11` (app-level, works from any view) and `y` (added wherever the other letter tab
keys live, i.e. the repository-list bindings) open the TEAMS view. No existing binding changes.

**FR-022 — View layout.** A `TeamsView` in `tui_panes.py` (following the `ListTextView`/`OutlookView` pattern) shows a
chat list and a message pane. Each chat row: unread marker (`*`), mention marker (`@`) when the chat has unread
mentions of me, time (`%m-%d %H:%M`), title, sender and preview truncated to width. Unread rows use a distinct
highlight style. Selecting a chat loads `messages(chat_id)` on a worker and displays `HH:MM  Sender: text` grouped by
day, with mentions of me highlighted.

**FR-023 — Keys inside TEAMS.** `j/k`, `g/G`, `Ctrl+d/Ctrl+u` move; `l`/`Enter` focus the message pane; `h` back to
the list; `r` reload chats (and restart sign-in if it failed/expired); `Esc` back (as in other views). No key performs
any write action.

**FR-024 — States.** The view renders distinct, non-crashing states: *not configured* (full FR-002 message with setup
steps), *libraries missing* (FR-003), *sign-in pending* (URL + code, FR-006), *loading*, *error* (`Error: ...`),
*empty* ("No chats"), *loaded*. A status line shows chat count, unread count, last reload time and any token-cache
notice (FR-010).

**FR-025 — Help.** `HELP["teams"]` entry in `app.py` describing the view and its keys (including "delete
`~/.lcars_dash/teams_token.bin` to sign out"), and a `GLOBAL_HELP` row `("⇧F11 / y", "Microsoft Teams chats
(read-only)")`. The HOME help entry lists Teams among clickable panes. The bottom status bar may add `y teams`.

### D. TEAMS tab — GUI (Tkinter)

**FR-026 — Sidebar pill and keys.** A "TEAMS\n[⇧F11 / Y]" pill directly under the GMAIL pill in the `gui.py` nav opens
`show_teams`; `<Shift-F11>` works from any view and `<Key-y>` follows the existing `on(...)` rule (letter keys act
from the status view only).

**FR-027 — Pane.** A `TeamsPane` with the same list + text layout, markers, states, keys (`j/k/g/G/l/h/r/Esc`) and
status line as FR-022 – FR-024, loading on a worker thread and updating widgets only on the Tk main thread
(`after`), consistent with `OutlookPane`/`GooglePane`.

**FR-028 — Help.** The GUI help table gains equivalent TEAMS and global entries.

### E. HOME pane (GUI and TUI)

**FR-029 — Compact Teams section.** HOME shows a compact "TEAMS CHAT" box with a header line
`Unread chats: N  //  Mentions: M` and the latest few chats (up to 5 lines, as space allows), formatted by a new
shared function in `home_ops.py` (e.g. `teams_lines(summary, width)` returning `(tag, text)` tuples with tags
`unread`, `mention`, `row`, `dim`, `err`), consistent with `mail_lines`.
*Acceptance:* unit test of `teams_lines` for loaded, empty and width-truncation cases.

**FR-030 — One-screen layout preserved.** The Teams box keeps HOME a single screen: it shares an existing row (e.g. a
third column in the inbox row) rather than adding a full-height row; all existing HOME boxes remain visible and
functional.
*Acceptance:* TUI pilot at 160×45 and GUI at default geometry: all HOME boxes including Teams are mounted with
non-zero size and the HOME view has no vertical scrollbar.

**FR-031 — Navigation.** Clicking the Teams box, or Tab/Shift+Tab to it and Enter, opens the TEAMS tab (TUI: add
`"hm-teams": "show_teams"` to `GO` in `tui_home.py` so it joins the Tab cycle and focus styling in `lcars.tcss`; GUI:
same `go("show_teams")` mechanism, focus ring and Tab cycle as other HOME panels).

**FR-032 — HOME degradation and refresh.** In not-configured / sign-in / error states the box shows a one- or two-line
summary (`Teams not configured - open TEAMS (y) for setup`, `Sign in: <url>  code <code>`, `Error: ...`) and never
blocks or breaks the rest of HOME. HOME's `r` reload and existing 5-minute refresh include Teams; the Teams load runs in
parallel with, and independently of, the Outlook/Gmail/usage loads.

### F. Packaging and tests

**FR-033 — Dependencies.** Add `msal`, `msal-extensions`, `requests` to `requirements.txt` and/or `pyproject.toml`
(neither exists today — see ASSUMPTION-006).

**FR-034 — Unit tests.** pytest tests under repo-root `tests/` for `teams_ops` and `home_ops.teams_lines` using mocked
Graph JSON and mocked MSAL. **No network access** (HTTP layer mocked; a real request attempt fails the test).
**`mindchuk_ops.add` is never called** (patched to raise in all UI smoke tests). Config/token paths redirected to temp
dirs. Coverage at minimum: FR-002, FR-003, FR-004, FR-007, FR-010, FR-013 – FR-019, FR-029.

**FR-035 — TUI smoke.** A headless Textual `run_test()` pilot test starts the app, opens TEAMS via `shift+f11`, via `y`
from the repo list and via the sidebar pill, returns HOME, Tab-cycles to the Teams box and presses Enter → TEAMS view
active. Runs with `teams_ops` mocked in not-configured and loaded states; no crash; no real network.

**FR-036 — GUI smoke.** A test constructs the Tk app (skipped if no display is available), calls `show_teams` and
`show_home`, processes pending events, and destroys it without error, with network-touching ops mocked.

**FR-037 — Regression.** Existing tabs, keys, HOME boxes and theme cycling behave as before.

## Non-Functional Requirements

**NFR-001 — Responsiveness.** No Teams network or auth call runs on the UI thread/event loop; UI input latency is
unaffected while Teams loads or sign-in is pending.

**NFR-002 — Performance.** On a typical connection `chats()` (≤ 50 chats) completes within 5 s and the HOME Teams
summary within 10 s; every HTTP request has a timeout ≤ 20 s.

**NFR-003 — Security / privacy.** Tokens are never logged, printed, or written unencrypted (FR-010). Only delegated
`Chat.Read`, `User.Read`, `offline_access`. Chat content is held in memory only — no on-disk storage of messages. No
secrets in source; `client_id`/`tenant_id` live only in the user's config file.

**NFR-004 — Read-only guarantee.** Verified by FR-018 tests.

**NFR-005 — Robustness.** Any Teams failure is contained to the TEAMS tab and the HOME Teams box; no unhandled
exception terminates the app.

**NFR-006 — Maintainability.** Follows existing patterns (data module without UI; shared formatting in `home_ops.py`;
views mirror the Outlook/Gmail views). New `.py` files use **CRLF** line endings; edited files keep CRLF.

**NFR-007 — Config isolation.** `~/.lcars_dash.json` is not modified by the feature or its tests; after all work it is
exactly `{"theme": "DEEP SPACE 9"}`. Teams settings live only in `~/.lcars_dash/teams_config.json`. Tests do not
create or modify real files in the user's home (temp paths / monkeypatch).

**NFR-008 — Theme compatibility.** New TUI/GUI elements use theme variables/palette so all five themes (TNG, DS9,
Klingon, Romulan, Vulcan) render correctly.

## Data Requirements

- Inputs: Graph JSON from `/me`, `/me/chats?$expand=lastMessagePreview` (+ members), `/me/chats/{id}/messages`.
- Outputs: in-memory dicts (FR-013, FR-014, FR-016); rendered `(tag, text)` lines.
- Storage: `~/.lcars_dash/teams_config.json` (user-created, read by the app only), `~/.lcars_dash/teams_token.bin`
  (DPAPI-encrypted MSAL cache). No other persistence; no retention of messages.
- Times: Graph UTC ISO-8601 timestamps converted to naive local `datetime`, matching other modules.
- Data owner: the user's Microsoft 365 tenant.

## Integration Requirements

- Microsoft Graph v1.0 (HTTPS) — delegated, read-only GETs.
- Microsoft identity platform (`login.microsoftonline.com/<tenant_id>`) — device code flow via `msal`.
- Windows DPAPI via `msal-extensions` for cache encryption.
- Internal: new `teams_ops.py`; changes to `home_ops.py`, `app.py`, `tui_panes.py`, `tui_home.py`, `lcars.tcss`,
  `gui.py`.
- Excluded: team/channel endpoints, calendar/meetings, presence, sending messages, Teams desktop automation.

## Environmental Requirements

- Windows workstation (DPAPI); the Python version already used by the project; local execution.
- Internet access to Microsoft Graph/login endpoints is needed for Teams features only; the rest of the dashboard works
  offline (Teams areas show an error state).
- Tenant must allow user (or admin) consent for `Chat.Read` and the public-client device code flow.

## Constraints

- C-1: Auth via MSAL delegated device code flow only; scopes `Chat.Read`, `User.Read`, `offline_access`.
- C-2: Read-only; no channel messages; no meetings/calendar.
- C-3: Fixed config path/format (FR-001) and token cache path (FR-009).
- C-4: Add `msal`, `msal-extensions`, `requests` dependencies (FR-033).
- C-5: Both GUI and TUI get the feature.
- C-6: `.py` files CRLF; `~/.lcars_dash.json` untouched.
- C-7: Tests use no network and never call `mindchuk_ops.add`.

## Risks

- R-1: Tenant policy may block consent to `Chat.Read` or the device code flow (Conditional Access) → feature unusable
  until an admin acts; mitigated by clear 403/sign-in messages.
- R-2: Graph throttling when scanning many chats for mentions → bounded scanning (FR-016) and Retry-After handling.
- R-3: `viewpoint` may be absent for some chats → the unread rule in Definitions may over-report.
- R-4: HOME auto-refresh during a pending sign-in could start duplicate flows → FR-007.
- R-5: HOME may become cramped at small window sizes → FR-030 acceptance at a fixed size.
- R-6: Some terminals intercept Shift+F11 → `y` and sidebar click remain available.
- R-7: msal / msal-extensions are not installed on the current machine; until installed the Teams areas show the
  FR-003 message.

## Assumptions

- ASSUMPTION-001: Teams tab keys are **Shift+F11** and **y** (F1–F12 and the obvious letters are already used; `y` is
  not a global key in GUI or TUI). Pill label `TEAMS [⇧F11 / Y]`.
- ASSUMPTION-002: "Recent chats" = up to 50 chats ordered by last message time (newest first); HOME shows up to 5.
- ASSUMPTION-003: "Mentions" = @mentions of the signed-in user only (tag/@channel/@everyone mentions not counted) in
  unread messages of unread chats, within the scan cap.
- ASSUMPTION-004: Refresh cadence follows existing patterns: on opening the tab if stale (> 60 s), on `r`, and with
  HOME's 5-minute refresh. No push/real-time updates.
- ASSUMPTION-005: Graph GETs do not change read state in Teams.
- ASSUMPTION-006: The repo has no `requirements.txt`/`pyproject.toml`; a minimal `requirements.txt` is created listing
  at least the three new packages.
- ASSUMPTION-007: No `tests/` folder exists; tests go in repo-root `tests/` and run with pytest.
- ASSUMPTION-008: The per-chat `@` marker in the TEAMS list uses the same mention computation as `summary()`.
- ASSUMPTION-009: Single Microsoft 365 account; the first cached account is used; no account switcher or sign-out UI
  (sign-out = delete `teams_token.bin`, documented in help).
- ASSUMPTION-010: Times are shown in local time using the formats of the Outlook/Gmail panes.

## Open Questions

None blocking. Decisions taken on the stakeholder's behalf (for later confirmation): ASSUMPTION-001 (keys),
ASSUMPTION-003 (mention definition), ASSUMPTION-006 (dependency file).

## Approval Status

**APPROVED** — 2026-11-10. Stakeholder absent; approved under delegated authority using the decisions supplied in the
request. Recorded assumptions remain subject to later stakeholder confirmation.
