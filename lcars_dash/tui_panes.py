"""Terminal, Mindchuk, Sessions and Usage views plus modals for the Textual dashboard."""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, RichLog, Static, TextArea

from . import copilot_ops, live_ops, mindchuk_ops

MARK = "\x01CWD\x01"


def move(app, step) -> None:
    """Vim-style movement in whichever list or scroll pane has focus."""
    w = app.focused
    if isinstance(w, DataTable):
        if not w.row_count:
            return
        row = 0 if step == "top" else w.row_count - 1 if step == "bottom" else w.cursor_row + step
        w.move_cursor(row=min(max(row, 0), w.row_count - 1))
    elif isinstance(w, VerticalScroll):
        if step == "top":
            w.scroll_home(animate=False)
        elif step == "bottom":
            w.scroll_end(animate=False)
        else:
            w.scroll_relative(y=step * 2, animate=False)


class Navigable(Vertical):
    """Shared j/k/g/G/Ctrl+d/Ctrl+u bindings for views made of a list and a text pane."""
    BINDINGS = [
        Binding("j", "move(1)", show=False), Binding("k", "move(-1)", show=False),
        Binding("g", "move('top')", show=False), Binding("G", "move('bottom')", show=False),
        Binding("ctrl+d", "move(10)", show=False), Binding("ctrl+u", "move(-10)", show=False),
        Binding("escape", "app.show_status", "Back"),
    ]

    def action_move(self, step) -> None:
        move(self.app, step)

    def bg(self, fn, done) -> None:
        self.app.run_bg(fn, lambda r: self.say(f"Error: {r}") if isinstance(r, Exception) else done(r))


class ListTextView(Navigable):
    """A table on top and a scrollable text pane below (Mindchuk, Sessions)."""
    PREFIX = ""
    TITLE = ""
    BINDINGS = [Binding("l", "focus_text", show=False), Binding("h", "focus_list", show=False)]

    def compose(self) -> ComposeResult:
        yield Static(self.TITLE, classes="view-title")
        yield DataTable(id=f"{self.PREFIX}-table", classes="lt-table", cursor_type="row")
        yield VerticalScroll(Static("", id=f"{self.PREFIX}-text"), id=f"{self.PREFIX}-scroll", classes="lt-text")
        yield Static("", id=f"{self.PREFIX}-status", classes="view-status")

    @property
    def table(self) -> DataTable:
        return self.query_one(f"#{self.PREFIX}-table", DataTable)

    def say(self, msg: str) -> None:
        self.query_one(f"#{self.PREFIX}-status", Static).update(msg)

    def show_text(self, content) -> None:
        self.query_one(f"#{self.PREFIX}-text", Static).update(content)
        self.query_one(f"#{self.PREFIX}-scroll").scroll_home(animate=False)

    def selected_key(self) -> str | None:
        t = self.table
        if not t.row_count:
            return None
        return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value

    def reselect(self, keep: str | None) -> None:
        t = self.table
        if not t.row_count:
            self.show_text("")
            return
        row = 0
        if keep is not None:
            try:
                row = t.get_row_index(keep)
            except Exception:
                row = 0
        t.move_cursor(row=row)
        self.on_select()

    def on_select(self) -> None:
        raise NotImplementedError

    def on_data_table_row_highlighted(self, e: DataTable.RowHighlighted) -> None:
        if e.data_table.id == f"{self.PREFIX}-table":
            e.stop()
            if e.row_key is not None and e.row_key.value is not None:
                self.on_select()

    def action_focus_text(self) -> None:
        self.query_one(f"#{self.PREFIX}-scroll").focus()

    def action_focus_list(self) -> None:
        self.table.focus()


# ---------------------------------------------------------------- modals

class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("y,enter", "dismiss(True)", "Yes"), Binding("n,escape,q", "dismiss(False)", "No")]

    def __init__(self, title: str, body: str):
        super().__init__()
        self.title_text, self.body = title, body

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog", id="confirm"):
            yield Static(self.title_text, classes="dialog-title")
            yield Static(self.body, classes="dialog-body")
            yield Static("y / Enter = yes     n / Esc = no", classes="dialog-hint")


class EntryEditor(ModalScreen[str | None]):
    """Entry text plus a tags field; tags become inline #hashtags (Mindchuk's tag syntax)."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel"), Binding("ctrl+s", "save", "Save")]

    def __init__(self, title: str, tag_hints: list[str] = (), tags_at_end: bool = False):
        super().__init__()
        self.title_text, self.hints, self.tags_at_end = title, tag_hints, tags_at_end

    def compose(self) -> ComposeResult:
        hints = " ".join(self.hints[:12])
        with Vertical(classes="dialog", id="editor"):
            yield Static(self.title_text.upper(), classes="dialog-title")
            yield TextArea(id="ed-text")
            yield Static("TAGS  (space/comma separated, e.g. quote ideas)" + (f"   Existing: {hints}" if hints else ""),
                         classes="dialog-hint")
            yield Input(id="ed-tags", placeholder="tags")
            yield Static("", id="ed-msg")
            yield Static("Ctrl+S save (or Enter in TAGS)     Esc cancel", classes="dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#ed-text", TextArea).focus()

    def on_input_submitted(self, e: Input.Submitted) -> None:
        e.stop()
        self.action_save()

    def action_save(self) -> None:
        body = self.query_one("#ed-text", TextArea).text.rstrip()
        if not body:
            self.query_one("#ed-msg", Static).update("Entry text is empty")
            return
        raw = self.query_one("#ed-tags", Input).value.strip()
        tags = ["#" + t.lstrip("#") for t in re.split(r"[,\s]+", raw) if t.lstrip("#")]
        if tags:
            line = " ".join(tags)
            body = f"{body}\n\n{line}" if self.tags_at_end else f"{line} {body}"
        self.dismiss(body)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,f4,question_mark", "dismiss(None)", "Close")]

    def __init__(self, sections: list[tuple[str, list[tuple[str, str]]]]):
        super().__init__()
        self.sections = sections

    def compose(self) -> ComposeResult:
        text = Text()
        for heading, rows in self.sections:
            text.append(f" {heading} \n", style="bold reverse")
            for key, desc in rows:
                text.append(f"{key:<22}", style="bold")
                text.append(f"{desc}\n")
            text.append("\n")
        with Vertical(classes="dialog", id="help"):
            yield Static("HELP", classes="dialog-title")
            yield VerticalScroll(Static(text), id="help-scroll")
            yield Static("Esc / q / F4 close", classes="dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#help-scroll").focus()

    def on_key(self, event) -> None:
        if event.key in ("j", "down"):
            move(self.app, 1)
        elif event.key in ("k", "up"):
            move(self.app, -1)


# ---------------------------------------------------------------- terminal

class TerminalView(Vertical):
    """Line-oriented PowerShell session (no full-screen/interactive programs)."""
    START = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;function prompt { '' };"
    BINDINGS = [Binding("up", "recall(-1)", show=False), Binding("down", "recall(1)", show=False),
                Binding("ctrl+l", "clear", "Clear"), Binding("escape", "app.show_status", "Back")]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.proc: subprocess.Popen | None = None
        self.cwd: Path | None = None
        self.history: list[str] = []
        self.hpos = 0
        self.prompt_text = "PS>"

    def compose(self) -> ComposeResult:
        yield Static("TERMINAL  //  WINDOWS POWERSHELL", id="term-title", classes="view-title")
        yield RichLog(id="term-out", wrap=True, markup=False, highlight=False, max_lines=5000)
        with Horizontal(id="term-row"):
            yield Static("PS>", id="term-prompt")
            yield Input(id="term-in")

    @property
    def log_w(self) -> RichLog:
        return self.query_one("#term-out", RichLog)

    def write(self, text: str, style: str = "") -> None:
        self.log_w.write(Text(text.rstrip("\r\n"), style=style))

    def open(self, cwd: Path) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.start(cwd)
        elif cwd != self.cwd:
            self.send(f"Set-Location -LiteralPath '{cwd}'")
            self.cwd = cwd
            self.write(f"[cd] {cwd}", "bold")
        self.update_prompt()
        self.query_one("#term-in", Input).focus()

    def start(self, cwd: Path) -> None:
        self.cwd = cwd
        self.proc = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(cwd), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.write(f"PowerShell session started in {cwd}", "bold")
        self.send(self.START)

    def _reader(self, proc) -> None:
        try:
            for line in proc.stdout:
                self.app.call_from_thread(self._on_line, line)
            self.app.call_from_thread(self.write, "[session ended]", "red")
        except Exception:  # app is shutting down
            pass

    def _on_line(self, line: str) -> None:
        if line.startswith(MARK):
            self.cwd = Path(line[len(MARK):].strip())
            self.update_prompt()
        else:
            self.write(line)

    def send(self, text: str) -> None:
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            self.write("[session not available - press Ctrl+C to restart]", "red")

    def on_input_submitted(self, e: Input.Submitted) -> None:
        e.stop()
        cmd = e.value
        e.input.value = ""
        if not cmd.strip():
            return
        self.history.append(cmd)
        self.hpos = len(self.history)
        self.write(f"{self.prompt_text} {cmd}", "bold")
        if cmd.strip().lower() in ("cls", "clear", "clear-host"):
            self.action_clear()
            return
        if self.proc is None or self.proc.poll() is not None:
            self.start(self.cwd or Path.home())
        self.send(cmd)
        self.send(f"Write-Output ('{MARK}' + (Get-Location).Path)")

    def action_recall(self, d: int) -> None:
        if not self.history:
            return
        self.hpos = min(max(self.hpos + d, 0), len(self.history))
        inp = self.query_one("#term-in", Input)
        inp.value = self.history[self.hpos] if self.hpos < len(self.history) else ""
        inp.cursor_position = len(inp.value)

    def action_clear(self) -> None:
        self.log_w.clear()

    def restart(self) -> None:
        self.shutdown()
        self.write("^C - session restarted", "red")
        self.start(self.cwd or Path.home())
        self.update_prompt()

    def update_prompt(self) -> None:
        name = self.cwd.name if self.cwd else ""
        self.prompt_text = f"PS {name}>"
        self.query_one("#term-prompt", Static).update(self.prompt_text)
        self.query_one("#term-title", Static).update(f"TERMINAL  //  WINDOWS POWERSHELL  //  {self.cwd}")

    def shutdown(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


# ---------------------------------------------------------------- mindchuk

class MindchukView(ListTextView):
    PREFIX = "mc"
    TITLE = "MINDCHUK  //  KNOWLEDGE BASE ENTRIES"
    BINDINGS = [Binding("n", "new", "New"), Binding("e", "append", "Append"),
                Binding("x", "archive(False)", "Archive"), Binding("u", "archive(True)", "Unarchive", show=False),
                Binding("d", "delete", "Delete"), Binding("v", "toggle_all", "+/-Archived"),
                Binding("r", "reload", "Reload")]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.loaded, self.show_all, self.cache, self.token = False, False, {}, 0

    def on_mount(self) -> None:
        self.table.add_columns("ID", "FIRST LINE")

    def open(self) -> None:
        self.table.focus()
        if not self.loaded:
            self.action_reload()

    def action_reload(self) -> None:
        self.say("Loading entries...")
        keep = self.selected_key()

        def done(rows):
            self.loaded = True
            t = self.table
            t.clear()
            for eid, title in rows:
                t.add_row(eid[:8], title or "(blank first line)", key=eid)
            self.reselect(keep)
            self.say(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
                     f"{' (including archived)' if self.show_all else ''}")
        self.bg(lambda: mindchuk_ops.list_entries(50, self.show_all), done)

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.action_reload()

    def on_select(self) -> None:
        eid = self.selected_key()
        if not eid:
            return
        self.token += 1
        token = self.token
        if eid in self.cache:
            self.show_text(self.cache[eid])
            return
        self.show_text("Loading...")

        def done(text):
            self.cache[eid] = text
            if token == self.token:
                self.show_text(text)
        self.bg(lambda: mindchuk_ops.show(eid), done)

    def known_tags(self) -> list[str]:
        seen: dict[str, None] = {}
        t = self.table
        for r in range(t.row_count):
            for tag in re.findall(r"#\w+", str(t.get_row_at(r)[1])):
                seen[tag] = None
        return list(seen)

    def action_new(self) -> None:
        def save(body):
            if body is None:
                return
            self.say("Adding entry...")
            self.bg(lambda: mindchuk_ops.add(body), lambda eid: (self.say(f"Added {eid[:8]}"), self.action_reload()))
        self.app.push_screen(EntryEditor("New Mindchuk entry", self.known_tags()), save)

    def action_append(self) -> None:
        eid = self.selected_key()
        if not eid:
            return

        def save(body):
            if body is None:
                return
            self.say("Appending...")

            def done(_):
                self.cache.pop(eid, None)
                self.say(f"Appended to {eid[:8]}")
                self.on_select()
            self.bg(lambda: mindchuk_ops.append(eid, body), done)
        self.app.push_screen(EntryEditor(f"Append to {eid[:8]}", self.known_tags(), tags_at_end=True), save)

    def action_archive(self, undo: bool) -> None:
        eid = self.selected_key()
        if eid:
            self.bg(lambda: mindchuk_ops.archive(eid, undo),
                    lambda _: (self.say(f"{'Unarchived' if undo else 'Archived'} {eid[:8]}"), self.action_reload()))

    def action_delete(self) -> None:
        eid = self.selected_key()
        if not eid:
            return

        def confirmed(yes):
            if yes:
                self.bg(lambda: mindchuk_ops.delete(eid),
                        lambda _: (self.cache.pop(eid, None), self.say(f"Deleted {eid[:8]}"), self.action_reload()))
        self.app.push_screen(ConfirmScreen("DELETE ENTRY", f"Permanently delete entry {eid[:8]}?\nThis cannot be undone."),
                             confirmed)


# ---------------------------------------------------------------- sessions

class SessionsView(ListTextView):
    PREFIX = "ss"
    TITLE = "COPILOT SESSIONS  //  HISTORY"
    BINDINGS = [Binding("enter", "resume", "Resume"), Binding("p", "new_here", "New Copilot"),
                Binding("r", "reload", "Reload"),
                Binding("a", "toggle_scope", "All/This repo")]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.repo_only, self.rows, self.token = False, {}, 0

    def on_mount(self) -> None:
        self.table.add_columns("UPDATED", "TURNS", "FOLDER", "SUMMARY")

    def open(self) -> None:
        self.table.focus()
        self.action_reload()

    def selected(self) -> dict | None:
        k = self.selected_key()
        return self.rows.get(k) if k else None

    def action_toggle_scope(self) -> None:
        self.repo_only = not self.repo_only
        self.action_reload()

    def action_reload(self) -> None:
        repo = self.app.selected() if self.repo_only else None
        under = repo.path if repo else None
        keep = self.selected_key()
        self.say("Loading sessions...")

        def done(rows):
            self.rows = {r["id"]: r for r in rows}
            t = self.table
            t.clear()
            for r in rows:
                t.add_row(copilot_ops.local_ts(r["updated"]), str(r["turns"]), Path(r["cwd"] or "?").name,
                          r["summary"] or "(no summary)", key=r["id"])
            self.reselect(keep)
            self.say(f"{len(rows)} session(s)" + (f" in {repo.name}" if repo else "")
                     + "  -  Enter resumes in a new window")
        self.bg(lambda: copilot_ops.sessions(300, under), done)

    def on_select(self) -> None:
        s = self.selected()
        if not s:
            return
        self.token += 1
        token = self.token

        def done(d):
            if token != self.token:
                return
            t = Text()

            def put(title, lines):
                t.append(f" {title} \n", style="bold reverse")
                t.append(("\n".join(lines) + "\n\n") if lines else "none\n\n")
            put("SESSION", [f"Folder:   {s['cwd']}", f"Repo:     {s['repository'] or '-'}   Branch: {s['branch'] or '-'}",
                            f"Created:  {copilot_ops.local_ts(s['created'])}   Updated: {copilot_ops.local_ts(s['updated'])}",
                            f"Resume:   copilot --resume {s['id']}"])
            put("CHECKPOINTS", [f"{n}. {x}" for n, x in d["checkpoints"]])
            put("LAST PROMPTS", [f"[{i}] {(m or '').strip()[:300]}" for i, m in d["turns"]])
            put("FILES TOUCHED", d["files"])
            put("REFERENCES", [f"{k}: {v}" for k, v in d["refs"]])
            self.show_text(t)
        self.bg(lambda: copilot_ops.detail(s["id"]), done)

    def on_data_table_row_selected(self, e: DataTable.RowSelected) -> None:
        if e.data_table.id == "ss-table":
            e.stop()
            self.action_resume()

    def action_resume(self) -> None:
        s = self.selected()
        if s:
            self.say(copilot_ops.open_copilot(Path(s["cwd"] or Path.home()), resume=s["id"]))

    def action_new_here(self) -> None:
        s = self.selected()
        self.say(copilot_ops.open_copilot(Path(s["cwd"]) if s and s["cwd"] else Path.home()))

# ---------------------------------------------------------------- monitor

class MonitorView(Navigable):
    """Sparkline per running Copilot CLI session (events per 10 s over the last 10 minutes)."""
    BINDINGS = [Binding("r", "refresh_now", "Refresh")]
    STATE_COLOR = {"RUNNING": "BLUE", "WAITING FOR INPUT": "ORANGE", "IDLE": "LAVENDER", "ERROR": "RED"}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows: list[dict] = []
        self.loading = False
        self.timer = None

    def compose(self) -> ComposeResult:
        yield Static("COPILOT MONITOR  //  RUNNING SESSIONS  //  LAST 10 MIN, 10 S PER BAR", classes="view-title")
        yield DataTable(id="mon-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="mon-status", classes="view-status")

    def on_mount(self) -> None:
        t = self.query_one("#mon-table", DataTable)
        for label in ("", "STATE", "SESSION", "FOLDER", "ACTIVITY (OLD → NOW)", "LAST", "EVENTS", "PID"):
            t.add_column(label)

    def say(self, msg: str) -> None:
        self.query_one("#mon-status", Static).update(msg)

    def open(self) -> None:
        self.query_one("#mon-table").focus()
        if self.timer is None:
            self.timer = self.set_interval(1, self._auto)
        self.action_refresh_now()

    def _auto(self) -> None:
        if self.app.current_view == "monitor":
            self.action_refresh_now()

    def action_refresh_now(self) -> None:
        if self.loading:
            return
        self.loading = True

        def done(rows):
            self.loading = False
            self.rows = rows
            self.render_rows()
        self.app.run_bg(live_ops.snapshot, lambda r: done(r) if not isinstance(r, Exception) else self._fail(r))

    def _fail(self, e) -> None:
        self.loading = False
        self.say(f"Error: {e}")

    def render_rows(self) -> None:
        c = self.app.colors
        t = self.query_one("#mon-table", DataTable)
        keep = t.cursor_row
        t.clear()
        for r in self.rows:
            col = c[self.STATE_COLOR.get(r["state"], "LAVENDER")]
            state = r["state"] + (f" {r['detail']}" if r["detail"] and r["state"] != "IDLE" else "")
            t.add_row(Text(live_ops.ICONS.get(r["state"], "?"), style=col), Text(state[:30], style=col),
                      r["name"][:34], r["folder"][:22],
                      Text(live_ops.sparkline(r["counts"]), style=col),
                      live_ops.age_label(r["age"]), str(r["total"]), str(r["pid"]))
        if self.rows:
            t.move_cursor(row=min(keep, len(self.rows) - 1))
        n = sum(r["state"] == "RUNNING" for r in self.rows)
        self.say(f"{len(self.rows)} session(s), {n} running  //  refreshes every 1 s  //  r: refresh")


# ---------------------------------------------------------------- usage

class UsageView(Navigable):
    PERIODS = (7, 30, 90)
    BINDINGS = [Binding("r", "reload", "Reload"), Binding("d", "cycle", "Period")]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.days, self.data = 30, None

    def compose(self) -> ComposeResult:
        yield Static("", id="us-title", classes="view-title")
        yield VerticalScroll(Static("", id="us-text"), id="us-scroll", classes="lt-text")
        yield Static("", id="us-status", classes="view-status")

    def on_mount(self) -> None:
        self._label()

    def say(self, msg: str) -> None:
        self.query_one("#us-status", Static).update(msg)

    def _label(self) -> None:
        self.query_one("#us-title", Static).update(f"COPILOT USAGE  //  AUDIT  //  PERIOD: {self.days} DAYS [D]")

    def open(self) -> None:
        self.query_one("#us-scroll").focus()
        self.action_reload()

    def action_cycle(self) -> None:
        self.days = self.PERIODS[(self.PERIODS.index(self.days) + 1) % len(self.PERIODS)]
        self._label()
        self.action_reload()

    def action_reload(self) -> None:
        self.say("Loading usage...")
        days = self.days

        def done(u):
            self.data = u
            self.render_usage()
            self.say(f"Last {days} days from ~/.copilot/session-store.db")
        self.bg(lambda: copilot_ops.usage(days), done)

    def render_usage(self) -> None:
        u = self.data
        if not u:
            return
        c = self.app.colors
        t = Text()
        head, dim, bar_style = "bold reverse", c["LAVENDER"], c["PERIWINKLE"]

        def bar(v, mx, width=34):
            return "█" * max(1 if v else 0, round(width * v / mx)) if mx else ""
        calls = sum(r[2] for r in u["per_day"])
        toks = sum(r[3] + r[4] for r in u["per_day"])
        reqs = sum(r[5] for r in u["per_day"])
        t.append(" SUMMARY \n", style=head)
        t.append(f"Sessions started: {u['sessions']}   Model calls: {calls:,}   "
                 f"Tokens: {toks / 1e6:,.1f}M   Premium requests (multiplier sum): {reqs:,.0f}\n\n")
        t.append(" PER DAY (MODEL CALLS) \n", style=head)
        mx = max((r[2] for r in u["per_day"]), default=0)
        t.append(f"{'DATE':<11}{'SESS':>5}{'CALLS':>8}{'TOKENS':>10}  \n", style=dim)
        for d, ns, n, i, o, _m in u["per_day"]:
            t.append(f"{d:<11}{ns:>5}{n:>8,}{(i + o) / 1e6:>9.1f}M  ")
            t.append(bar(n, mx) + "\n", style=bar_style)
        t.append("\n BY MODEL \n", style=head)
        t.append(f"{'MODEL':<26}{'SESS':>5}{'CALLS':>8}{'TOKENS':>10}{'REQS':>9}\n", style=dim)
        for m, ns, n, i, o, r in u["per_model"]:
            t.append(f"{(m or '?')[:25]:<26}{ns:>5}{n:>8,}{(i + o) / 1e6:>9.1f}M{r:>9,.0f}\n")
        t.append("\n BY FOLDER / REPO (TOP 15) \n", style=head)
        t.append(f"{'FOLDER':<34}{'SESS':>5}{'CALLS':>8}\n", style=dim)
        folders = u["per_folder"][:15]
        mx = max((r[2] for r in folders), default=0)
        for name, ns, n, _tok in folders:
            t.append(f"{name[:33]:<34}{ns:>5}{n:>8,}  ")
            t.append(bar(n, mx, 28) + "\n", style=bar_style)
        self.query_one("#us-text", Static).update(t)
        self.query_one("#us-scroll").scroll_home(animate=False)
