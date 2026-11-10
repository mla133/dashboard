# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no version
numbers yet, so changes are grouped under `Unreleased` until a release is tagged.

## [Unreleased] - 2026-11-10

### Added

- Read-only Microsoft Teams chat support (1:1, group and meeting chats) through Microsoft Graph.
  - New data module `lcars_dash/teams_ops.py`: configuration, MSAL device code sign-in, encrypted token cache,
    Graph chat and message reads, HTML-to-text conversion, unread and mention summary.
  - TUI: TEAMS tab (`TeamsView`), `Shift+F11` / `F23` / `y` (status view) shortcuts, sidebar pill, help entries.
  - GUI: TEAMS pane (`TeamsPane`), `Shift+F11` / `y` shortcuts, nav pill, help entries.
  - HOME: "TEAMS CHAT // UNREAD + MENTIONS" box in both front ends (last in tab order).
  - Configuration file `~/.lcars_dash/teams_config.json` (`client_id`, `tenant_id`). No Teams environment variables
    or command-line options.
  - Token cache `~/.lcars_dash/teams_token.bin`, encrypted with Windows DPAPI through `msal-extensions`. If the cache
    cannot be used, the token is kept in memory only and the UI says so.
- Dependencies in `requirements.txt`: `msal>=1.28`, `msal-extensions>=1.3`, `requests>=2.32.4`.
- Development dependency `pytest>=8.0` in `requirements-dev.txt`, and `pytest.ini`.
- Offline test suite (`tests/`, 244 tests) covering configuration, sign-in, Graph access, parsing, UI smoke tests and
  security regressions. Network access is blocked by the test harness.
- Documentation: `README.md` (installation, Entra app registration, sign-in, keys, troubleshooting, limitations),
  `docs/release/release-notes.md`, `docs/reviews/documentation-review.md`.

### Changed

- GUI navigation pill height reduced from 58 to 54 pixels to fit the TEAMS pill.
- HOME Tab order now ends with the Teams box.
- Dashboard help (TUI and GUI) lists Teams shortcuts and the sign-out procedure.

### Security

- Terminal control characters, bidirectional overrides and zero-width characters are removed from all Teams text
  (chat titles, names, previews, message bodies, error text and sign-in text) before display (SEC-001).
- HTML message bodies are length-capped and parsed in a single linear pass, which removes a regex slowdown on
  crafted input (SEC-002).
- Graph URLs, including `nextLink` values, must be `https://graph.microsoft.com` on the allow-listed `/v1.0/me`
  paths. Chat identifiers are validated (SEC-005).
- The status line is rendered as plain text, not Rich markup (SEC-004).
- Dependency floors raised for `requests` and `msal-extensions` (SEC-003).

### Fixed

- `lcars_dash/app.py` and `lcars_dash/gui.py` line endings normalised to CRLF (BUG-001 and the GUI equivalent found
  during the TDD pass).
- Dashboard help text corrected: HOME help spacing and indentation (CR-006).

### Deprecated

- Nothing.

### Removed

- Nothing.

### Known limitations

- Teams is read-only: no sending, editing, deleting or marking as read. Channels, teams and meeting
  calendar/transcript data are not supported.
- No in-app sign-out. Sign-out requires quitting the app and deleting `teams_token.bin` (SEC-006).
- Live Microsoft 365 / Entra sign-in, DPAPI persistence on the target machine and refresh timing are verified
  manually after installation, not by the automated suite.
- Open low-severity notes: SEC-007 (Graph path allow-list is a prefix match on `/v1.0/me`), CR-001 to CR-005 (code
  clean-ups), and spec documentation drift (see `docs/reviews/documentation-review.md`).
