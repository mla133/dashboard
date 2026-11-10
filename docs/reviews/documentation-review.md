# Documentation Review

Feature: read-only Microsoft Teams chat (TUI and GUI) · Date: 2026-11-10 · Reviewer: Technical Writer
Inputs checked against code: `lcars_dash/teams_ops.py`, `app.py` (`HELP`, `GLOBAL_HELP`, bindings), `gui.py`
(`_bind_keys`, help tables, `main`), `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, and `docs/design/spec.md`.
Required inputs present: `requirements.md`, `spec.md`, `implementation-plan.md`, `implementation-summary.md`,
`test-report.md`, `code-review.md`, `security-review.md`.

## Documentation Summary

| Deliverable | Path | Status |
|---|---|---|
| README (new; no README existed) | `README.md` | Created. Covers install, Entra registration, config format, sign-in, keys, token cache and sign-out, rollback, troubleshooting, limitations, support. |
| Changelog (new) | `CHANGELOG.md` | Created. Added, Changed, Security, Fixed, Deprecated, Removed, Known limitations. |
| Release notes (new) | `docs/release/release-notes.md` | Created. Features, changes, fixes, install and upgrade, rollback, limitations, open issues. |
| Documentation review | `docs/reviews/documentation-review.md` | This report. |

Facts were verified against the code, not only the spec:

- Config path `~/.lcars_dash/teams_config.json`, keys `client_id` and `tenant_id`, and the validation messages match
  `_load_config`.
- Token path `~/.lcars_dash/teams_token.bin`, DPAPI via `msal-extensions`, and the in-memory fallback notice match
  `_make_cache`.
- Scopes `Chat.Read` and `User.Read` match `SCOPES`. Public client, device code flow, no secret matches
  `PublicClientApplication` use.
- Keys: `shift+f11` / `f23` (TUI) and `<Shift-F11>` (GUI) open Teams from any view. `y` opens it only from the status
  view in both UIs (`app.py` binding on StatusView; `gui.py` `_bind_keys` filters non-status views). `r` reloads and
  restarts a failed sign-in (`reload(retry=True)` and `retry_sign_in`). `?` / `F4` open help.
- Sign-out procedure (quit, then delete `teams_token.bin`) matches the in-app help and SEC-006.
- Error strings quoted in the README match `teams_ops.py` text (not configured, libraries missing, cannot reach
  sign-in, tenant rejected, 403 consent, 401, sign-in failed, cache unavailable, waiting for sign-in).
- Limits quoted (50 chats, 20 messages scanned in up to 15 unread chats, `Retry-After` cap 10 s, 5 pages) match the
  module constants.
- Test count quoted (244) matches a fresh offline run on 2026-11-10.

## Deliverables Reviewed

README.md

architecture.md (not produced as a separate file; architecture is covered by `docs/design/spec.md`, Architecture
Summary and Component Responsibilities, which is the permanent design reference)

installation-guide.md (not produced as a separate file; installation is covered in README.md, Installation)

configuration-guide.md (not produced as a separate file; configuration is covered in README.md, Step 2 and the
Configuration reference)

deployment-guide.md (not produced as a separate file; deployment is a local `pip install` plus launch, covered in
README.md and release notes)

operations-guide.md (not produced as a separate file; sign-in, keys, refresh behaviour and token lifecycle are in
README.md)

troubleshooting-guide.md (not produced as a separate file; troubleshooting is in README.md, Teams troubleshooting)

docs/release/release-notes.md

CHANGELOG.md

## Release Readiness Checklist

[X] Architecture Documented (`docs/design/spec.md`; summarised in README Support section)

[X] Installation Documented (README, Installation; release notes, Installation and upgrade)

[X] Configuration Documented (README, Step 2 and Configuration reference)

[X] Operations Documented (README, Running, Keys, Refresh behaviour, Token cache and sign-out)

[X] Troubleshooting Documented (README, Teams troubleshooting, Diagnostics, Support checklist)

[X] Release Notes Created (`docs/release/release-notes.md`)

[X] Rollback Documented (README, Disabling Teams; release notes, Rollback)

[ ] Live tenant verification (manual; tracked as a known limitation, not a documentation defect)

## Findings

DOC-001

Severity: Low

Status: RESOLVED. `docs/design/spec.md` Deployment block now lists `msal-extensions>=1.3` and `requests>=2.32.4`,
matching `requirements.txt`.

Description: `docs/design/spec.md`, Deployment Considerations, listed `msal-extensions>=1.1` and `requests>=2.31`. The
actual `requirements.txt` has `msal-extensions>=1.3` and `requests>=2.32.4` (SEC-003 fix).

DOC-002

Severity: Low

Status: RESOLVED. TUI `HELP["home"]` `r` row now ends "; restarts a failed Teams sign-in", matching the GUI (also
closes CR-005).

Description: The TUI HOME help row for `r` (`lcars_dash/app.py`, `HELP["home"]`) did not say that `r` also restarts a
failed Teams sign-in.

DOC-003

Severity: Low

Description: The code-review artifact quotes 186 passing tests. The current suite has 244 tests, all passing. The
review was done before the security fixes added tests. The release notes and changelog use 244.

Recommendation: No change needed. The code review remains accurate for the code it reviewed. Note the count when
citing test evidence.

DOC-004

Severity: Low

Description: Separate architecture, installation, configuration, deployment, operations and troubleshooting guides were
not produced as files. Their content is in `README.md`, `docs/design/spec.md` and the release notes. For a single
local desktop application with one feature, this is proportionate, but the README has become the main operator
document.

Recommendation: If the project grows, split the README Teams section into `docs/` guides. No action needed for this
release.

## Verification Notes

- Each README and release note fact listed under Documentation Summary was checked against the source files named
  there.
- The README was corrected during review for: `Esc` versus `F1` (TUI `Esc` behaviour is not consistent between HELP
  and the smoke test, so only `F1` is cited); the `@` marker wording (spec: unread messages that mention you); the
  sign-in code lifetime (no timer in the code, so no number is given); and the error-length claim (a cut-off applies
  only to some messages).
- No production code was changed. No commit was made.

## Final Status

APPROVED

Rationale: all required deliverables exist and match the implementation. DOC-001 and DOC-002 are resolved. DOC-003
and DOC-004 are informational Low notes needing no action. Live tenant verification remains a manual post-install
step and is not a documentation defect.

Forwarded to: Agents Orchestrator for final release evaluation.
