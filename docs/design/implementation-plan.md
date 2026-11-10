# Implementation Plan — Microsoft Teams Chat (read-only) for LCARS Dashboard

Document root: `docs/` · Inputs: `docs/design/requirements.md` (APPROVED), `docs/design/spec.md` (APPROVED) ·
Date: 2026-11-10 · Author: Senior Project Manager

**Status: APPROVED** (2026-11-10, delegated authority; stakeholder absent)

## 1. Global rules (apply to every task)

- **G1 CRLF**: every new/edited `.py` file must be CRLF. Check after each task: no bare `\n`
  (e.g. `python -c "import sys;d=open(f,'rb').read();assert d.count(b'\n')==d.count(b'\r\n')"`).
  Edit tools that write LF must be followed by normalisation.
- **G2 Config untouched**: `~/.lcars_dash.json` must remain exactly `{"theme": "DEEP SPACE 9"}`. Tests redirect
  `config.CONFIG_FILE` to tmp; never run the real GUI/TUI theme-cycling against the real file without a tmp redirect.
  Verify at every pass end (task T-VERIFY-CFG).
- **G3 No home writes in tests**: paths monkeypatched to `tmp_path`; no network (socket guard); `mindchuk_ops.add/run`
  patched to raise.
- **G4 Read-only**: only `requests.get`; no `/teams/`, `/channels/`.
- **G5 Pattern fidelity**: mirror `outlook_ops`/`google_ops`, `OutlookView`/`OutlookPane`, `home_ops.mail_lines`.
- **G6 Theme**: colours only via theme roles (NFR-008). TUI table cells must be `rich.text.Text`.
- Each task is done only when its verification passes and G1 holds.

## 2. Dependency overview

```text
T01 packaging + test scaffolding ─┬─> T02 teams_ops core ──> T03 auth ──> T04 graph+parse ──> T05 summary
                                  │                                                              │
                                  └─> T06 home_ops (needs exception types from T02, shape from T04/T05)
T02..T06 ──> T07 TUI app wiring + TeamsView ──> T08 TUI HOME box + tcss ──> T09 TUI smoke
T02..T06 ──> T10 GUI TeamsPane + Dashboard wiring ──> T11 GUI HOME box ──> T12 GUI smoke
T09 + T12 ──> T13 regression/full suite/final verification ──> T14 hand-off (implementation-summary)
```

T07–T09 (TUI) and T10–T12 (GUI) are independent of each other once T06 is done and may run in parallel.

## 3. Milestones

| Milestone | Content | Exit condition |
|---|---|---|
| M1 Foundation | T01–T06 | `pytest` green for config/auth/graph/parse/home tests; msal absent import safe |
| M2 TUI complete | T07–T09 | TUI smoke green |
| M3 GUI complete | T10–T12 | GUI smoke green (or skipped w/o display, manually checked) |
| M4 Validation | T13–T14 | Full suite green, CRLF + config checks pass, ready for code/security review |

## 4. Tasks

Complexity: S/M/L. Owner = developer pass (Section 6).

### T01 — Packaging and test scaffolding (Pass D, then A)
- **Req**: FR-033, FR-034, NFR-007, C-7
- **Files**: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `tests/conftest.py`, `tests/teams_fakes.py`
- **Deps**: none · **Complexity**: M
- **Work**: create files verbatim from spec "Deployment"; `conftest.py` autouse fixtures (no-network sockets, path
  redirects incl. `config.CONFIG_FILE`, mindchuk guard, `teams_ops._reset()` — `_reset` is added in T02, fixture
  must tolerate its absence until then via `getattr`); `teams_fakes.py`: `FakeMsalModule/FakeApp` (records client_id,
  authority, scopes; device flow blockable by `threading.Event`), `FakeExtensions`, `FakeResponse`, Graph JSON
  builders (chats, messages, me).
- **Verify**: `python -m pytest --collect-only` works; `requirements.txt` lists msal, msal-extensions, requests.

### T02 — teams_ops: constants, exceptions, config, lazy imports (Pass A)
- **Req**: FR-001, FR-002, FR-003, FR-004, FR-012, NFR-003, NFR-006
- **Files**: `lcars_dash/teams_ops.py` (NEW), `tests/test_teams_config.py`
- **Deps**: T01 · **Complexity**: M
- **Work**: spec C1, C2, C3, exceptions + exact `NOT_CONFIGURED_MSG`, `_wrap`, `_reset`; stdlib-only top-level imports;
  GUID/tenant validation; config read at call time.
- **Verify**: tests for no file / bad JSON / non-object / missing / blank / bad GUID (exact prefix, "public client",
  "device code", "Chat.Read", zero HTTP); import succeeds with `sys.modules["msal"]=None`; module imports no UI libs.

### T03 — teams_ops: authentication and token cache (Pass A)
- **Req**: FR-004–FR-011, NFR-001, NFR-003
- **Files**: `lcars_dash/teams_ops.py`, `tests/test_teams_auth.py`
- **Deps**: T02 · **Complexity**: L (highest risk; do first among logic tasks)
- **Work**: `_Auth`, `_lock`/`_init_lock`, `_ensure_app`, `_token`, `_complete_flow`, `_flow_reason`, `auth_state`,
  `retry_sign_in`, `_make_cache` with in-memory fallback + notice; never plaintext persistence; app not cached on
  construction failure.
- **Verify**: scopes exact; code/URL available while completion blocked; 2 threads → 1 `initiate_device_flow`;
  success→`signed_in`; expiry→`failed` with "press r to retry"; `retry_sign_in` then new flow; msal_extensions absent →
  no `teams_token.bin` + notice; fake extensions → `build_encrypted_persistence(str(TOKEN_FILE))` used; silent token
  path avoids device flow.

### T04 — teams_ops: Graph layer, parsing, HTML stripping (Pass A)
- **Req**: FR-012–FR-015, FR-017–FR-019, NFR-002, NFR-003
- **Files**: `lcars_dash/teams_ops.py`, `tests/test_teams_graph.py`, `tests/test_teams_parse.py`
- **Deps**: T03 · **Complexity**: L
- **Work**: `_get` (GET only, URL guard, status table, Retry-After via `time.sleep`), `_pages`, `_me`, `_chat_path`,
  `chats` (+400 fallback), `_parse_chat`, `messages`, `_parse_message`, `_sender`, `_parse_utc`, `_local`, `html_to_text`.
- **Verify**: six chat scenarios + pagination + 400 fallback; six message scenarios ordered oldest→newest; HTML table
  (br/p/div, entities, `<at>`, img, attachment, emoji, ESC stripped, `&lt;b&gt;` literal, single-line); every recorded
  call is GET, no `/teams/`/`/channels/`, foreign nextLink rejected; 401→refresh, 401×2→SignInRequired, 403, 429
  (Retry-After 3 and 99→10), 429×2, timeout, invalid JSON; `/me` once.

### T05 — teams_ops: summary() (Pass A)
- **Req**: FR-016, FR-017, ASSUMPTION-003/008, NFR-002
- **Files**: `lcars_dash/teams_ops.py`, `tests/test_teams_parse.py`
- **Deps**: T04 · **Complexity**: M
- **Work**: summary with cache (`max_age`), `retry`, bounded parallel mention scan, `capped`, error propagation rules.
- **Verify**: 3 chats (2 unread, 2 me-mentions + 1 other) → `unread_chats==2`, `mentions==2`; capped cases (>15 unread,
  full window); SignInRequired from a scan re-raised; max_age cache hit; `cache_notice` surfaced.

### T06 — home_ops: Teams formatting helpers (Pass A)
- **Req**: FR-029, FR-024 (state text), FR-032, FR-022 (cells), NFR-008
- **Files**: `lcars_dash/home_ops.py`, `tests/test_home_teams_lines.py`
- **Deps**: T02 (exception types), T05 (summary shape) · **Complexity**: M
- **Work**: `teams_cells`, `teams_lines`, `teams_error_lines`, `teams_message_lines`, `teams_status`; import teams_ops;
  additions only (existing functions untouched).
- **Verify**: loaded / empty / width-truncation / header tag selection; each exception row of the mapping table
  (compact and full); day headers; continuation indentation; status line incl. cache notice.

### T07 — TUI: app wiring and TeamsView (Pass B)
- **Req**: FR-020–FR-025, FR-006 (TUI), NFR-001, NFR-005, NFR-008
- **Files**: `lcars_dash/app.py`, `lcars_dash/tui_panes.py`, `lcars_dash/lcars.tcss` (`#n-teams` only)
- **Deps**: T06 · **Complexity**: L
- **Work**: spec U1 table (HELP["teams"], HELP["home"] edits, GLOBAL_HELP, `y` and `shift+f11,f23` bindings, NavBlock,
  `TeamsView` in compose, statusbar `y teams`, `action_show_teams`, theme-cycle re-render) and U2 `TeamsView`
  (state machine, `Text` cells, debounce, stale-token discards, 2 s sign-in poll).
- **Verify**: app starts; manual/pilot: `shift+f11`, `y`, pill click open TEAMS in not-configured, sign-in pending
  (URL+code shown, other tabs usable) and loaded states; no existing binding changed (diff review).

### T08 — TUI: HOME Teams box (Pass B)
- **Req**: FR-029–FR-032, FR-025 (home help)
- **Files**: `lcars_dash/tui_home.py`, `lcars_dash/lcars.tcss`
- **Deps**: T07 · **Complexity**: M
- **Work**: spec U3 + U3b (GO last entry, `r`→`reload(True)`, FocusBox in `.hm-mail` row, `reload_teams`, `_auto`
  sign-in completion, `mention` style, `render_teams`, tcss focus/border rules).
- **Verify**: HOME at 160×45: all boxes non-zero size, `max_scroll_y == 0`; Teams failures do not affect other boxes.

### T09 — TUI smoke tests (Pass C)
- **Req**: FR-035, FR-030, FR-031, FR-037, FR-006
- **Files**: `tests/test_tui_teams_smoke.py`
- **Deps**: T08 · **Complexity**: M
- **Work**: `asyncio.run(...run_test(size=(160,45)))` flows from spec; `quiet_ops` fixture; not-configured and loaded
  summaries; pending sign-in tab switching; `f5` theme cycle; works with msal absent.
- **Verify**: green; no real network; `~/.lcars_dash.json` unchanged.

### T10 — GUI: TeamsPane and Dashboard wiring (Pass C)
- **Req**: FR-026–FR-028, FR-006 (GUI), NFR-001, NFR-008
- **Files**: `lcars_dash/gui.py`
- **Deps**: T06 · **Complexity**: L
- **Work**: spec U4 + U5 (pane, pill after GMAIL, pill height 58→54, panes dict, `<Shift-F11>`/`<Key-y>`, HELP and
  GLOBAL_HELP, `show_teams`, Treeview tag colours in `apply_theme`).
- **Verify**: Tk app starts without msal; `show_teams` renders not-configured/loaded/sign-in states; widgets updated
  only via `after`/`_pump`.

### T11 — GUI: HOME Teams box (Pass C)
- **Req**: FR-029–FR-032
- **Files**: `lcars_dash/gui.py`
- **Deps**: T10 · **Complexity**: M
- **Work**: spec U6 (6-column grid, new panel last in `order`, padx rule, `mention` tag, `reload(retry)`,
  `reload_teams`, `_auto`, `render_teams`, status label columnspan).
- **Verify**: default geometry: all HOME panels mapped, height > 10, existing boxes unchanged; Tab cycle reaches Teams;
  click opens TEAMS.

### T12 — GUI smoke tests (Pass C)
- **Req**: FR-036, FR-030, FR-031, FR-037
- **Files**: `tests/test_gui_teams_smoke.py`
- **Deps**: T11 · **Complexity**: S
- **Verify**: green or skipped on `TclError`; `show_teams`/`show_home` + destroy without error.

### T13 — Full regression and compliance sweep (Pass D)
- **Req**: FR-037, NFR-004, NFR-006, NFR-007, C-6, C-7
- **Files**: none (fixes only)
- **Deps**: T09, T12 · **Complexity**: S
- **Work**: `python -m pytest`; CRLF check across all new/edited `.py`; confirm `~/.lcars_dash.json` equals
  `{"theme": "DEEP SPACE 9"}` and `~/.lcars_dash/` has no new Teams files; grep teams_ops for non-GET verbs and UI
  imports; install `msal msal-extensions` only if the user wants live sign-in (manual step, not a test dependency).
- **Verify**: all green; checklist recorded in implementation summary.

### T14 — Hand-off (Pass D)
- **Files**: `docs/design/implementation-summary.md`
- **Deps**: T13 · **Complexity**: S
- **Work**: list files changed, deviations, manual verification steps (Entra setup, first sign-in, sign-out).

## 5. Requirements traceability

| Requirement | Tasks |
|---|---|
| FR-001, FR-002, FR-003 | T02 |
| FR-004 | T02, T03 |
| FR-005 – FR-011 | T03 |
| FR-006 (UI part) | T07, T10 |
| FR-012 | T02, T04 |
| FR-013, FR-014, FR-015 | T04 |
| FR-016 | T05 |
| FR-017, FR-018, FR-019 | T04 |
| FR-020, FR-021 | T07 |
| FR-022, FR-023, FR-024 | T06, T07 |
| FR-025 | T07, T08 |
| FR-026, FR-027, FR-028 | T10 |
| FR-029 | T06, T08, T11 |
| FR-030, FR-031, FR-032 | T08, T11 (verified T09, T12) |
| FR-033 | T01 |
| FR-034 | T01–T06 |
| FR-035 | T09 |
| FR-036 | T12 |
| FR-037 | T09, T12, T13 |
| NFR-001 | T03, T07, T10 |
| NFR-002 | T04, T05 |
| NFR-003 | T03, T04, T13 |
| NFR-004 | T04, T13 |
| NFR-005 | T07, T08, T10, T11 |
| NFR-006 | G1, T13 |
| NFR-007 | T01, T13 |
| NFR-008 | T07, T08, T10, T11 |

## 6. Developer passes

| Pass | Scope | Tasks | Parallel? |
|---|---|---|---|
| **D0 (deps)** | packaging + test scaffolding | T01 | first; tiny |
| **A (data + tests)** | `teams_ops.py`, `home_ops.py`, unit tests | T02 → T03 → T04 → T05 → T06 | sequential; start immediately after D0 |
| **B (TUI)** | `app.py`, `tui_panes.py`, `tui_home.py`, `lcars.tcss`, TUI smoke | T07 → T08 → T09 | parallel with C after A |
| **C (GUI)** | `gui.py`, GUI smoke | T10 → T11 → T12 | parallel with B after A |
| **D (final)** | sweep + hand-off | T13, T14 | after B and C |

Note: B and C touch disjoint files (only `lcars.tcss` is B's). T09 TUI smoke may be assigned to the TDD Engineer.
Early alternative for speed: Pass A may stub `home_ops` signatures so B/C start once T05 contracts are fixed; not
required.

## 7. Risks and mitigations

| Id | Risk | Mitigation / planned handling |
|---|---|---|
| PR-1 | Auth thread-safety bugs (duplicate flows, deadlock) | T03 first among logic tasks; locks never held across I/O; concurrent-thread test |
| PR-2 | msal/msal-extensions not installed on dev machine | Fakes injected via `sys.modules`; tests never need the real packages |
| PR-3 | LF line endings on new `.py` | G1 check in every task and T13 |
| PR-4 | Tests accidentally touching real `~/.lcars_dash.json` (theme save) | Autouse path redirect in T01; G2 check at T13 |
| PR-5 | GUI/TUI layout regression (6-column grid, sidebar height) | FR-030 assertions in T09/T12; pill height 54 |
| PR-6 | Textual DataTable markup injection from chat text | `Text` cells only (G6); test with `[bold]`-style content |
| PR-7 | Graph behaviour differs from assumptions (A1/A2) | 400 fallback + client-side sort; live check is manual post-install |
| PR-8 | Tk smoke impossible without display | Skip on `TclError`; manual run noted in summary |
| PR-9 | Shift+F11 intercepted by terminal | `f23` alias, `y`, pill click |

## 8. Quality, security, and acceptance planning

- **Testing before implementation**: T01 and the test files named in each task are authored alongside/before the code
  (TDD Engineer may write tests from the spec's required-cases list ahead of Pass A).
- **Unit**: T02–T06; **integration/smoke**: T09, T12; **acceptance**: spec Acceptance Criteria table run at T13;
  **manual validation** (post-install): Entra registration, device-code sign-in, token file not plaintext, sign-out by
  deleting `teams_token.bin`.
- **Security work items**: scopes (T03/T04), config validation (T02), URL guard + chat-id validation (T04), no
  plaintext token (T03), control-char stripping and `Text` cells (T04/T07), secrets handling and dependency review
  (T01, T13); Security Engineer review follows implementation.

## 9. Definition of done

All tasks T01–T14 verified; `python -m pytest` green offline; all new/edited `.py` CRLF; `~/.lcars_dash.json` ==
`{"theme": "DEEP SPACE 9"}`; every FR/NFR in the traceability table has passing evidence; hand-off summary written.

## Approval Status

**APPROVED** — 2026-11-10, Senior Project Manager, under delegated authority (stakeholder absent).
