from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, DataTable, Footer, OptionList, Static
from textual.widgets.option_list import Option

from . import config, copilot_ops, git_ops, panels, tests_ops
from .git_ops import RepoStatus
from .themes import DEFAULT_THEME, THEMES
from .tui_panes import (HelpScreen, MindchukView, MonitorView, SessionsView, TerminalView, UsageView, move)

HOMEDEV = Path.home() / "HomeDev"
COLUMNS = ("REPOSITORY", "VIEWING", "CHECKED OUT", "LAST UPDATED", "AGE", "BY", "SYNC", "HEALTH", "TESTS", "SOURCE")
SORT_KEYS = {
    0: lambda s: s.name.lower(),
    1: lambda s: s.view_branch.lower(),
    2: lambda s: s.branch.lower(),
    3: lambda s: s.last_date if s.last_date != "-" else "",
    4: lambda s: s.last_date if s.last_date != "-" else "",
    5: lambda s: s.last_author.lower(),
    6: lambda s: (s.last_date == "-" or bool(s.error), s.behind, s.ahead, s.dirty),
    7: lambda s: (s.changed + s.untracked, s.stashes, s.unmerged),
    8: None,  # needs instance state (test results)
    9: lambda s: s.source,
}
NEWEST_FIRST = (3, 4)

HELP = {
    "status": ("SOFTWAREDEVELOPMENT / HOMEDEV", [
        ("j / k, ↓ / ↑", "Move through repositories (or scroll the summary)"),
        ("click a header / S", "Sort by that column; again to reverse (S cycles the column from the keyboard)"),
        ("g / G", "Jump to first / last"),
        ("Ctrl+d / Ctrl+u", "Page down / up"),
        ("l / Enter", "Move focus to the summary pane"),
        ("h", "Back to the repository list (from the summary); from the list, open the HomeDev tab"),
        ("d", "Switch to the SoftwareDevelopment tab (also F1, or click it in the sidebar)"),
        ("Tab", "Switch between list and summary"),
        ("b", "Open the branch picker for the selected repository"),
        ("   in picker", "j/k or ↑/↓ move, g/G first/last, l or Enter select, h/Esc/q cancel"),
        ("(default)", "Each repository starts on its most recently updated branch"),
        ("r", "Refresh (git fetch + fast-forward pull) the selected repository"),
        ("a", "Refresh all repositories"),
        ("Ctrl+r", "Re-read status without touching the network"),
        ("o", "Open the selected repo in VS Code"),
        ("e", "Open the selected repo in Explorer"),
        ("p", "Start Copilot (new window) in the selected repo"),
        ("x", "Run the repo's tests (auto-detected, or set in ~/.lcars_dash.json); result shown in TESTS"),
        ("t / m / s / u", "Open Terminal (starts in the selected repo) / Mindchuk / Sessions / Usage"),
        ("(columns)", "SYNC: OK, OK* (uncommitted changes), ↓n behind, ↑n ahead, FAILED, ERROR"),
        ("(health)", "Mn modified/staged, ?n untracked, Sn stashes, Un branches not merged into main; or clean"),
        ("(tests)", "PASS/FAIL + age of the last run, RUNNING, N/A (no test command), - (never run)"),
        ("(source)", "ASSEMBLA, GITHUB, LOCAL (no remote), ... taken from the git remote URL"),
        ("(roots)", "Folders scanned (2 levels deep): set \"roots\" in ~/.lcars_dash.json; default SoftwareDevelopment + HomeDev"),
        ("(HomeDev tab)", "F8 / h lists repos under ~/HomeDev with the same keys; the SoftwareDevelopment tab lists the rest"),
    ]),
    "sessions": ("COPILOT SESSIONS", [
        ("j / k, g / G", "Move through sessions (or scroll the details)"),
        ("l / h", "Focus the details / the list"),
        ("Enter", "Resume the session: new PowerShell window running copilot --resume in its folder"),
        ("p", "Start a new Copilot session in that session's folder"),
        ("o", "Open that folder in VS Code"),
        ("a", "Toggle ALL REPOS / THIS REPO (the repo selected on the repo list)"),
        ("r", "Reload from ~/.copilot/session-store.db"),
        ("Esc", "Return to the repo list"),
    ]),
    "monitor": ("COPILOT MONITOR", [
        ("(what)", "One row per running Copilot CLI session; bars = activity events per 10 s over the last 10 min (oldest → newest)"),
        ("STATE", "WORKING (blue), WAITING? (orange: busy but silent 45 s+, maybe awaiting approval), IDLE"),
        ("r", "Refresh now (auto-refreshes every 3 s)"),
        ("o", "Open the session's folder in VS Code"),
        ("j / k", "Move"),
        ("Esc", "Return to the repo list"),
    ]),
    "usage": ("COPILOT USAGE", [
        ("d", "Cycle the period: 7 / 30 / 90 days"),
        ("r", "Reload"),
        ("j / k, g / G", "Scroll / top / bottom"),
        ("Esc", "Return to the repo list"),
        ("(columns)", "SESS sessions, CALLS model calls, TOKENS in+out, REQS premium-request multiplier sum"),
    ]),
    "terminal": ("TERMINAL", [
        ("Enter", "Run the command"),
        ("↑ / ↓", "Command history"),
        ("Ctrl+L (or cls)", "Clear the screen"),
        ("Ctrl+C", "Restart the PowerShell session"),
        ("Esc", "Return to the repo list"),
        ("(note)", "Line-based: full-screen/interactive programs are not supported"),
        ("(start dir)", "Opens in the repo selected on the repo list; changes when you pick another"),
        ("F4", "This help (the ? key types normally here)"),
    ]),
    "mindchuk": ("MINDCHUK", [
        ("j / k, g / G", "Move through entries (or scroll the text)"),
        ("l / h", "Focus the text / the list"),
        ("n", "New entry"),
        ("e", "Append to the selected entry"),
        ("x / u", "Archive / unarchive the selected entry"),
        ("d", "Delete the selected entry (asks first)"),
        ("v", "Show / hide archived entries"),
        ("r", "Reload the list"),
        ("Esc", "Return to the repo list"),
        ("— ENTRY EDITOR —", ""),
        ("Ctrl+S", "Save and send to Mindchuk"),
        ("Esc", "Cancel"),
        ("TAGS field", "Space/comma separated; added as #hashtags (start of a new entry, end of an append). Enter also saves"),
    ]),
}
GLOBAL_HELP = [
    ("F1 / d", "SoftwareDevelopment repos"), ("F8 / h", "HomeDev repos"), ("F2 / t", "Terminal"),
    ("F3 / m", "Mindchuk"), ("F6 / s", "Copilot Sessions"), ("F7 / u", "Copilot Usage"),
    ("F9 / w", "Monitor running Copilot sessions"),
    ("F4 / ?", "This help"), ("F5 / c", "Cycle colour theme (TNG, DS9, Klingon, Romulan, Vulcan; saved)"),
    ("q", "Quit (not while typing in the terminal)"),
]


class BranchPicker(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape,q,h", "dismiss(None)", "Cancel"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "first", show=False),
        Binding("G", "last", show=False),
        Binding("l", "select", show=False),
    ]

    def __init__(self, repo: str, names: list[str], current: str):
        super().__init__()
        self.repo, self.names, self.current = repo, names, current

    def compose(self) -> ComposeResult:
        with Vertical(id="picker", classes="dialog"):
            yield Static(f"SELECT BRANCH  //  {self.repo.upper()}", id="picker-title", classes="dialog-title")
            yield OptionList(*[Option(("● " if n == self.current else "  ") + n, id=n) for n in self.names])

    def on_mount(self) -> None:
        ol = self.query_one(OptionList)
        if self.current in self.names:
            ol.highlighted = self.names.index(self.current)
        ol.focus()

    def on_option_list_option_selected(self, e: OptionList.OptionSelected) -> None:
        self.dismiss(self.names[e.option_index])

    def action_cursor_down(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(OptionList).action_cursor_up()

    def action_first(self) -> None:
        self.query_one(OptionList).action_first()

    def action_last(self) -> None:
        self.query_one(OptionList).action_last()

    def action_select(self) -> None:
        self.query_one(OptionList).action_select()


class NavBlock(Static):
    """Clickable sidebar block."""

    def __init__(self, label: str, action: str, **kw):
        super().__init__(label, **kw)
        self.nav_action = action

    async def on_click(self) -> None:
        await self.app.run_action(self.nav_action)


class StatusView(Vertical):
    """Repository list + summary; letter shortcuts only apply while focus is in here."""
    BINDINGS = [
        Binding("r", "app.refresh_selected", "Refresh"),
        Binding("a", "app.refresh_all", "Refresh all"),
        Binding("ctrl+r", "app.rescan_status", "Re-read", show=False),
        Binding("b", "app.pick_branch", "Branch"),
        Binding("x", "app.run_tests", "Tests"),
        Binding("o", "app.launch('vscode')", "Code"),
        Binding("e", "app.launch('explorer')", "Explorer"),
        Binding("p", "app.launch('copilot')", "Copilot"),
        Binding("S", "app.cycle_sort", "Sort", show=False),
        Binding("t", "app.show_terminal", "Terminal"),
        Binding("m", "app.show_mindchuk", "Mindchuk"),
        Binding("s", "app.show_sessions", "Sessions"),
        Binding("u", "app.show_usage", "Usage"),
        Binding("w", "app.show_monitor", "Monitor"),
        Binding("c", "app.cycle_theme", "Theme", show=False),
        Binding("question_mark", "app.show_help", "Help", show=False),
        Binding("enter,l", "app.open_detail", "Open", show=False),
        Binding("h", "app.h_key", "HomeDev", show=False),
        Binding("d", "app.show_status", "SoftwareDev", show=False),
        Binding("tab", "app.toggle_focus", "Switch pane", show=False),
        Binding("j", "app.move(1)", show=False),
        Binding("k", "app.move(-1)", show=False),
        Binding("g", "app.move('top')", show=False),
        Binding("G", "app.move('bottom')", show=False),
        Binding("ctrl+d", "app.move(10)", show=False),
        Binding("ctrl+u", "app.move(-10)", show=False),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("SOFTWAREDEVELOPMENT", id="list-title")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=False)
        yield Static("SUMMARY", id="detail-title")
        yield VerticalScroll(id="detail")


class LcarsDash(App):
    CSS_PATH = "lcars.tcss"
    TITLE = "ASSEMBLA REPO ACTIVITY"
    BINDINGS = [
        Binding("f1", "show_status", "Software", show=False),
        Binding("f2", "show_terminal", show=False),
        Binding("f3", "show_mindchuk", show=False),
        Binding("f4", "show_help", show=False),
        Binding("f5", "cycle_theme", show=False),
        Binding("f6", "show_sessions", show=False),
        Binding("f7", "show_usage", show=False),
        Binding("f8", "show_homedev", show=False),
        Binding("f9", "show_monitor", show=False),
        Binding("ctrl+c", "interrupt", show=False, priority=True),
    ]

    def __init__(self, roots: list[Path] | None = None):
        saved = config.load().get("theme")
        self.lc_theme = saved if saved in THEMES else DEFAULT_THEME
        super().__init__()
        self.roots = roots or config.roots() or [Path.home()]
        self.repos: dict[str, RepoStatus] = {}
        self.views: dict[str, str] = {}  # user-chosen branch per repo
        self.busy: set[str] = set()
        self.tests_busy: set[str] = set()
        self.test_results = tests_ops.load_results()
        self.scope = "status"
        self.current_view = "status"
        self.sort_col: int | None = None
        self.sort_desc = False
        self._rebuilding = False

    # ---- theme ----
    @property
    def colors(self) -> dict[str, str]:
        return THEMES[self.lc_theme]

    def get_css_variables(self) -> dict[str, str]:
        v = super().get_css_variables()
        v.update({f"lc-{k.lower()}": val for k, val in THEMES[self.lc_theme].items()})
        return v

    def themed(self, markup: str) -> str:
        """Map colours in panels.py markup (default theme) to the active theme."""
        rev = {v.lower(): k for k, v in THEMES[DEFAULT_THEME].items()}
        return re.sub(r"#[0-9a-fA-F]{6}", lambda m: self.colors.get(rev.get(m.group(0).lower(), ""), m.group(0)), markup)

    def action_cycle_theme(self) -> None:
        names = list(THEMES)
        self.lc_theme = names[(names.index(self.lc_theme) + 1) % len(names)]
        config.save(theme=self.lc_theme)
        self.refresh_css()
        self._label_theme()
        self._rebuild()
        s = self._selected()
        if s:
            self.show_detail(s)
        self.query_one(UsageView).render_usage()
        self.say(f"Theme: {self.lc_theme}")

    def _label_theme(self) -> None:
        self.query_one("#n-theme", NavBlock).update(f"THEME [F5 / C]\n{self.lc_theme}")

    # ---- layout ----
    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("STARFLEET REPOSITORY ACTIVITY  //  ASSEMBLA", id="title")
            yield Static("", id="cap")
            yield Static("", id="clock")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield NavBlock("SOFTWAREDEVELOPMENT\n[F1 / D]", "show_status", id="n-status", classes="block")
                yield NavBlock("HOMEDEV\n[F8 / H]", "show_homedev", id="n-homedev", classes="block")
                yield NavBlock("TERMINAL\n[F2 / T]", "show_terminal", id="n-terminal", classes="block")
                yield NavBlock("MINDCHUK\n[F3 / M]", "show_mindchuk", id="n-mindchuk", classes="block")
                yield NavBlock("SESSIONS\n[F6 / S]", "show_sessions", id="n-sessions", classes="block")
                yield NavBlock("USAGE\n[F7 / U]", "show_usage", id="n-usage", classes="block")
                yield NavBlock("MONITOR\n[F9 / W]", "show_monitor", id="n-monitor", classes="block")
                yield Static("", id="spacer")
                yield NavBlock("", "cycle_theme", id="n-theme", classes="block")
                yield NavBlock("HELP\n[F4 / ?]", "show_help", id="n-help", classes="block")
            with ContentSwitcher(id="views", initial="v-status"):
                yield StatusView(id="v-status")
                yield TerminalView(id="v-terminal")
                yield MindchukView(id="v-mindchuk")
                yield SessionsView(id="v-sessions")
                yield UsageView(id="v-usage")
                yield MonitorView(id="v-monitor")
        yield Static("j/k move  g/G top/bottom  l/Enter open  b branch  r/a refresh  x tests  o code  e explorer  p copilot  "
                     "s sessions  u usage  ? help  q quit", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#table", DataTable).focus()
        self._build_columns()
        self._label_theme()
        self.set_interval(1, self._tick)
        self._tick()
        self.load_all()

    def _tick(self) -> None:
        self.query_one("#clock", Static).update(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    def say(self, msg: str) -> None:
        self.query_one("#statusbar", Static).update(msg)

    async def action_quit(self) -> None:
        self.query_one(TerminalView).shutdown()
        self.exit()

    # ---- views ----
    def _switch(self, name: str) -> None:
        self.current_view = name
        self.query_one(ContentSwitcher).current = f"v-{name}"

    def action_show_status(self, scope: str = "status") -> None:
        self._switch("status")
        self.query_one("#table", DataTable).focus()
        if scope != self.scope:
            self.scope = scope
            self._set_scope()

    def action_show_homedev(self) -> None:
        self.action_show_status("homedev")

    def action_h_key(self) -> None:
        if isinstance(self.focused, DataTable):
            self.action_show_homedev()
        else:
            self.query_one("#table", DataTable).focus()

    def action_show_terminal(self) -> None:
        self._switch("terminal")
        s = self._selected()
        self.query_one(TerminalView).open(s.path if s else self.roots[0])

    def action_show_mindchuk(self) -> None:
        self._switch("mindchuk")
        self.query_one(MindchukView).open()

    def action_show_sessions(self) -> None:
        self._switch("sessions")
        self.query_one(SessionsView).open()

    def action_show_usage(self) -> None:
        self._switch("usage")
        self.query_one(UsageView).open()

    def action_show_monitor(self) -> None:
        self._switch("monitor")
        self.query_one(MonitorView).open()

    def action_show_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss(None)
            return
        title, rows = HELP[self.current_view]
        self.push_screen(HelpScreen([(title, rows), ("ANYWHERE", GLOBAL_HELP)]))

    def action_interrupt(self) -> None:
        if self.current_view == "terminal":
            self.query_one(TerminalView).restart()
        else:
            self.notify("Press q (repo list) to quit")

    # ---- keyboard navigation (vim-style alongside arrows) ----
    def action_move(self, step) -> None:
        move(self, step)

    def action_open_detail(self) -> None:
        if isinstance(self.focused, DataTable):
            self.query_one("#detail").focus()

    def action_toggle_focus(self) -> None:
        if isinstance(self.focused, DataTable):
            self.query_one("#detail").focus()
        else:
            self.query_one("#table", DataTable).focus()

    @work(thread=True, exclusive=True, group="branches")
    def action_pick_branch(self) -> None:
        s = self._selected()
        if not s:
            return
        names = git_ops.branch_names(s.path)
        if not names:
            self.call_from_thread(self.say, f"{s.name}: no branches")
            return
        self.call_from_thread(self._open_picker, s, names)

    def _open_picker(self, s: RepoStatus, names: list[str]) -> None:
        def done(choice: str | None) -> None:
            if choice:
                self.views[s.name] = choice
                self.reread(s.name)

        self.push_screen(BranchPicker(s.name, names, s.view_branch), done)

    @work(thread=True, group="reread")
    def reread(self, name: str) -> None:
        s = git_ops.read_status(self.repos[name].path, self.views.get(name), name)
        self.call_from_thread(self._store, s)

    def run_bg(self, fn, then) -> None:
        """Run fn in a thread; deliver its result (or the exception) to `then` on the UI thread."""
        def go():
            try:
                res = fn()
            except Exception as e:  # keep UI alive
                res = e
            self.call_from_thread(then, res)
        self.run_worker(go, thread=True, exit_on_error=False)

    # ---- table ----
    def _row(self, s: RepoStatus) -> tuple[tuple, str | None]:
        c = self.colors
        if s.name in self.busy:
            sync, color = "REFRESHING", c["BLUE"]
        elif s.last_date == "-":
            sync, color = "ERROR", "#ff3333"
        elif s.error:
            sync, color = "FAILED", "#ff3333"
        elif s.behind:
            sync, color = f"↓{s.behind}", c["ORANGE"]
        elif s.ahead:
            sync, color = f"↑{s.ahead}", c["LAVENDER"]
        else:
            sync, color = ("OK*" if s.dirty else "OK"), None
        health = " ".join(p for p in (f"M{s.changed}" if s.changed else "", f"?{s.untracked}" if s.untracked else "",
                                      f"S{s.stashes}" if s.stashes else "", f"U{s.unmerged}" if s.unmerged else "") if p)
        tests = "RUNNING" if s.name in self.tests_busy else tests_ops.label(self.test_results.get(str(s.path)))
        vals = (s.name, s.view_branch, s.branch, s.last_date, s.last_rel, s.last_author, sync,
                health or "clean", tests, s.source)
        return tuple(Text(v, style=color) if color else v for v in vals), color

    def _in_homedev(self, s: RepoStatus) -> bool:
        try:
            return s.path.resolve().is_relative_to(HOMEDEV.resolve())
        except OSError:
            return False

    def _visible(self, s: RepoStatus) -> bool:
        return self._in_homedev(s) == (self.scope == "homedev")

    def _build_columns(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        for i, title in enumerate(COLUMNS):
            arrow = (" ▼" if self.sort_desc else " ▲") if i == self.sort_col else ""
            table.add_column(title + arrow, key=str(i))

    def _ordered(self) -> list[RepoStatus]:
        shown = [s for s in self.repos.values() if self._visible(s)]
        if self.sort_col is None:
            return sorted(shown, key=lambda s: s.name.lower())
        key = SORT_KEYS[self.sort_col] or self._test_key
        return sorted(shown, key=lambda s: (key(s), s.name.lower()), reverse=self.sort_desc)

    def _test_key(self, s: RepoStatus):
        r = self.test_results.get(str(s.path))
        return (r is not None, r is not None and r.get("rc") not in (0, None), r["when"] if r else "")

    def _rebuild(self) -> None:
        """Redraw the whole table (scope, sort or theme change), keeping the selection."""
        table = self.query_one("#table", DataTable)
        cur = self._selected()
        self._rebuilding = True
        self._build_columns()
        rows = self._ordered()
        for s in rows:
            table.add_row(*self._row(s)[0], key=s.name)
        if cur and cur.name in table.rows:
            table.move_cursor(row=table.get_row_index(cur.name))
        self._rebuilding = False
        sel = self._selected()
        if sel:
            self.show_detail(sel)
        else:
            self._clear_detail()

    def _clear_detail(self) -> None:
        self.query_one("#detail-title", Static).update("SUMMARY")
        self.query_one("#detail", VerticalScroll).remove_children()

    def _set_scope(self) -> None:
        home = self.scope == "homedev"
        self.query_one("#list-title", Static).update("HOMEDEV  //  ~/HomeDev" if home else "SOFTWAREDEVELOPMENT")
        self._rebuild()
        n = self.query_one("#table", DataTable).row_count
        self.say(f"{n} repositories in " + ("~/HomeDev" if home else "SoftwareDevelopment"))

    def _render_row(self, s: RepoStatus) -> None:
        table = self.query_one("#table", DataTable)
        if not self._visible(s):
            if s.name in table.rows:
                table.remove_row(s.name)
            return
        cells = self._row(s)[0]
        if s.name in table.rows:
            for col, val in zip(table.columns.keys(), cells):
                table.update_cell(s.name, col, val)
        else:
            table.add_row(*cells, key=s.name)

    def _selected(self) -> RepoStatus | None:
        table = self.query_one("#table", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self.repos.get(key)

    def selected(self) -> RepoStatus | None:
        return self._selected()

    def on_data_table_header_selected(self, e: DataTable.HeaderSelected) -> None:
        if e.data_table.id == "table":
            e.stop()
            self._sort_by(e.column_index)

    def action_cycle_sort(self) -> None:
        self._sort_by(0 if self.sort_col is None else (self.sort_col + 1) % len(COLUMNS), keep_dir=True)

    def _sort_by(self, col: int, keep_dir: bool = False) -> None:
        if self.sort_col == col and not keep_dir:
            self.sort_desc = not self.sort_desc
        elif self.sort_col != col:
            self.sort_col, self.sort_desc = col, col in NEWEST_FIRST
        self._rebuild()
        self.say(f"Sorted by {COLUMNS[col]} {'descending' if self.sort_desc else 'ascending'}")

    # ---- loading ----
    @work(thread=True, exclusive=True, group="load")
    def load_all(self) -> None:
        found = git_ops.discover_all(self.roots)
        where = ", ".join(str(r) for r in self.roots)
        if not found:
            self.call_from_thread(self.say, f"No repositories found in {where}")
            return
        done = [0]

        def one(item):
            p, n = item
            self.call_from_thread(self._store, git_ops.read_status(p, self.views.get(n), n))
            done[0] += 1
            self.call_from_thread(self.say, f"Reading repositories... {done[0]}/{len(found)}")
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(one, found))
        self.call_from_thread(self.say, f"{len(found)} repositories tracked in {where}")

    @work(thread=True, group="tests", exit_on_error=False)
    def action_run_tests(self) -> None:
        s = self._selected()
        if not s or s.name in self.tests_busy:
            return
        if not tests_ops.detect(s.path, s.name):
            self.call_from_thread(self.say, f"{s.name}: no test command detected (set test_commands in ~/.lcars_dash.json)")
            return
        name, path = s.name, s.path
        self.tests_busy.add(name)
        self.call_from_thread(self._render_row, s)
        self.call_from_thread(self.say, f"{name}: running tests...")
        try:
            res = tests_ops.run(path, name)
        finally:
            self.tests_busy.discard(name)
        self.test_results[str(path)] = res
        verdict = "not run" if res["rc"] is None else "PASSED" if res["rc"] == 0 else "FAILED"
        self.call_from_thread(self._store, self.repos[name])
        self.call_from_thread(self.say, f"{name}: tests {verdict} ({res['secs']}s)")

    def action_launch(self, what: str) -> None:
        s = self._selected()
        if not s:
            return
        fn = {"vscode": copilot_ops.open_vscode, "explorer": copilot_ops.open_explorer,
              "copilot": copilot_ops.open_copilot}[what]
        try:
            self.say(fn(s.path))
        except OSError as e:
            self.say(f"{s.name}: {e}")

    def _store(self, s: RepoStatus) -> None:
        old = self.repos.get(s.name)
        if old and not s.pulled:
            s.pulled = old.pulled
        self.repos[s.name] = s
        if self.sort_col is not None and self._visible(s):
            self._rebuild()
        else:
            self._render_row(s)
        cur = self._selected()
        if cur and cur.name == s.name:
            self.show_detail(s)

    def action_rescan_status(self) -> None:
        self.load_all()

    # ---- refresh ----
    def action_refresh_selected(self) -> None:
        s = self._selected()
        if s:
            self.refresh_repo(s.name)

    def action_refresh_all(self) -> None:
        for name in list(self.repos):
            self.refresh_repo(name)

    @work(thread=True, group="pull", exit_on_error=False)
    def refresh_repo(self, name: str) -> None:
        if name in self.busy:
            return
        self.busy.add(name)
        self.call_from_thread(self._render_row, self.repos[name])
        try:
            s = git_ops.refresh(self.repos[name].path, self.views.get(name), name)
        finally:
            self.busy.discard(name)
        self.call_from_thread(self._store, s)
        self.call_from_thread(self.say, f"{name}: " + (s.error or f"refreshed, {len(s.pulled)} new commit(s)"))

    # ---- detail ----
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "table" or self._rebuilding:
            return
        event.stop()
        s = self.repos.get(event.row_key.value) if event.row_key is not None else None
        if s:
            self.show_detail(s)

    @work(thread=True, exclusive=True, group="detail")
    def show_detail(self, s: RepoStatus) -> None:
        sections = []
        for title, fn in panels.PANELS:
            try:
                body = fn(s)
            except Exception as e:  # a broken panel must not take down the view
                body = f"[red]panel error: {e}[/]"
            sections.append((title, body))
        self.call_from_thread(self._fill_detail, s.name, sections)

    def _fill_detail(self, name: str, sections) -> None:
        cur = self._selected()
        if not cur or cur.name != name:
            return
        self.query_one("#detail-title", Static).update(f"SUMMARY  //  {name.upper()}")
        box = self.query_one("#detail", VerticalScroll)
        box.remove_children()
        for title, body in sections:
            box.mount(Static(title, classes="panel-title"), Static(self.themed(body), classes="panel-body"))
        box.scroll_home(animate=False)
