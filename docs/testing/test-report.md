# Test Report

## Feature Overview

Read-only Microsoft Teams chat integration for the LCARS dashboard: `teams_ops.py`, `home_ops` Teams helpers, TUI `TeamsView` + HOME box, GUI `TeamsPane` + HOME box. Validated 2026-11-10 against `requirements.md`, `spec.md`, `implementation-summary.md` (Passes A, B, C).

## Requirements Reviewed

FR-001 – FR-037, NFR-001 – NFR-008.

## Acceptance Criteria Verified

| Area | Requirements | Evidence | Result |
|---|---|---|---|
| Config / not configured / missing libs | FR-001–003 | test_teams_config, test_teams_auth, test_import_safe_and_missing_msal, subprocess import with msal blocked | PASS |
| Scopes, device flow, single flow, outcome | FR-004–008, FR-011 | test_teams_auth (scopes, concurrency, expiry, retry) | PASS |
| Token cache / fallback | FR-009–010 | test_teams_auth (memory fallback writes no file; persistence used when available) | PASS (real DPAPI untested, see notes) |
| Data API, parsing, HTML, summary | FR-012–017 | test_teams_graph, test_teams_parse | PASS |
| Read-only, error handling | FR-018–019, NFR-004 | GET-only source test, single `requests.get`, foreign nextLink rejection, 401/403/429/network tests | PASS |
| TUI | FR-020–025 | test_tui_teams_smoke (headless pilot) | PASS |
| GUI | FR-026–028 | test_gui_teams_smoke (real Tk) | PASS |
| HOME | FR-029–032 | test_home_teams_lines, both smoke files | PASS |
| Deps / tests | FR-033–036 | requirements.txt has msal, msal-extensions, requests (new test) | PASS |
| Regression | FR-037 | Full suite; Gmail F11 unchanged; theme cycle | PASS |
| Config isolation | NFR-007 | `~/.lcars_dash.json` == `{"theme": "DEEP SPACE 9"}` (new test + manual) | PASS |
| Non-blocking, robustness, theme | NFR-001, 005, 008 | smoke tests (sign-in pending keeps other tabs usable; failures contained) | PASS |
| Live Graph/Entra, NFR-002 timing | FR-009, NFR-002 | Not testable offline | NOT VERIFIED (manual post-install step) |

## Test Categories Executed

- Unit, Integration (faked Graph/MSAL), Workflow (TUI pilot and Tk smoke), Negative, Boundary (limits, paging caps, empty/None, invalid chat ids), Regression, Convention/static checks.

## Results

Passed:

- Full pytest run 5 times (3 before, 2 after adding tests): 148/148, then 186/186 each run. No flakiness observed in the Tk or Textual tests.
- CRLF check on all 29 `.py` files: all CRLF except one bare-LF line (BUG-001).
- `~/.lcars_dash.json` = `{"theme": "DEEP SPACE 9"}`.
- No network: the conftest socket guard blocks everything except loopback; `teams_ops` has exactly one HTTP call site (`requests.get`) and no post/put/patch/delete.
- No `mindchuk_ops.add` use by Teams code (`teams_ops`, `home_ops`, TeamsView/TeamsPane). The pre-existing Mindchuk actions are unchanged. conftest also makes `add/run` raise during tests.
- Headless launch, run against the real `Dashboard` / `LcarsDash` with a temp HOME: GUI created, `show_teams` called, mainloop ran 2.5 s and exited, printed `GUI_OK`. TUI `run_test` at 160x45 with `shift+f11` printed `TUI_OK`. Both ran without exceptions with Teams not configured.

Failed:

- None.

New tests added (tests/ only): `tests/test_validation_gaps.py` (38 tests). It covers per-file CRLF, user theme config, no mindchuk/write verbs, dependencies listed, scope whitelist, and import without msal in a subprocess.

## Defects Identified

BUG-001

Severity: Low

Status: Open

Requirement: Conventions (CRLF on all `.py`)

Title: `lcars_dash/app.py` line 328 has a bare LF ending.

Steps To Reproduce: read the bytes of `app.py` and find an `\n` not preceded by `\r` (line 328).

Expected Result: all lines CRLF.

Actual Result: one LF-only line. The implementation summary says it pre-dates Pass B.

Impact: cosmetic and conventions only. The test tolerates it for `app.py` only.

Recommended Fix: normalize line 328 to CRLF and drop the allowance in `tests/test_validation_gaps.py`.

BUG-002

Severity: Low

Status: Open (observation)

Requirement: FR-021 / FR-023 (TUI keys)

Title: the TUI `y` key works only on StatusView, as specified, so it is not a global shortcut. Terminal Shift+F11 reporting varies, with `f23`, the pill and Tab+Enter as fallbacks. This matches the spec; flagged for user awareness only.

## Approval Checklist

[X] Requirements Tested
[X] Acceptence Criteria Tested (live-tenant items excluded, manual)
[X] Regression Testing Complete
[X] Error Handling Verified
[X] Logging Verified (errors surface as TeamsError messages and UI status lines; tokens are never exposed)

## Re-validation after security fixes and code review edits (2026-11-10)

- Full pytest, 3 consecutive runs: 244 passed each (about 14 s). No flakes.
- CRLF check on all .py under lcars_dash/ and tests/: no bare-LF lines.
- ~/.lcars_dash.json is {"theme": "DEEP SPACE 9"}, before and after the launch checks.
- Headless GUI (Tk Dashboard: create, update, mainloop 1.5 s, destroy): OK.
- Headless TUI (Textual run_test, 1 s): OK.
- No production code modified; no commit.

## Final Status

APPROVED WITH NOTES (re-validated; no regressions)

Notes: live Graph/Entra sign-in, real DPAPI persistence (msal-extensions) and NFR-002 timing need manual verification after install. Two Low items (BUG-001, BUG-002). Forward to Code Reviewer.
