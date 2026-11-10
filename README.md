# LCARS Dashboard

A terminal (Textual) and desktop (Tkinter) dashboard for watching repository activity, Copilot sessions, usage,
calendars, mail and Microsoft Teams chats in one place. Local use only; Windows is the target platform
(DPAPI token encryption and the Outlook integration both depend on it).

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Running](#running)
- [Microsoft Teams (read-only)](#microsoft-teams-read-only)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Support](#support)

## Requirements

- Windows 10 or later (token cache uses Windows DPAPI).
- Python 3.13 (the version used in development).
- Network access to `login.microsoftonline.com` and `graph.microsoft.com` for Teams features only.
- A Microsoft 365 work account that can use Teams chats, and permission to register an app in your Entra ID
  tenant (or an administrator who can do it for you).

## Installation

From the repository root:

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` installs the Teams libraries (`msal`, `msal-extensions`, `requests`) together with the
rest of the dashboard dependencies (`textual`, `rich`, `pywin32`, Google API client).

Optional, for development and tests:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

The test suite runs offline. Network access is blocked by the test harness, so it never contacts Microsoft.

To check that the Teams libraries are installed:

```powershell
python -c "import msal, msal_extensions, requests; print('Teams libraries OK')"
```

If `msal` is missing, the Teams panes show `Teams libraries missing (msal): pip install msal msal-extensions requests`.
The rest of the dashboard still works.

## Running

| Front end | Command |
|---|---|
| Terminal (Textual) | `python -m lcars_dash` |
| Desktop (Tkinter) | `python -m lcars_dash.gui` |

Both accept `--root <folder>` (repeatable) to choose the folders that contain cloned repositories. Without it, the
roots come from `~/.lcars_dash.json`.

Press `?` (TUI) or `F4` (GUI) at any time for the in-app help.

## Microsoft Teams (read-only)

The Teams feature shows your 1:1, group and meeting chats, newest first. unread chats are marked `*`, and unread chats with a
message that mentions you are marked `@`. **Nothing is ever sent, edited, deleted or marked as read.**
The app only reads.

Teams appears in two places:

- The **TEAMS** tab (sidebar pill `TEAMS [⇧F11 / Y]` in the TUI, nav pill in the GUI). It has a chat list and a
  message pane.
- The **TEAMS CHAT // UNREAD + MENTIONS** box on HOME, which summarises unread chats and mentions and opens the
  TEAMS tab when clicked.

### Step 1: Register an app in Entra ID

You need this once per install. An administrator may need to do it for you.

1. Sign in to the [Entra admin center](https://entra.microsoft.com) and go to **Entra ID > App registrations >
   New registration**.
2. Name it (for example `LCARS Dashboard`). Under **Supported account types**, choose **Accounts in this
   organizational directory only (single tenant)**. Leave the Redirect URI empty.
3. Select **Register**. On the overview page, copy:
   - **Application (client) ID**
   - **Directory (tenant) ID**
4. Go to **Authentication**. Under **Advanced settings**, set **Allow public client flows** to **Yes**, then
   select **Save**. This enables the device code flow that the dashboard uses. The app does not use a client
   secret, so do not create one.
5. Go to **API permissions > Add a permission > Microsoft Graph > Delegated permissions**. Add:
   - `Chat.Read`
   - `User.Read`

   Do not add any other permissions. The dashboard requests only these two scopes (plus the standard
   `openid`, `profile` and `offline_access`, which MSAL adds itself).
6. **Tenant consent:** `Chat.Read` may require administrator consent in your tenant. If the **Status** column
   does not show **Granted for <your tenant>**, select **Grant admin consent for <your tenant>**, or ask an
   administrator to do it. Without consent, sign-in can succeed but reading chats fails with a 403 (see
   [Troubleshooting](#troubleshooting)).

### Step 2: Create the configuration file

Create `%USERPROFILE%\.lcars_dash\teams_config.json` (the folder `~/.lcars_dash` is the same location). Use the two
values from step 3:

```json
{
  "client_id": "11111111-2222-3333-4444-555555555555",
  "tenant_id": "66666666-7777-8888-9999-000000000000"
}
```

| Key | Required | Format | Example |
|---|---|---|---|
| `client_id` | yes | Application (client) ID GUID | `11111111-2222-3333-4444-555555555555` |
| `tenant_id` | yes | Directory (tenant) GUID, or a verified domain name | `contoso.onmicrosoft.com` |

Rules, enforced by the app:

- The file must be a JSON object. Extra keys are ignored.
- Both keys must be non-empty strings.
- `client_id` must be a GUID. `tenant_id` may contain letters, digits, dots and hyphens only.

The file is read again on each refresh, so you can fix it and press `r` without restarting. Do not put a client
secret in this file. The app does not use one.

If the file is missing or invalid, the Teams pane shows `Teams not configured: create
~/.lcars_dash/teams_config.json`, followed by the setup steps and a `Reason:` line (for example `missing
tenant_id`).

### Step 3: Sign in

1. Start the dashboard and open the TEAMS tab, or press `r` on HOME.
2. The pane shows a sign-in prompt in this form:

   ```text
   Sign in: https://microsoft.com/devicelogin  code ABCD1234
   Waiting for sign-in... (r to retry)
   ```

   The address is the one Microsoft returns; it is usually `microsoft.com/devicelogin`.
3. Open that address in a browser, enter the code, and sign in with your work account.
4. Accept the `Chat.Read` and `User.Read` prompt if you see one.
5. Return to the dashboard. The chat list loads automatically when sign-in completes.

Sign-in codes expire after a set time (Microsoft sets the limit; the app does not show a countdown). If the code expires, or you decline the prompt, the pane shows
`Teams sign-in failed: <reason> (press r to retry)`. Press `r` to start a new code.

Only one sign-in can be pending at a time. Pressing `r` while a code is waiting does not start a second one.

### Keys

**Global (any view)**

| Key | Action |
|---|---|
| `Shift+F11` | Open the TEAMS tab. TUI: `shift+f11` or `f23` (some terminals send this). GUI: `Shift+F11`. |
| `y` | Open the TEAMS tab. Works only from the **status** view (the default view in both front ends). |
| Pill click | Click the TEAMS pill in the sidebar (TUI) or nav bar (GUI). |

If your terminal does not pass `Shift+F11` through, use `y` from the status view, the pill, or Tab to the Teams
box on HOME and press Enter.

**TEAMS tab, terminal (TUI)**

| Key | Action |
|---|---|
| `j` / `k` | Move down / up through chats (or scroll the messages when focused) |
| `g` / `G` | Top / bottom |
| `Ctrl+d` / `Ctrl+u` | Page down / up |
| `l` or `Enter` | Read the selected chat (moves focus to the messages) |
| `h` | Back to the chat list |
| `Tab` | Switch between the list and the messages |
| `r` | Reload chats. Also restarts sign-in if it failed or expired. |
| `Esc` | Back to the repository list |

**TEAMS tab, desktop (GUI)**

Use the **READ** and **RELOAD [R]** pills at the top of the pane, or `R` to reload. Moving between chats uses
the same focus behaviour as the Outlook pane.

**HOME**

| Key | Action |
|---|---|
| `r` | Reload everything, including Teams. Also restarts a failed Teams sign-in. |
| `Tab` / `Enter` | Move to the Teams box and open the TEAMS tab. |

### Refresh behaviour

- HOME refreshes every 5 minutes, and `r` refreshes immediately.
- Each refresh reads up to 50 of your most recent chats. It scans the last 20 messages of up to 15 unread chats
  to find mentions.
- Chat and message fetches are paged and capped. Large chat histories are not loaded in full.
- Teams calls run in background threads, so the rest of the dashboard stays responsive during a refresh or
  sign-in.

### Token cache and sign-out

- After a successful sign-in, the token is stored in `%USERPROFILE%\.lcars_dash\teams_token.bin`.
  The file is encrypted with Windows DPAPI, so it can be read only by your Windows user account. It is never
  stored as plaintext.
- If the encrypted cache cannot be used, the app keeps the token in memory only. The pane then shows
  `Teams token cache unavailable (...); sign-in will not be remembered.` You will have to sign in again each
  time the app starts. Install `msal-extensions` to fix this (`python -m pip install -r requirements.txt`).
- **Sign-out:** there is no sign-out button. To sign out:
  1. Quit the dashboard completely.
  2. Delete `%USERPROFILE%\.lcars_dash\teams_token.bin`.

  A running app keeps its session until it exits. Deleting the file while the app is running does not sign
  out the current session. The next sign-in starts a fresh device code prompt.
- To revoke the app's access entirely, remove the consent in **Entra ID > Enterprise applications** for the app,
  or ask your administrator to do so.

### Teams troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| `Teams not configured: create ~/.lcars_dash/teams_config.json` with a `Reason:` line | File missing or invalid. The reason says which. | Fix the file as shown in [Step 2](#step-2-create-the-configuration-file), then press `r`. |
| `Reason: client_id is not a GUID` | `client_id` is not the Application (client) ID GUID. | Copy the exact value from the app overview page. |
| `Reason: tenant_id has invalid characters` | `tenant_id` contains spaces, slashes or other characters. | Use the Directory (tenant) ID GUID or a plain domain name. |
| `Reason: tenant_id rejected by Microsoft sign-in` | Microsoft does not recognise the tenant. | Check the Directory (tenant) ID. |
| `Teams libraries missing (msal): ...` | Dependencies not installed. | `python -m pip install -r requirements.txt` |
| `Cannot reach Microsoft sign-in: ...` | No network, or a proxy/firewall blocks `login.microsoftonline.com`. | Check the connection, then press `r`. |
| `Teams sign-in failed: code expired (press r to retry)` | The code was not entered in time. | Press `r` and sign in with the new code. |
| `Teams sign-in failed: sign-in declined (press r to retry)` | The sign-in prompt was declined. | Press `r` and accept the prompt. |
| `Teams sign-in failed: ...AADSTS7000218...` or similar `client_secret` / `client_assertion` text | Public client flows are not enabled for the app. | Entra ID > App registrations > your app > Authentication > **Allow public client flows** = Yes. Then press `r`. |
| `Microsoft Graph denied access (403): Chat.Read consent is missing ...` | `Chat.Read` (and `User.Read`) are not consented for your tenant. | Add both delegated permissions and grant admin consent, then sign out (see above) and sign in again. |
| `Microsoft Graph rejected the sign-in (401)` | The token was refused, usually after a permission change. | Quit, delete `teams_token.bin`, restart, and sign in again. |
| `Teams token cache unavailable (...)` | `msal-extensions` missing, or the cache file could not be written. | Install the dependencies. Check that `%USERPROFILE%\.lcars_dash` is writable. |
| Chats load slowly or stop updating | Microsoft Graph is throttling requests (HTTP 429). | Wait a minute and press `r`. The app honours `Retry-After`, capped at 10 seconds. |
| `Shift+F11` does nothing | The terminal or OS intercepts the key. | Use `y` from the status view, the TEAMS pill, or Tab to the Teams box on HOME. |
| `y` does nothing | `y` works only from the status view. | Press `F1` to reach status, then `y`. |
| Pane says `Waiting for sign-in... (r to retry)` for a long time | You have not completed the browser step. | Complete the sign-in, or press `r` to get a new code. |
| No chats listed | You have no chats in the window the app reads, or the account has no Teams chats. | Confirm in the Teams client. |

**Diagnostics:** the Teams code writes debug messages to the `lcars_dash.teams` logger. No log handler is
configured by default, so these messages are not shown. Most problems are visible in the Teams pane status line.
Error text from Microsoft is cleaned of control characters, and some messages are shortened. Tokens and message
content are never written to logs.

**Support checklist** (collect before raising an issue):

1. Output of `python -m pip show msal msal-extensions requests`.
2. The exact status line shown in the Teams pane (copy it; do not include your code or tokens).
3. Whether `teams_config.json` exists and which keys it contains. Do not paste the GUID values publicly.
4. Whether the app is running on the same Windows account that created `teams_token.bin`.

## Configuration reference

| Path | Purpose | Who writes it |
|---|---|---|
| `~/.lcars_dash/teams_config.json` | Teams `client_id` and `tenant_id`. Read only. | You |
| `~/.lcars_dash/teams_token.bin` | DPAPI-encrypted MSAL token cache. | The app (MSAL) |
| `~/.lcars_dash.json` | Dashboard settings, including the default repo roots and theme. | The app / you |

Teams has no environment variables and no command-line options. All Teams settings live in
`teams_config.json`. The `~` path is your Windows user profile folder.

### Disabling Teams (rollback)

Teams is optional. To turn it off without removing the dashboard:

1. Quit the dashboard.
2. Rename or delete `%USERPROFILE%\.lcars_dash\teams_config.json`. The TEAMS pane then shows the "not configured"
   message and nothing is requested from Microsoft.
3. Delete `%USERPROFILE%\.lcars_dash\teams_token.bin` to remove the cached sign-in.

To roll back to a version without Teams, check out the previous release in your repository, then run
`python -m pip install -r requirements.txt` again. The Teams libraries can stay installed; nothing else uses them.

## Limitations

- **Read-only.** The app never sends, edits, deletes or marks messages as read. It makes only HTTP `GET` requests.
- **Chats only.** 1:1, group and meeting chats are shown. **Channels, teams and meetings** (calendar or
  transcripts) are not supported and are never requested.
- **Delegated access only.** The app uses your own sign-in and sees only what you can see in Teams. It has no
  application-level or admin access.
- **Recent chats only.** The list shows up to 50 chats. Message history is paged and capped, so very old messages
  may not load.
- **No in-app sign-out.** Sign-out is manual (see [Token cache and sign-out](#token-cache-and-sign-out)).
- **Windows only** for the encrypted token cache. Elsewhere the app keeps the token in memory only and asks you to
  sign in each time it starts.
- **Shift+F11 depends on the terminal.** Some terminals do not send it. `y` and the pill are always available.
- **Live tenant verification is manual.** The automated test suite runs offline with faked Microsoft services.
  Sign-in against a real tenant, DPAPI persistence on your machine, and refresh timing must be checked by hand
  after installation (see the test report).

## Support

- Architecture and requirements: `docs/design/` (`requirements.md`, `spec.md`, `implementation-summary.md`).
- Test evidence: `docs/testing/test-report.md`.
- Reviews: `docs/reviews/`.
- Release notes and changes: `docs/release/release-notes.md` and `CHANGELOG.md`.
- Open security notes and follow-ups: `docs/reviews/security-review.md` (SEC-006 sign-out, SEC-007 path allow-list).
