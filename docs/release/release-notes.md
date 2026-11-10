# Release Notes: Microsoft Teams Chat (read-only)

Date: 2026-11-10 · Feature: read-only Microsoft Teams chats in the LCARS Dashboard (TUI and GUI)
Status of the feature: tested offline (244 passing tests, 3 consecutive runs), reviewed (code review, security
review, documentation review). Live tenant verification is a manual post-install step (see Known Limitations).

## Highlights

The dashboard can now show your Microsoft Teams chats next to your repositories, calendar, mail and usage. It shows
your 1:1, group and meeting chats, newest first. Unread chats are marked `*`, and unread messages that mention you
are marked `@`. Nothing is ever sent, edited, deleted or marked as read.

## Features

- **TEAMS tab** in both front ends: chat list and message pane.
- **HOME box** "TEAMS CHAT // UNREAD + MENTIONS", reachable by Tab and click.
- **Sign-in with a device code** shown in the pane. No client secret is used. The app is a public client.
- **Least-privilege scopes:** delegated `Chat.Read` and `User.Read` only.
- **Encrypted token cache** (Windows DPAPI via `msal-extensions`). Falls back to memory only, with a visible notice.
- **Shortcuts:** `Shift+F11` opens TEAMS from any view. `y` opens it from the status view. `r` reloads or restarts a
  failed sign-in.

## Changes to existing behaviour

- New keys: `Shift+F11` (`F23` alias in the TUI) and `y` (status view only). Existing keys are unchanged;
  `F11` still opens Gmail.
- GUI nav pill height reduced from 58 to 54 pixels to fit the TEAMS pill.
- HOME Tab order now ends with the Teams box.
- New dependencies in `requirements.txt`: `msal`, `msal-extensions`, `requests`. Run
  `python -m pip install -r requirements.txt` after updating.

## Fixes

- Security hardening found in review (all resolved before release):
  - Control and invisible characters are removed from chat text and error messages (SEC-001).
  - Crafted HTML cannot cause a long CPU stall: input is capped and parsed linearly (SEC-002).
  - Graph URLs and chat identifiers are validated, including `nextLink` values (SEC-005).
  - The status line cannot be misread as markup (SEC-004).
  - Dependency minimum versions raised (SEC-003).
- Line endings normalised to CRLF in `app.py` and `gui.py` (BUG-001 and a GUI equivalent).
- HOME help text spacing and indentation corrected in the TUI (CR-006).

## Installation and upgrade

1. Update the repository.
2. `python -m pip install -r requirements.txt`
3. Optional: `python -m pip install -r requirements-dev.txt` and `python -m pytest` to run the offline tests.
4. Teams is off until you create `~/.lcars_dash/teams_config.json`. Follow the README, section "Microsoft Teams
   (read-only)". The dashboard works without Teams configured.

No data migration is needed. No existing configuration file changes.

## Rollback

- Disable Teams: delete or rename `~/.lcars_dash/teams_config.json` and delete `~/.lcars_dash/teams_token.bin`.
- Revert: check out the previous release. Installed libraries can stay.

Details are in the README, section "Disabling Teams (rollback)".

## Known limitations

- **Read-only.** No sending, editing, deleting or marking as read.
- **Chats only.** Channels, teams and meeting calendar or transcript data are not supported and are never requested.
- **Delegated access only.** You see what your own account can see in Teams.
- **Recent chats only.** Up to 50 chats per refresh. Message history is paged and capped.
- **No in-app sign-out.** Quit the app, then delete `teams_token.bin` (SEC-006, deferred).
- **Windows encrypted cache.** Elsewhere, sign-in is not remembered between starts.
- **Shift+F11 depends on the terminal.** Use `y`, the TEAMS pill, or Tab to the Teams box on HOME as fallbacks.
- **Not verified against a live tenant.** The automated suite uses faked Microsoft services. After installation,
  check: sign-in with a real work account, the 403 path before and after consent, token persistence across restarts
  (DPAPI), and HOME refresh timing.

## Known issues (open, not release-blocking)

| ID | Severity | Summary |
|---|---|---|
| SEC-007 | Low | The Graph path allow-list matches `/v1.0/me` as a prefix. Harmless with the current scopes. Tighten before widening scopes. |
| CR-001 | Low | Layout and navigation code is duplicated between the Outlook and Teams panes. |
| CR-002 | Low | An unused field in `TeamsView`. |
| CR-003 | Low | A few reads of shared state happen outside the lock. Benign today. |
| CR-004 | Low | `_wrap` does not use `functools.wraps`. |
| CR-005 | Low | The TUI HOME help `r` row does not mention that `r` restarts a failed sign-in. |
| DOC-001 | Low | The design spec's deployment section lists older dependency floors than `requirements.txt`. The README and `requirements.txt` are correct. |

## Support

- Setup, sign-in and troubleshooting: `README.md`.
- Requirements and design: `docs/design/`.
- Test evidence: `docs/testing/test-report.md`.
- Reviews: `docs/reviews/`.
- Changes by version: `CHANGELOG.md`.
