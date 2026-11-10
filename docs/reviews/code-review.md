# Code Review Report

Feature: read-only Microsoft Teams chat (TEAMS tab + HOME box, TUI and GUI) · Date: 2026-11-10 · Reviewer: Code Reviewer
Inputs: `docs/design/requirements.md`, `spec.md`, `implementation-plan.md`, `implementation-summary.md`,
`docs/testing/test-report.md` (APPROVED WITH NOTES).

## Review Summary

Reviewed `lcars_dash/teams_ops.py`, the Teams additions to `home_ops.py`, `TeamsView` (`tui_panes.py`), the HOME box
(`tui_home.py`), wiring in `app.py`, `TeamsPane` / `HomePane` / `Dashboard` (`gui.py`), `lcars.tcss`, and `tests/`.

The implementation follows the spec closely and fits the existing patterns. It is readable, the threading rules
are respected, error paths are explicit and the tests are thorough (186 tests, all offline). There are no Critical,
High or Medium findings. Four Low cosmetic issues were fixed during the review (CR-006). Five Low notes remain, and
none of them blocks release.

`python -m pytest` after the fixes: **186 passed** (13.6 s).

## Requirements Compliance

- FR-001 to FR-037 and NFR-001 to NFR-008 trace to code elements as listed in the spec's Requirements Mapping. Spot checks:
  - Exact scopes (FR-004).
  - Single device flow under `_init_lock` (FR-007).
  - DPAPI cache or in-memory fallback with a notice (FR-009 and FR-010).
  - GET only, through the single `_get` (FR-018).
  - The status table in `_get` (FR-019).
  - HOME box and Tab order last (FR-030 and FR-031).
  - `shift+f11` / `f23` / `y` keys and the nav pill (FR-020, FR-021, FR-026 and FR-027).
- No scope creep: no write verbs, no channel/team endpoints, no Mindchuk use in Teams paths. The only extra items are
  a `TypedDict` for `Chat` / `Message` (the spec asks for it) and `MIN_UTC` (the spec names it).

## Architecture Compliance

- `teams_ops` has no UI imports and imports only the standard library at the top level. It uses lazy
  `msal` / `msal_extensions` / `requests` imports and the `_wrap` pattern, like `google_ops` and `outlook_ops`.
- Formatting lives only in `home_ops`. Both UIs consume the same `(tag, text)` lines, so TUI and GUI behave the same.
- The UI-to-`teams_ops` contract is honoured:
  - UI threads call only `auth_state()` and `retry_sign_in()`.
  - Data calls go through `run_bg`.
  - Stale results are dropped using per-view tokens.
  - `teams_busy` prevents overlapping HOME loads.
- `_lock` is never held across I/O. `_init_lock` is taken only on worker threads.
- Small deviation: TUI `HomeView.action_reload` starts the Teams job before the other HOME jobs, while the spec says
  "then". This has no functional effect.

## Maintainability Assessment

- The state machine (idle, loading, signin, error, loaded) is explicit and named the same way in both UIs.
- Functions are short. `_token` and `_get` are the most complex, and both follow the spec algorithm step by step.
- Constants are in one place (C1) and are read at call time, so tests can patch them.
- The TUI uses `rich.text.Text` cells and lines everywhere, which avoids markup injection.
- Some duplication follows existing patterns and is accepted by the spec (CR-001).

## Technical Debt Assessment

The technical debt is low and acceptable:

- Duplication between panes, as the spec directs (CR-001).
- One unused field (CR-002).
- Minor lock and loop clarity issues in `teams_ops` (CR-003).
- `_wrap` does not use `functools.wraps` (CR-004).

There are no shortcuts or hacks. Tests that patch module globals depend on the "read at call time" rule. That rule
is documented in the spec and in comments.

## Documentation Assessment

- Every public function has a docstring.
- The module docstring states the config and token paths.
- The in-app help (`HELP["teams"]`, `GLOBAL_HELP`, HOME rows) exists in both UIs.
- The setup steps are in `NOT_CONFIGURED_MSG`.
- Comments explain why, for example "never held across I/O" and "another thread just finished".
- One small difference between the TUI and GUI help text (CR-005).

## Findings

### CR-001

Severity: Low

Category: Duplication

Description: Two pieces of code are duplicated.

1. `gui.TeamsPane.__init__` and `move()` copy about 60 lines from `OutlookPane`: the title, pill bar, list and text
   `RoundFrame`s, focus-ring bindings and the `move` logic.
2. `TeamsView._styles` / `_lines` duplicate `HomeView._styles` / `_lines`.

The spec asks for both copies ("Layout copies OutlookPane.__init__", "identical to OutlookPane.move", "same as
HomeView._lines").

Impact: A layout or navigation fix in one list/text pane has to be repeated in the others.

Recommendation: In a later clean-up, move the list-plus-text pane skeleton and `move()` into a small GUI base class
(for example `ListTextPane`), and the tag-to-style rendering into one shared TUI helper. Not required for this release.

Affected Components: `gui.py` (`OutlookPane`, `TeamsPane`), `tui_panes.py` (`TeamsView`), `tui_home.py` (`HomeView`)

### CR-002

Severity: Low

Category: Readability

Description: `TeamsView.messages_for` is set in `_load_messages` but never read. The GUI pane does not have this
field.

Impact: A future maintainer may think it controls behaviour.

Recommendation: Remove it, or use it to skip reloading when the same chat is selected again.

Affected Components: `tui_panes.py` `TeamsView`

### CR-003

Severity: Low

Category: Maintainability

Description: Three small clarity issues in `teams_ops`:

1. In `_token`, the error raised after a failed `initiate_device_flow` reads `_auth.error` outside `_lock`. The local
   `reason` value could be used instead.
2. The `log.debug` call in `_complete_flow` reads `_auth.state` outside the lock.
3. The 401 branch of `_get` uses a third counter state (`unauthorized > 2`) that cannot normally be reached, which makes
   the retry loop harder to follow.

Impact: These are benign today, because `_auth` is only read and the values are just used for messages. They do
weaken the "fields only under `_lock`" rule a reader would rely on.

Recommendation:

- Format the message from the local `reason`.
- Log the outcome from a local variable.
- After a second 401, call `_forget_accounts()` and `_token()`. If `_token()` returns, raise
  `TeamsError("... (401)")`.

Affected Components: `teams_ops._token`, `_complete_flow`, `_get`

### CR-004

Severity: Low

Category: Maintainability

Description: `_wrap` copies `__name__` and `__doc__` by hand. It does not use `functools.wraps`, so `__wrapped__`,
`__qualname__` and the signature are lost. This copies the existing `google_ops._wrap` pattern.

Impact: IDE and help introspection are slightly worse. There is no runtime effect.

Recommendation: Use `functools.wraps(fn)` here, and in `google_ops` when that module is next touched.

Affected Components: `teams_ops._wrap`

### CR-005

Severity: Low

Category: Documentation

Description: The HOME help `r` row differs between the UIs:

- GUI: "...; restarts a failed Teams sign-in"
- TUI `app.py`: no mention of the restart, although TUI HOME `r` also calls `reload(True)`.

Impact: TUI users may not find out that HOME `r` retries a failed sign-in.

Recommendation: Add the same clause to the TUI `HELP["home"]` `r` row.

Affected Components: `app.py` `HELP["home"]`

### CR-006 (fixed during review)

Severity: Low

Category: Readability

Description: Four cosmetic and convention issues were found and **fixed** during the review, with CRLF kept:

1. **BUG-001:** `app.py` line 328 had a bare LF. It is normalised to CRLF. The `app.py` exception in
   `tests/test_validation_gaps.py::test_python_files_are_crlf` is removed, so the test now requires 0 bare LF in
   every `.py` file.
2. `app.py` `HELP["home"]` `(what)` text had nine extra spaces in the middle of the sentence ("today's usage,
   this work week's ..."). These spaces were visible in the help screen.
3. `app.py` `HELP["home"]` `r` row was indented wrongly (16 spaces instead of 8).
4. `tui_home.py` had no blank line between `render_all()` and `render_monitor()`.

Impact: Cosmetic only. The full suite passes after the fixes (186 passed).

Recommendation: None. This finding is closed.

Affected Components: `lcars_dash/app.py`, `lcars_dash/tui_home.py`, `tests/test_validation_gaps.py`

### Observations (no action)

- HOME reloads (`r` and every 5 minutes) call `summary(max_age=0)`. With the caps, each reload makes up to
  1 + 1 + 15 GET requests. This is the intended design (spec R-A4, ASSUMPTION-A9). Watch for throttling in real use.
- The module global `_expand_members` is changed without the lock. This is benign: the flag only ever changes from
  True to False and stays False.
- BUG-002 (the TUI `y` key works only on StatusView) matches the spec. The help text documents it.

## Approval Checklist

[X] Requirements Implemented
[X] Architecture Followed
[X] Maintainability Acceptable
[X] Logging Acceptable (debug logger only, no tokens/content; diagnostics surfaced in UI status lines per spec)
[X] Documentation Acceptable

## Final Status

APPROVED

APPROVED WITH NOTES: only Low findings. CR-006 is fixed. CR-001 to CR-005 are optional clean-ups for later.
Forward to the Security Engineer. Focus areas from the spec: the DPAPI fallback, the URL guard, the markup-injection
handling and the use of locks. Nothing has been committed.
