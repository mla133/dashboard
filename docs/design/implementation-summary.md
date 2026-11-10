# Implementation Summary

## Pass D0 + Pass A (T01–T06) — Teams data layer, formatting helpers, unit tests

Task ID:

T01, T02, T03, T04, T05, T06 (Passes D0 and A)

Requirements Implemented:

FR-001, FR-002, FR-003, FR-004, FR-005, FR-007, FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, FR-015,
FR-016, FR-017, FR-018, FR-019, FR-033, FR-034 (unit part), FR-029 / FR-022 / FR-024 helper text (formatting only),
NFR-002, NFR-003, NFR-006, NFR-007. UI parts (FR-006 UI, FR-020–028, FR-030–032, FR-035/036) belong to Passes B/C.

Files Created:

- `requirements.txt`, `requirements-dev.txt`, `pytest.ini`
- `lcars_dash/teams_ops.py`
- `tests/__init__.py`, `tests/conftest.py`, `tests/teams_fakes.py`
- `tests/test_teams_config.py`, `tests/test_teams_auth.py`, `tests/test_teams_graph.py`, `tests/test_teams_parse.py`,
  `tests/test_home_teams_lines.py`

Files Modified:

- `lcars_dash/home_ops.py` (additions only: `import teams_ops`, `_clip`, `teams_cells`, `teams_lines`,
  `teams_error_lines`, `teams_message_lines`, `teams_status`; docstring updated). `app.py`, `tui_*.py`, `gui.py`,
  `lcars.tcss` untouched.

Key Decisions:

- Implemented exactly per spec C1–C10. Locks never held across I/O; one device flow per process (`_init_lock`).
- `tests/__init__.py` added so `conftest.py`/tests can `from . import teams_fakes`.
- `conftest.py` autouse: socket guard, path redirects (`teams_ops.*`, `config.CONFIG_FILE`, `tests_ops.RESULTS_FILE`,
  `google_ops.*`), `mindchuk_ops.add/run` raise, `teams_ops._reset()`, and `teams_ops.time` replaced so no real sleeping
  (recorded in the `sleeps` fixture). Fixtures `fake_msal` (also blocks real `msal_extensions` by default),
  `fake_extensions`, `write_config`, `graph` (routes `requests.get`; other verbs raise), `signed_in`.
- Header and sign-in lines use a spacing-preserving `_clip` rather than `short()` (which collapses the double spaces
  the spec text requires). Chat rows use `short()` as in `mail_lines`, so runs of spaces/leading marker spaces collapse
  in HOME rows (same behaviour as the existing mail box).
- A scan window with zero messages is never flagged `mentions_capped`.

Assumptions:

- A naive timestamp from Graph is treated as UTC (spec text truncated at that point).
- `expires_at` missing from a pending flow is treated as already expired (MSAL always supplies it).

Known Limitations:

- No live Graph/Entra verification (manual post-install step). Real `msal`/`msal-extensions` were installed
  but tests use fakes only.
- Real `msal-extensions` DPAPI behaviour (ASSUMPTION-A3) is untested here.

Dependencies Added:

`msal>=1.28`, `msal-extensions>=1.1` (requirements.txt); `pytest>=8.0` (requirements-dev.txt).
Installed locally: msal 1.39.0, msal-extensions 1.3.1 (PyJWT 2.15.1 transitively).

Validation Notes:

- `python -m pytest`: see result in hand-off message (all Pass A tests green, offline).
- All new/edited `.py` files verified CRLF (no bare LF).
- `~/.lcars_dash.json` still `{"theme": "DEEP SPACE 9"}`; tests redirect all paths to `tmp_path`.

Handoff Status:

READY FOR TDD VALIDATION (Pass A); Passes B and C may proceed against the `teams_ops` / `home_ops` contracts.

## Pass C (T10–T12) — GUI TeamsPane, Dashboard wiring, HOME Teams box, GUI smoke tests

Task ID:

T10, T11, T12 (Pass C)

Requirements Implemented:

FR-006 (GUI), FR-026, FR-027, FR-028, FR-029, FR-030, FR-031, FR-032 (GUI), FR-036, NFR-001, NFR-005, NFR-008 (GUI).

Files Created:

- `tests/test_gui_teams_smoke.py` (8 tests; skips if Tk cannot start)

Files Modified:

- `lcars_dash/gui.py` only: `teams_ops` import; new `TeamsPane` (after `GooglePane`); `Dashboard`: TEAMS nav pill
  (nav pill height 58→54), `self.teams` + `panes["teams"]`, `<Shift-F11>` (allowed from any view) and `y` keys,
  `HELP["teams"]`, updated `HELP["home"]`, `GLOBAL_HELP` (`⇧F11 / y`), `show_teams`, Treeview `unread`/`mention`
  tag recolour in `apply_theme`; `HomePane`: 6-column grid, Teams box (last in Tab order, click/Tab/Enter open TEAMS),
  `mention` tag, `reload(retry)`, `reload_teams`, sign-in completion check in `_auto`, `render_teams`.
  `app.py`, `tui_*.py`, `lcars.tcss` untouched.

Key Decisions:

- Followed spec U4–U6. `TeamsPane` pill `READ [L]` / `RELOAD [R]` use lambdas so they can be created before `self.view`.
- Tests use ONE module-scoped `Dashboard` (a second Tk root in the same process intermittently fails with
  `invalid command name "tcl_findLibrary"` on this machine); the faked `teams_ops.summary` answer is switched per test.
  Tests redirect `config.CONFIG_FILE`, fake `live_ops/copilot_ops/outlook_ops/google_ops/home_ops.week_events`,
  and stub `Dashboard.load_all`; `mindchuk_ops.add` stays guarded by conftest.
- The Tk 8.6 Treeview `tag_configure(font=...)` is used for bold unread/mention rows.
- Normalised two pre-existing bare-LF lines in `gui.py` (MonitorPane.render) to CRLF while enforcing G1.

Assumptions:

- `<Shift-F11>` delivered by Tk on Windows as `<Shift-F11>`; verified with `event_generate` in the smoke test
  (GMAIL `<F11>` still opens Gmail).

Known Limitations:

- Not run against live Graph/Entra; message pane and sign-in flow verified with fakes only.
- Visual layout (HOME at default geometry) asserted by mapped/height>10 checks, not screenshots.

Dependencies Added:

None.

Validation Notes:

- `python -m pytest`: 148 passed (full suite, offline).
- `gui.py` and `tests/test_gui_teams_smoke.py` verified CRLF (no bare LF).
- `~/.lcars_dash.json` still `{"theme": "DEEP SPACE 9"}`.

Handoff Status:

READY FOR TDD VALIDATION (Pass C)

## Pass B (T07–T09) — TUI: TeamsView, HOME Teams box, smoke tests

Task ID:

T07, T08, T09 (Pass B)

Requirements Implemented:

FR-006 (TUI), FR-020–FR-025, FR-029–FR-032 (TUI), FR-035, FR-037 (TUI), NFR-001, NFR-005, NFR-008.

Files Created:

- `tests/test_tui_teams_smoke.py` (6 headless Textual pilot tests, 160x45, all data sources faked)

Files Modified:

- `lcars_dash/app.py`: import, `HELP["teams"]`, HELP["home"] text, GLOBAL_HELP entry, `y` binding (StatusView),
  `shift+f11,f23` binding, `n-teams` NavBlock, `TeamsView` in compose, statusbar `y teams`, `action_show_teams`,
  theme-cycle re-render.
- `lcars_dash/tui_panes.py`: `TeamsView(ListTextView)` after `GoogleView` (state machine idle/loading/signin/error/loaded,
  `Text` cells, 0.3 s message debounce, stale-token discard, 2 s sign-in poll); imports `time`, `home_ops`, `teams_ops`.
- `lcars_dash/tui_home.py`: `hm-teams` FocusBox (last in `GO`), `r` -> `reload(True)`, `reload_teams`, `_auto`
  sign-in completion, `mention` style, `render_teams`.
- `lcars_dash/lcars.tcss`: `#n-teams`, `#hm-teams` border and focus rule.
- `tests/conftest.py`: network guard now permits loopback (`127.0.0.1`/`::1`) connects only, because the Windows asyncio
  event loop creates a loopback socketpair; all other connects still raise.

Key Decisions:

- Implemented per spec U1–U3b. `gui.py` untouched.
- The `y` binding lives only on StatusView (per spec); from HOME/other views use `shift+f11`/`f23`, the pill, or Tab+Enter.
  Smoke tests therefore use `shift+f11` except for the explicit `y`-from-status case.

Assumptions:

- `Chat["members"]` is a list of display-name strings (as produced by `teams_ops._parse_chat`).

Known Limitations:

- Not verified against a live Graph tenant. Terminal Shift+F11 reporting varies (`f23` alias, `y`, pill click are fallbacks).
- `app.py` contains one pre-existing bare-LF line ending (present before Pass B); all Pass B edits are CRLF.

Dependencies Added:

None.

Validation Notes:

- `python -m pytest tests/test_tui_teams_smoke.py`: 6 passed. Full run: 145 passed, 2 skipped; the single failure
  (`tests/test_gui_teams_smoke.py::test_home_tab_cycle_reaches_teams_and_click_opens_tab`) belongs to the in-progress Pass C.
- CRLF verified on all Pass B files; `~/.lcars_dash.json` still `{"theme": "DEEP SPACE 9"}`; no network; `mindchuk_ops.add` never called.

Handoff Status:

READY FOR TDD VALIDATION (Pass B)

## Security fixes

Response to `docs/reviews/security-review.md`. Full suite: 244 passed (new: `tests/test_security_fixes.py`).

- **SEC-001 (High):** new `teams_ops.clean_text()` drops Unicode categories Cc, Cf, Zl and Zp (ESC, C1, bidi, zero-width). Single-line mode also turns newlines and tabs into spaces. It is applied at parse time to topic and title, member and sender names, `me.name`, `web_url`, Graph and MSAL error text (`_error_message`, `_flow_reason`), device-flow fields (`auth_state`, `TeamsSignInRequired`) and message bodies. `TeamsError.__init__` sanitises every message.
- **SEC-002 (Medium):** `html_to_text` input is capped (32 KB, or 4 KB for single-line previews). The backtracking regexes were replaced by one linear pass over bounded tags (`<[^<>]{0,2048}>`) in `_strip_tags`. Timing test: under 0.2 s for 9 hostile payloads, both modes. Behaviour note: an unclosed `<script>`, `<style>` or `<attachment>` now drops the rest of the body.
- **SEC-003:** `requirements.txt` now has `requests>=2.32.4` and `msal-extensions>=1.3`.
- **SEC-004:** `TeamsView.say` renders the status as `rich.text.Text`, so `[` is never parsed as markup.
- **SEC-005:** `_check_graph_url` uses `urlsplit` and requires https, host `graph.microsoft.com` (no userinfo, port 443 only), no `.`/`..` segments, no `%2e`/`%2f`/`%5c`/backslash. Checks are case-insensitive and path-prefix allow-listed (`/v1.0/me`, `/v1.0/me/chats`). `_CHAT_ID` rejects dot-only ids and any `..`.
- **SEC-006:** not changed in code. The TEAMS help text (TUI and GUI) now says to quit the app, then delete `teams_token.bin`. An in-app sign-out is deferred.
- Known limits: ZWJ (U+200D) is removed, so compound emoji split into parts. The remaining process finding (the code-review artifact) is for the Orchestrator.
- `~/.lcars_dash.json` untouched. No commit. All edited `.py` files verified with no bare LF (CRLF).
