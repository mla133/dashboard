# Security Review Report

Feature: read-only Microsoft Teams chats (`lcars_dash/teams_ops.py`, `home_ops` Teams helpers, TUI `TeamsView` + HOME
box, GUI `TeamsPane` + HOME box).
Reviewer: Security Engineer. Date: 2026-11-10 (re-review after the security fixes).
Evidence: source review of `teams_ops.py` (`clean_text`, `TeamsError`, `_error_message`, `_flow_reason`, `auth_state`,
`_check_graph_url`, `_get`, `_CHAT_ID`, `_strip_tags`, `html_to_text`, `_parse_chat`, `_parse_message`, `_sender`, `_me`),
`tui_panes.TeamsView.say`, help text in `app.py` / `gui.py`, `requirements.txt`, `tests/test_security_fixes.py`;
dynamic hostile-input probes (below); full suite run: **244 passed**.
Required inputs: requirements, spec, implementation plan, implementation summary, test report and
`docs/reviews/code-review.md` (APPROVED WITH NOTES) are all present.

## Security Summary

All findings from the first review are resolved or accepted:

| ID | Severity | Status |
|---|---|---|
| SEC-001 terminal escape injection via chat metadata | High | **Fixed and verified** |
| SEC-002 regex CPU denial of service in `html_to_text` | Medium | **Fixed and verified** |
| SEC-003 dependency floors | Low | **Fixed** (`requests>=2.32.4`, `msal-extensions>=1.3`) |
| SEC-004 status line parsed as markup | Low | **Fixed** (`TeamsView.say` renders `rich.text.Text`) |
| SEC-005 weak Graph URL guard / dot chat ids | Low | **Fixed and verified** |
| SEC-007 `/v1.0/me` allow-list too broad | Low | **Resolved** (exact `/v1.0/me` or `/v1.0/me/chats[/...]`; tested) |
| SEC-006 no in-app sign-out | Low | **Accepted / deferred**; help text corrected |
| Process: missing code review | — | **Resolved** (`code-review.md` exists, APPROVED WITH NOTES) |

The core design is unchanged and sound: MSAL device code flow on a public client (no secret), delegated `Chat.Read` +
`User.Read` only, DPAPI-encrypted token cache with an in-memory fallback (never plain text), one GET-only HTTP function,
bounded retries/paging/timeouts, no token in logs or errors.

**Final status: APPROVED** (SEC-007 resolved; only SEC-006 deferred).

## Verification of fixes

### SEC-001 (High) — fixed

`clean_text()` drops every character of Unicode category Cc, Cf, Zl, Zp (C0, DEL, C1 incl. CSI `\x9b`/NEL `\x85`, bidi
overrides/isolates, zero-width, BOM, line/paragraph separators); single-line mode also folds `\n`/`\t`. It is applied at
parse time to topic/title, member names, preview sender, message sender, `me.name`, `web_url`, Graph error text,
MSAL `error_description`, device-flow fields and `cache_notice` (`auth_state`), and inside `html_to_text` *after*
`html.unescape` (so `&#x1b;`, `&#27;`, `&#155;`, `&#x202e;` are also removed). `TeamsError.__init__` sanitises every
string argument, which also covers `requests` exception text.

Probe with payload `Lunch\x1b]52;c;<b64>\x1b\\ \x9b31m \u202eevil` (OSC 52 ended with ST, CSI, RLO), plus entity-encoded
variants and U+2028/2029/FEFF: no Cc/Cf/Zl/Zp character survived in any of `clean_text` (both modes), `html_to_text`
(both modes), `_parse_chat` (`title`, `members`, `sender`, `preview`, `web_url`), `_parse_message` (`sender`, `text`),
`TeamsError`, `_error_message`, `_flow_reason`. Covered by tests `test_clean_text_*`, `test_parse_chat_and_message_sanitised`,
`test_graph_error_and_me_name_sanitised`, `test_flow_reason_and_signin_fields_sanitised`.

### SEC-002 (Medium) — fixed

Input capped (32 KB body, 4 KB single-line preview). Backtracking regexes replaced by one `finditer` pass over bounded tags
`<[^<>]{0,2048}>`; the `alt` lookup runs only inside a single bounded tag. Measured worst cases (13 hostile payloads × 2
modes, including the original `'<emoji alt="' * 3000` that took 17.1 s): **max 6.3 ms**, all others ≤ 6 ms. Covered by
`test_html_to_text_is_fast_on_hostile_input` and `test_html_to_text_caps_input_length`. Accepted functional side effect:
an unclosed `<script>/<style>/<attachment>` drops the rest of the body (fail-safe).

### SEC-003 (Low) — fixed

`requirements.txt`: `msal>=1.28`, `msal-extensions>=1.3`, `requests>=2.32.4`. Installed: msal 1.39.0, msal-extensions 1.3.1,
requests 2.34.2, urllib3 2.7.0. `pip-audit`/lock file in CI remains a recommendation.

### SEC-004 (Low) — fixed

`TeamsView.say()` calls `Static.update(Text(str(msg)))`; covered by `test_teams_status_line_is_not_parsed_as_markup`.

### SEC-005 (Low) — fixed

`_check_graph_url` (called by `_get` for both paths and nextLinks) uses `urlsplit`; requires `https`, host
`graph.microsoft.com`, port 443/none, no userinfo; rejects `%2e`, `%2f`, `%5c`, backslash, `.`/`..` segments (after
unquote); lower-cases before the `/teams`/`/channels` deny check; allow-lists `/v1.0/me` and `/v1.0/me/chats`.
`_CHAT_ID` rejects `.`, `..`, `...`, `a..b`, `/`, `%`.

Probe results: rejected — `Teams/x/Channels`, `me/chats/../messages`, `%2e%2e`, backslash, `;/../../users`,
`graph.microsoft.com.evil.com`, userinfo, port 8443, `http://`, `/v1.0//me`, `/v1.0/users/x`. Allowed — normal chat paths;
`%252e%252e` (single-decoded by Graph to a literal id, harmless); fragments (never sent). See SEC-007 for the residual.

### SEC-006 (Low) — accepted, deferred

No in-app sign-out yet. TUI and GUI help text now read "Quit the app, then delete ~/.lcars_dash/teams_token.bin (a running
app keeps its session until it exits)". Residual risk is limited to the lifetime of the process. Track for a later release.

## Attack Surface

| Exposure | Direction | Trust | Notes |
|---|---|---|---|
| `~/.lcars_dash/teams_config.json` | read | local user | `client_id` GUID; `tenant_id` `^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$` |
| `~/.lcars_dash/teams_token.bin` | read/write | local user | DPAPI via msal-extensions; in-memory fallback |
| `https://login.microsoftonline.com/<tenant>` | outbound TLS | Microsoft | MSAL device flow and refresh |
| `https://graph.microsoft.com/v1.0/me[/chats…]` | outbound TLS, GET | Microsoft | URL-guarded (`_check_graph_url`) |
| Chat content (topic, names, bodies, previews) | inbound | **untrusted** | sanitised at parse time (`clean_text`), length-capped, rendered as `Text` (TUI) / Tk text |
| Device-flow message / URI / code | inbound | Microsoft (TLS) | sanitised |
| Background threads | local | n/a | device-flow thread; 4-worker mention scan |

No listening sockets, no write verbs, `web_url` never opened.

## Authentication Review

Unchanged and acceptable: public client, device code flow, no secret, least-privilege scopes, single flow at a time
(`_init_lock`), bounded 401 handling (force refresh once, then re-sign-in, hard stop). Sign-out is manual (SEC-006).

## Authorization Review

Delegated permissions only; Graph enforces chat membership. `_get` is the only HTTP function and uses `requests.get`;
tests fail on any other verb. URL guard is now a real path allow-list (SEC-005), backed by token scope.

## Input Validation Review

| Input | Validation | Assessment |
|---|---|---|
| Config JSON | type checks, GUID/tenant regex | Good |
| Graph URL / nextLink | `_check_graph_url` (scheme, host, port, userinfo, encoded chars, dot segments, allow-list) | Good (SEC-007 note) |
| Chat id | `_CHAT_ID` (no dot-only ids, no `..`) + `quote` | Good |
| Message body HTML | 32 KB / 4 KB cap, linear tag pass, unescape, then `clean_text` | Good |
| Topic, names, sender, `me`, `web_url`, error and MSAL text | `clean_text` at parse/construction time | Good |
| Graph JSON | `isinstance` guards; non-dict rejected | Good |
| Rich markup | Teams list/text/status use `Text` objects | Good |
| Tk GUI | Tk does not interpret markup or ANSI | Safe |

## Secrets Management Review

No change from the first review: no secrets in source or docs; token only in the `Authorization` header; DPAPI cache with
in-memory fallback (no plain-text write); `log.debug` records path and status only, no handler configured; tests redirect
all files to `tmp_path`, fake `msal_extensions` and block non-loopback sockets. `shot.png` (repo root, unrelated to Teams)
shows internal repository names and an employee name — do not publish (informational).

## Dependency Review

| Package | Floor | Installed | Notes |
|---|---|---|---|
| msal | >=1.28 | 1.39.0 | Microsoft-maintained, no known advisories for this usage |
| msal-extensions | >=1.3 | 1.3.1 | No `portalocker` dependency |
| requests | >=2.32.4 | 2.34.2 | Floor now excludes CVE-2024-35195 and CVE-2024-47081 |
| urllib3 (transitive) | none | 2.7.0 | Current; optional `urllib3>=2.5` floor or `pip-audit` in CI recommended |

## Threat Model

| STRIDE | Threat | Status |
|---|---|---|
| Spoofing | Bidi/control characters in names or topics | Mitigated (SEC-001) |
| Tampering | Terminal escape / OSC 52 clipboard injection via chat data | Mitigated (SEC-001) |
| Tampering | Forged nextLink sends token elsewhere | Mitigated (host/scheme/port/userinfo guard; requests strips auth on host change) |
| Repudiation | Read-only client | N/A (Graph/Entra logs authoritative) |
| Information disclosure | Token in logs, errors or files | Mitigated |
| Information disclosure | Chat contents on screen / in memory | Accepted (user's own data) |
| Denial of service | Crafted HTML freezes UI | Mitigated (SEC-002: caps + linear parser, ≤ 6.3 ms worst case) |
| Denial of service | Throttling, paging, hangs | Mitigated (timeouts, page caps, capped Retry-After) |
| Elevation of privilege | Team/channel endpoints, write verbs | Mitigated (scope + GET-only + allow-list) |

## Findings

### SEC-001 — High — Validation — **RESOLVED**
Terminal control-sequence injection via chat metadata. Fixed by `clean_text` at parse time and in `TeamsError`; verified
by probes and tests (see Verification).

### SEC-002 — Medium — Validation (DoS) — **RESOLVED**
Regex backtracking in `html_to_text`. Fixed by input caps and a linear bounded-tag pass; verified (max 6.3 ms).

### SEC-003 — Low — Dependency — **RESOLVED**
Floors raised in `requirements.txt`.

### SEC-004 — Low — Validation — **RESOLVED**
Teams status line rendered as `Text`.

### SEC-005 — Low — Authorization (defense in depth) — **RESOLVED**
`_check_graph_url` and `_CHAT_ID` hardened; verified.

### SEC-006 — Low — Authentication (hardening) — **ACCEPTED / DEFERRED**
Finding ID: SEC-006. No in-app sign-out; help text now accurate. Recommendation unchanged: add a sign-out action
(`_forget_accounts()`, clear `_last` and view caches, delete the token file) in a later release.
Affected Components: `teams_ops`, help text in `app.py` and `gui.py`.

### SEC-007 — Low — Authorization (defense in depth) — RESOLVED

**Resolved 2026-11-10.** `_check_graph_url` now allows exactly `/v1.0/me` or `/v1.0/me/chats` and paths below it
(`ALLOWED_EXACT`, `ALLOWED_PREFIX` in `teams_ops.py`). `/v1.0/me/joinedTeams`, `/v1.0/me/mailFolders` and
`/v1.0/me/chatsx` are rejected in `tests/test_security_fixes.py`. Original finding follows.

Finding ID: SEC-007
Severity: Low
Category: Authorization

Description:
The allow-list prefix `/v1.0/me` accepts every path below `/me`, not just `/me` and `/me/chats/...`. Probes:
`/v1.0/me/joinedTeams` and `/v1.0/me/mailFolders` pass `_check_graph_url` (`/joinedteams` does not contain `/teams`).

Attack Scenario:
Would require a malicious nextLink from Graph itself (host is fixed) or a future code change. With the current scopes
(`Chat.Read`, `User.Read`) Graph returns 403 for these endpoints.

Impact:
Negligible today; matters only if scopes are widened.

Recommendation:
Make `/v1.0/me` an exact match and keep `/v1.0/me/chats` as the only prefix (`path == "/v1.0/me" or path == "/v1.0/me/chats"
or path.startswith("/v1.0/me/chats/")`); add `/v1.0/me/joinedTeams` and `/v1.0/me/mailFolders` to the rejection test.

Affected Components:
`teams_ops.ALLOWED_PREFIXES`, `teams_ops._check_graph_url`, `tests/test_security_fixes.py`.

## Approval Checklist

[X] Authentication Reviewed
[X] Authorization Reviewed
[X] Validation Reviewed
[X] Secrets Reviewed
[X] Dependencies Reviewed
[X] Logging Reviewed (no handlers; debug logs path and status only; no token)
[X] Error Handling Reviewed (error text sanitised and cut to 200 characters; no token or stack-trace leaks)
[X] Attack Surface Documented
[X] Threat Model Reviewed
[X] No Critical Findings
[X] No High Findings
[X] Required inputs complete (`code-review.md` present, APPROVED WITH NOTES)

## Final Status

**APPROVED** (Low notes only — APPROVED WITH NOTES in the agent workflow)

Next step: forward to the Technical Writer.

Follow-ups for a later release (non-blocking): SEC-006 in-app sign-out;
optional `pip-audit`/lock file in CI. Do not publish `shot.png`.
