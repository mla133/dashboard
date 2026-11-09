"""Windows desktop (Tkinter) front-end: same data/panels as the TUI, LCARS styled."""
from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from rich.style import Style
from rich.text import Text

from . import config, copilot_ops, git_ops, live_ops, mindchuk_ops, panels, tests_ops
from .git_ops import RepoStatus
from .themes import DEFAULT_THEME, THEMES

theme_name = DEFAULT_THEME
BLACK = ORANGE = PEACH = LAVENDER = BLUE = PERIWINKLE = RED = TEXT = ""


def set_theme(name: str) -> None:
    global theme_name, BLACK, ORANGE, PEACH, LAVENDER, BLUE, PERIWINKLE, RED, TEXT
    t = THEMES[name]
    theme_name = name
    BLACK, ORANGE, PEACH, LAVENDER = t["BLACK"], t["ORANGE"], t["PEACH"], t["LAVENDER"]
    BLUE, PERIWINKLE, RED = t["BLUE"], t["PERIWINKLE"], t["RED"]
    TEXT = PEACH


def recolor_map(old: str, new: str):
    """Function mapping a hex colour from theme `old` to the same role in theme `new`."""
    rev = {v.lower(): k for k, v in THEMES[old].items()}

    def m(c):
        role = rev.get(str(c).lower())
        return THEMES[new][role] if role else c
    return m


def themed(hex_color: str) -> str:
    """Map a colour from the default theme (used by panels.py markup) to the active theme."""
    return recolor_map(DEFAULT_THEME, theme_name)(hex_color)


def load_saved_theme() -> str:
    name = config.load().get("theme")
    return name if name in THEMES else DEFAULT_THEME


set_theme(DEFAULT_THEME)
LABEL_FONT = ("Bahnschrift SemiBold", 14)
MARK = "\x01CWD\x01"
BODY_FONT = ("Consolas", 13)
HOMEDEV = Path.home() / "HomeDev"
COLUMNS = (("repo", "REPOSITORY", 250), ("view", "VIEWING", 170), ("co", "CHECKED OUT", 140),
           ("date", "LAST UPDATED", 160), ("age", "AGE", 100), ("by", "BY", 120), ("sync", "SYNC", 80),
           ("health", "HEALTH", 130), ("tests", "TESTS", 90), ("src", "SOURCE", 100))


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class Pill(tk.Canvas):
    """Filled rounded label/button."""

    def __init__(self, parent, text="", color=ORANGE, command=None, anchor="w", **kw):
        super().__init__(parent, bg=BLACK, highlightthickness=0, **kw)
        self.color, self.text, self.command, self.anchor = color, text, command, anchor
        self.bind("<Configure>", lambda e: self.draw())
        if command:
            self.configure(cursor="hand2")
            self.bind("<Button-1>", lambda e: command())

    def set(self, text: str) -> None:
        self.text = text
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        round_rect(self, 1, 1, w - 1, h - 1, min(18, h // 2), fill=self.color, outline=self.color)
        x = 14 if self.anchor == "w" else w - 14
        self.create_text(x, h // 2, text=self.text, fill=BLACK, font=LABEL_FONT,
                         anchor=self.anchor, justify="left")


class RoundFrame(tk.Canvas):
    """Rounded outline around a child widget; outline turns orange when focus is inside."""

    def __init__(self, parent, color=PERIWINKLE, **kw):
        super().__init__(parent, bg=BLACK, highlightthickness=0, **kw)
        self.color, self.active, self.child, self._win = color, False, None, None
        self.bind("<Configure>", lambda e: self.draw())

    def set_child(self, widget) -> None:
        self.child = widget
        self._win = self.create_window(10, 10, window=widget, anchor="nw")
        self.draw()

    def highlight(self, on: bool) -> None:
        self.active = on
        self.draw()

    def draw(self) -> None:
        self.delete("border")
        w, h = self.winfo_width(), self.winfo_height()
        round_rect(self, 2, 2, w - 2, h - 2, 18, fill="", outline=ORANGE if self.active else self.color,
                   width=3, tags="border")
        if self._win:
            self.tag_lower("border")
            self.coords(self._win, 10, 10)
            self.itemconfigure(self._win, width=max(w - 20, 1), height=max(h - 20, 1))


class BranchPicker(tk.Toplevel):
    def __init__(self, app: "Dashboard", repo: str, names: list[str], current: str):
        super().__init__(app, bg=BLACK)
        self.title(f"Select branch - {repo}")
        self.geometry("560x600")
        self.transient(app)
        self.callback = app.set_branch
        self.repo = repo
        self.names = names
        tk.Label(self, text=f"SELECT BRANCH  //  {repo.upper()}", bg=ORANGE, fg=BLACK,
                 font=LABEL_FONT, anchor="w", padx=10).pack(fill="x", padx=10, pady=10)
        self.lb = tk.Listbox(self, bg=BLACK, fg=TEXT, font=BODY_FONT, selectbackground=ORANGE,
                             selectforeground=BLACK, activestyle="none", highlightthickness=2,
                             highlightbackground=LAVENDER, highlightcolor=ORANGE, bd=0)
        self.lb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for n in names:
            self.lb.insert("end", ("● " if n == current else "  ") + n)
        idx = names.index(current) if current in names else 0
        self._select(idx)
        self.lb.focus_set()
        self.lb.bind("<Double-Button-1>", lambda e: self.choose())
        for key, fn in (("<Return>", self.choose), ("l", self.choose), ("<Escape>", self.destroy),
                        ("h", self.destroy), ("q", self.destroy),
                        ("j", lambda: self.move(1)), ("k", lambda: self.move(-1)),
                        ("g", lambda: self._select(0)), ("G", lambda: self._select(len(names) - 1))):
            self.lb.bind(key, lambda e, f=fn: (f(), "break")[1])
        self.grab_set()

    def move(self, d: int) -> None:
        cur = self.lb.curselection()
        self._select(min(max((cur[0] if cur else 0) + d, 0), len(self.names) - 1))

    def _select(self, i: int) -> None:
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(i)
        self.lb.activate(i)
        self.lb.see(i)

    def choose(self) -> None:
        cur = self.lb.curselection()
        if cur:
            self.callback(self.repo, self.names[cur[0]])
        self.destroy()


class TerminalPane(tk.Frame):
    """Line-oriented PowerShell session (no full-screen/interactive programs)."""

    START = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
             "function prompt { '' };")

    def __init__(self, parent, app: "Dashboard"):
        super().__init__(parent, bg=BLACK)
        self.app, self.proc, self.cwd, self.history, self.hpos = app, None, None, [], 0
        self.title = tk.Label(self, text="TERMINAL  //  WINDOWS POWERSHELL", bg=BLACK, fg=ORANGE,
                              font=LABEL_FONT, anchor="w")
        self.title.pack(fill="x")
        self.frame = RoundFrame(self, ORANGE, height=300)
        self.frame.pack(fill="both", expand=True)
        holder = tk.Frame(self.frame, bg=BLACK)
        self.out = tk.Text(holder, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="char", bd=0,
                           highlightthickness=0, state="disabled", cursor="arrow")
        sb = ttk.Scrollbar(holder, command=self.out.yview)
        self.out.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True)
        self.frame.set_child(holder)
        self.frame.highlight(True)
        self.out.tag_configure("cmd", foreground=ORANGE, font=(BODY_FONT[0], BODY_FONT[1], "bold"))
        self.out.tag_configure("err", foreground="#ff6666")
        row = tk.Frame(self, bg=BLACK)
        row.pack(fill="x", pady=(8, 0))
        self.prompt = tk.Label(row, text="PS>", bg=ORANGE, fg=BLACK, font=LABEL_FONT, padx=10)
        self.prompt.pack(side="left")
        self.entry = tk.Entry(row, bg=BLACK, fg=TEXT, font=BODY_FONT, insertbackground=ORANGE,
                              bd=0, highlightthickness=2, highlightbackground=LAVENDER,
                              highlightcolor=ORANGE, relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(8, 0))
        self.entry.bind("<Return>", lambda e: self.submit())
        self.entry.bind("<Up>", lambda e: self.recall(-1))
        self.entry.bind("<Down>", lambda e: self.recall(1))
        self.entry.bind("<Control-c>", self.interrupt)
        self.entry.bind("<Control-l>", lambda e: self.clear())
        self.entry.bind("<Escape>", lambda e: app.show_status())
        self.out.bind("<Button-1>", lambda e: self.entry.focus_set())

    def open(self, cwd: Path) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.start(cwd)
        elif cwd != self.cwd:
            self.send(f"Set-Location -LiteralPath '{cwd}'")
            self.cwd = cwd
            self.write(f"[cd] {cwd}\n", "cmd")
        self.update_prompt()
        self.entry.focus_set()

    def start(self, cwd: Path) -> None:
        self.cwd = cwd
        self.proc = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(cwd), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.write(f"PowerShell session started in {cwd}\n", "cmd")
        self.send(self.START)

    def _reader(self, proc) -> None:
        for line in proc.stdout:
            self.app.q.put((self._on_line, line))
        self.app.q.put((lambda _: self.write("[session ended]\n", "err"), None))

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
        except (OSError, ValueError):
            self.write("[session not available - press Ctrl+C to restart]\n", "err")

    def submit(self) -> None:
        cmd = self.entry.get()
        self.entry.delete(0, "end")
        if not cmd.strip():
            return
        self.history.append(cmd)
        self.hpos = len(self.history)
        self.write(f"{self.prompt.cget('text')} {cmd}\n", "cmd")
        if cmd.strip().lower() in ("cls", "clear", "clear-host"):
            self.clear()
            return
        if self.proc is None or self.proc.poll() is not None:
            self.start(self.cwd or Path.home())
        self.send(cmd)
        self.send(f"Write-Output ('{MARK}' + (Get-Location).Path)")

    def recall(self, d: int) -> None:
        if not self.history:
            return
        self.hpos = min(max(self.hpos + d, 0), len(self.history))
        self.entry.delete(0, "end")
        if self.hpos < len(self.history):
            self.entry.insert(0, self.history[self.hpos])

    def interrupt(self, _e=None):
        if self.entry.selection_present():
            return None  # normal copy
        self.shutdown()
        self.write("^C - session restarted\n", "err")
        self.start(self.cwd or Path.home())
        self.update_prompt()
        return "break"

    def clear(self) -> None:
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.configure(state="disabled")

    def write(self, text: str, tag: str = "") -> None:
        self.out.configure(state="normal")
        self.out.insert("end", text, tag)
        self.out.configure(state="disabled")
        self.out.see("end")

    def update_prompt(self) -> None:
        name = self.cwd.name if self.cwd else ""
        self.prompt.configure(text=f"PS {name}>")
        self.title.configure(text=f"TERMINAL  //  WINDOWS POWERSHELL  //  {self.cwd}")

    def shutdown(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


class EntryEditor(tk.Toplevel):
    """Modal editor with a tags field. Tags become inline #hashtags (Mindchuk's tag syntax)."""

    def __init__(self, app, title: str, on_save, tag_hints: list[str] = (), tags_at_end: bool = False):
        super().__init__(app, bg=BLACK)
        self.title(title)
        self.geometry("820x600")
        self.transient(app)
        self.on_save, self.tags_at_end = on_save, tags_at_end
        tk.Label(self, text=title.upper(), bg=ORANGE, fg=BLACK, font=LABEL_FONT, anchor="w",
                 padx=10).pack(fill="x", padx=10, pady=10)
        bar = tk.Frame(self, bg=BLACK, height=52)
        bar.pack(side="bottom", fill="x", padx=10, pady=10)
        bar.pack_propagate(False)
        Pill(bar, "SAVE  [Ctrl+Enter]", ORANGE, self.save, width=280).pack(side="left", fill="y")
        Pill(bar, "CANCEL  [Esc]", RED, self.destroy, width=220).pack(side="left", fill="y", padx=8)
        self.msg = tk.Label(bar, text="", bg=BLACK, fg="#ff6666", font=BODY_FONT)
        self.msg.pack(side="left", padx=8)
        row = tk.Frame(self, bg=BLACK)
        row.pack(side="bottom", fill="x", padx=10)
        tk.Label(row, text="TAGS", bg=LAVENDER, fg=BLACK, font=LABEL_FONT, padx=10).pack(side="left")
        self.tags = tk.Entry(row, bg=BLACK, fg=TEXT, font=BODY_FONT, insertbackground=ORANGE, bd=0,
                             highlightthickness=2, highlightbackground=LAVENDER, highlightcolor=ORANGE)
        self.tags.pack(side="left", fill="x", expand=True, ipady=5, padx=(8, 0))
        hints = " ".join(tag_hints[:12])
        tk.Label(self, text=f"space/comma separated, e.g. quote ideas.  Existing: {hints}" if hints
                 else "space/comma separated, e.g. quote ideas", bg=BLACK, fg=BLUE, font=("Consolas", 10),
                 anchor="w", wraplength=780, justify="left").pack(side="bottom", fill="x", padx=10)
        self.text = tk.Text(self, bg=BLACK, fg=TEXT, font=BODY_FONT, insertbackground=ORANGE, wrap="word",
                            height=5, highlightthickness=2, highlightbackground=LAVENDER,
                            highlightcolor=ORANGE, bd=0)
        self.text.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        for w in (self.text, self.tags):
            w.bind("<Control-Return>", lambda e: (self.save(), "break")[1])
        self.tags.bind("<Return>", lambda e: (self.save(), "break")[1])
        self.bind("<Escape>", lambda e: self.destroy())
        self.text.focus_set()
        self.grab_set()

    def save(self) -> None:
        body = self.text.get("1.0", "end").rstrip()
        if not body:
            self.msg.configure(text="Entry text is empty")
            return
        tags = ["#" + t.lstrip("#") for t in re.split(r"[,\s]+", self.tags.get().strip()) if t.lstrip("#")]
        if tags:
            line = " ".join(tags)
            body = f"{body}\n\n{line}" if self.tags_at_end else f"{line} {body}"
        self.on_save(body)
        self.destroy()


class MindchukPane(tk.Frame):
    """Browse, read, add to and curate Mindchuk entries through the mindchuk CLI."""

    def __init__(self, parent, app: "Dashboard"):
        super().__init__(parent, bg=BLACK)
        self.app, self.loaded, self.show_all, self.cache, self.token = app, False, False, {}, 0
        tk.Label(self, text="MINDCHUK  //  KNOWLEDGE BASE ENTRIES", bg=BLACK, fg=ORANGE,
                 font=LABEL_FONT, anchor="w").pack(fill="x")
        bar = tk.Frame(self, bg=BLACK, height=48)
        bar.pack(fill="x", pady=(0, 6))
        bar.pack_propagate(False)
        for text, color, cmd in (("NEW [N]", ORANGE, self.new), ("APPEND [E]", PEACH, self.append),
                                 ("ARCHIVE [X]", LAVENDER, lambda: self.archive(False)),
                                 ("UNARCHIVE [U]", PERIWINKLE, lambda: self.archive(True)),
                                 ("DELETE [D]", RED, self.delete), ("RELOAD [R]", BLUE, self.reload),
                                 ("+ARCHIVED [V]", PEACH, self.toggle_all)):
            p = Pill(bar, text, color, cmd, width=10)
            p.pack(side="left", fill="both", expand=True, padx=(0, 6))
            if "ARCHIVED" in text:
                self.all_pill = p
        self.list_frame = RoundFrame(self, PERIWINKLE, height=240)
        self.list_frame.pack(fill="both", expand=True)
        holder = tk.Frame(self.list_frame, bg=BLACK)
        self.tree = ttk.Treeview(holder, columns=("id", "title"), show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.heading("title", text="FIRST LINE")
        self.tree.column("id", width=90, stretch=False)
        self.tree.column("title", width=900)
        sb = ttk.Scrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.list_frame.set_child(holder)
        self.text_frame = RoundFrame(self, LAVENDER, height=300)
        self.text_frame.pack(fill="both", expand=True, pady=(8, 0))
        th = tk.Frame(self.text_frame, bg=BLACK)
        self.view = tk.Text(th, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="word", bd=0, highlightthickness=0,
                            state="disabled", cursor="arrow")
        tsb = ttk.Scrollbar(th, command=self.view.yview)
        self.view.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True)
        self.text_frame.set_child(th)
        self.status = tk.Label(self, text="", bg=BLACK, fg=BLUE, font=BODY_FONT, anchor="w")
        self.status.pack(fill="x")

        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<FocusIn>", lambda e: (self.list_frame.highlight(True), self.text_frame.highlight(False)))
        self.view.bind("<FocusIn>", lambda e: (self.list_frame.highlight(False), self.text_frame.highlight(True)))
        self.view.bind("<Button-1>", lambda e: self.view.focus_set())
        for k, fn in (("n", self.new), ("e", self.append), ("x", lambda: self.archive(False)),
                      ("u", lambda: self.archive(True)), ("d", self.delete), ("r", self.reload),
                      ("v", self.toggle_all), ("j", lambda: self.move(1)), ("k", lambda: self.move(-1)),
                      ("g", lambda: self.move("top")), ("G", lambda: self.move("bottom")),
                      ("l", lambda: self.view.focus_set()), ("h", lambda: self.tree.focus_set()),
                      ("<Escape>", app.show_status)):
            for w in (self.tree, self.view):
                w.bind(k if k.startswith("<") else f"<Key-{k}>", lambda e, f=fn: (f(), "break")[1])

    # ---- helpers ----
    def say(self, msg: str) -> None:
        self.status.configure(text=msg)

    def selected_id(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def bg(self, fn, done) -> None:
        self.app.run_bg(fn, lambda r: self.say(f"Error: {r}") if isinstance(r, Exception) else done(r))

    def move(self, step) -> None:
        if self.focus_get() is self.view:
            self.view.yview_moveto(0 if step == "top" else 1) if isinstance(step, str) else \
                self.view.yview_scroll(step * 2, "units")
            return
        rows = self.tree.get_children()
        if not rows:
            return
        cur = self.tree.selection()
        i = rows.index(cur[0]) if cur else 0
        i = 0 if step == "top" else len(rows) - 1 if step == "bottom" else min(max(i + step, 0), len(rows) - 1)
        self.tree.selection_set(rows[i])
        self.tree.see(rows[i])

    # ---- actions ----
    def open(self) -> None:
        self.tree.focus_set()
        if not self.loaded:
            self.reload()

    def reload(self) -> None:
        self.say("Loading entries...")
        keep = self.selected_id()

        def done(rows):
            self.loaded = True
            self.tree.delete(*self.tree.get_children())
            for eid, title in rows:
                self.tree.insert("", "end", iid=eid, values=(eid[:8], title or "(blank first line)"))
            kids = self.tree.get_children()
            if kids:
                pick = keep if keep in kids else kids[0]
                self.tree.selection_set(pick)
                self.tree.see(pick)
            self.say(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
                     f"{' (including archived)' if self.show_all else ''}")
        self.bg(lambda: mindchuk_ops.list_entries(50, self.show_all), done)

    def toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.all_pill.set("-ARCHIVED [V]" if self.show_all else "+ARCHIVED [V]")
        self.reload()

    def on_select(self) -> None:
        eid = self.selected_id()
        if not eid:
            return
        self.token += 1
        token = self.token
        if eid in self.cache:
            self._show_text(self.cache[eid])
            return
        self._show_text("Loading...")

        def done(text):
            self.cache[eid] = text
            if token == self.token:
                self._show_text(text)
        self.bg(lambda: mindchuk_ops.show(eid), done)

    def _show_text(self, text: str) -> None:
        self.view.configure(state="normal")
        self.view.delete("1.0", "end")
        self.view.insert("end", text)
        self.view.configure(state="disabled")

    def new(self) -> None:
        def save(body):
            self.say("Adding entry...")
            self.bg(lambda: mindchuk_ops.add(body), lambda eid: (self.say(f"Added {eid[:8]}"), self.reload()))
        EntryEditor(self.app, "New Mindchuk entry", save, self.known_tags())

    def append(self) -> None:
        eid = self.selected_id()
        if not eid:
            return

        def save(body):
            self.say("Appending...")

            def done(_):
                self.cache.pop(eid, None)
                self.say(f"Appended to {eid[:8]}")
                self.on_select()
            self.bg(lambda: mindchuk_ops.append(eid, body), done)
        EntryEditor(self.app, f"Append to {eid[:8]}", save, self.known_tags(), tags_at_end=True)

    def known_tags(self) -> list[str]:
        seen: dict[str, None] = {}
        for iid in self.tree.get_children():
            for t in re.findall(r"#\w+", self.tree.set(iid, "title")):
                seen[t] = None
        return list(seen)

    def archive(self, undo: bool) -> None:
        eid = self.selected_id()
        if eid:
            self.bg(lambda: mindchuk_ops.archive(eid, undo),
                    lambda _: (self.say(f"{'Unarchived' if undo else 'Archived'} {eid[:8]}"), self.reload()))

    def delete(self) -> None:
        eid = self.selected_id()
        if eid and messagebox.askyesno("Delete entry", f"Permanently delete entry {eid[:8]}?\nThis cannot be undone.",
                                       parent=self.app):
            self.bg(lambda: mindchuk_ops.delete(eid),
                    lambda _: (self.cache.pop(eid, None), self.say(f"Deleted {eid[:8]}"), self.reload()))


local_ts = copilot_ops.local_ts


class SessionsPane(tk.Frame):
    """Copilot CLI session history (read-only) with one-key resume in a new terminal."""

    def __init__(self, parent, app: "Dashboard"):
        super().__init__(parent, bg=BLACK)
        self.app, self.repo_only, self.rows, self.token = app, False, {}, 0
        tk.Label(self, text="COPILOT SESSIONS  //  HISTORY", bg=BLACK, fg=ORANGE, font=LABEL_FONT,
                 anchor="w").pack(fill="x")
        bar = tk.Frame(self, bg=BLACK, height=48)
        bar.pack(fill="x", pady=(0, 6))
        bar.pack_propagate(False)
        for text, color, cmd in (("RESUME [ENTER]", ORANGE, self.resume), ("NEW COPILOT [P]", PEACH, self.new_here),
                                 ("VS CODE [O]", LAVENDER, self.code), ("RELOAD [R]", BLUE, self.reload),
                                 ("ALL REPOS [A]", PERIWINKLE, self.toggle_scope)):
            p = Pill(bar, text, color, cmd, width=10)
            p.pack(side="left", fill="both", expand=True, padx=(0, 6))
            if "REPOS" in text:
                self.scope_pill = p
        self.list_frame = RoundFrame(self, PERIWINKLE, height=240)
        self.list_frame.pack(fill="both", expand=True)
        holder = tk.Frame(self.list_frame, bg=BLACK)
        cols = (("when", "UPDATED", 170), ("turns", "TURNS", 80), ("folder", "FOLDER", 280), ("summary", "SUMMARY", 700))
        self.tree = ttk.Treeview(holder, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for cid, title, w in cols:
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=w, stretch=cid == "summary")
        sb = ttk.Scrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.list_frame.set_child(holder)
        self.text_frame = RoundFrame(self, LAVENDER, height=300)
        self.text_frame.pack(fill="both", expand=True, pady=(8, 0))
        th = tk.Frame(self.text_frame, bg=BLACK)
        self.view = tk.Text(th, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="word", bd=0, highlightthickness=0,
                            state="disabled", cursor="arrow")
        tsb = ttk.Scrollbar(th, command=self.view.yview)
        self.view.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True)
        self.text_frame.set_child(th)
        self.view.tag_configure("h", background=LAVENDER, foreground=BLACK, font=LABEL_FONT, spacing1=8, spacing3=2)
        self.view.tag_configure("k", foreground=ORANGE)
        self.status = tk.Label(self, text="", bg=BLACK, fg=BLUE, font=BODY_FONT, anchor="w")
        self.status.pack(fill="x")

        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<FocusIn>", lambda e: (self.list_frame.highlight(True), self.text_frame.highlight(False)))
        self.view.bind("<FocusIn>", lambda e: (self.list_frame.highlight(False), self.text_frame.highlight(True)))
        self.view.bind("<Button-1>", lambda e: self.view.focus_set())
        self.tree.bind("<Double-1>", lambda e: self.resume())
        for k, fn in (("Return", self.resume), ("p", self.new_here), ("o", self.code), ("r", self.reload),
                      ("a", self.toggle_scope), ("j", lambda: self.move(1)), ("k", lambda: self.move(-1)),
                      ("g", lambda: self.move("top")), ("G", lambda: self.move("bottom")),
                      ("l", lambda: self.view.focus_set()), ("h", lambda: self.tree.focus_set()),
                      ("Escape", app.show_status)):
            for w in (self.tree, self.view):
                w.bind(f"<Key-{k}>", lambda e, f=fn: (f(), "break")[1])

    def say(self, msg: str) -> None:
        self.status.configure(text=msg)

    def selected(self) -> dict | None:
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def move(self, step) -> None:
        if self.focus_get() is self.view:
            self.view.yview_moveto(0 if step == "top" else 1) if isinstance(step, str) else \
                self.view.yview_scroll(step * 2, "units")
            return
        rows = self.tree.get_children()
        if not rows:
            return
        cur = self.tree.selection()
        i = rows.index(cur[0]) if cur else 0
        i = 0 if step == "top" else len(rows) - 1 if step == "bottom" else min(max(i + step, 0), len(rows) - 1)
        self.tree.selection_set(rows[i])
        self.tree.see(rows[i])

    def open(self) -> None:
        self.tree.focus_set()
        self.reload()

    def toggle_scope(self) -> None:
        self.repo_only = not self.repo_only
        self.scope_pill.set("THIS REPO [A]" if self.repo_only else "ALL REPOS [A]")
        self.reload()

    def reload(self) -> None:
        repo = self.app.selected() if self.repo_only else None
        under = repo.path if repo else None
        keep = self.tree.selection()
        self.say("Loading sessions...")

        def done(rows):
            if isinstance(rows, Exception):
                self.say(f"Error: {rows}")
                return
            self.rows = {r["id"]: r for r in rows}
            self.tree.delete(*self.tree.get_children())
            for r in rows:
                self.tree.insert("", "end", iid=r["id"], values=(
                    local_ts(r["updated"]), r["turns"], Path(r["cwd"] or "?").name, r["summary"] or "(no summary)"))
            kids = self.tree.get_children()
            if kids:
                pick = keep[0] if keep and keep[0] in kids else kids[0]
                self.tree.selection_set(pick)
                self.tree.see(pick)
            self.say(f"{len(rows)} session(s)" + (f" in {repo.name}" if repo else "") + "  -  Enter resumes in a new window")
        self.app.run_bg(lambda: copilot_ops.sessions(300, under), done)

    def on_select(self) -> None:
        s = self.selected()
        if not s:
            return
        self.token += 1
        token = self.token

        def done(d):
            if token != self.token:
                return
            v = self.view
            v.configure(state="normal")
            v.delete("1.0", "end")
            if isinstance(d, Exception):
                v.insert("end", f"Error: {d}")
            else:
                def put(title, lines):
                    v.insert("end", f" {title} \n", "h")
                    v.insert("end", "\n".join(lines) + "\n\n" if lines else "none\n\n")
                put("SESSION", [f"Folder:   {s['cwd']}", f"Repo:     {s['repository'] or '-'}   Branch: {s['branch'] or '-'}",
                                f"Created:  {local_ts(s['created'])}   Updated: {local_ts(s['updated'])}",
                                f"Resume:   copilot --resume {s['id']}"])
                put("CHECKPOINTS", [f"{n}. {t}" for n, t in d["checkpoints"]])
                put("LAST PROMPTS", [f"[{i}] {(m or '').strip()[:300]}" for i, m in d["turns"]])
                put("FILES TOUCHED", d["files"])
                put("REFERENCES", [f"{t}: {val}" for t, val in d["refs"]])
            v.configure(state="disabled")
            v.yview_moveto(0)
        self.app.run_bg(lambda: copilot_ops.detail(s["id"]), done)

    def resume(self) -> None:
        s = self.selected()
        if s:
            self.say(copilot_ops.open_copilot(Path(s["cwd"] or Path.home()), resume=s["id"]))

    def new_here(self) -> None:
        s = self.selected()
        self.say(copilot_ops.open_copilot(Path(s["cwd"]) if s and s["cwd"] else Path.home()))

    def code(self) -> None:
        s = self.selected()
        if s and s["cwd"]:
            self.say(copilot_ops.open_vscode(Path(s["cwd"])))


class UsagePane(tk.Frame):
    """Copilot usage report: calls, tokens and premium requests per day, model and folder."""
    PERIODS = (7, 30, 90)

    def __init__(self, parent, app: "Dashboard"):
        super().__init__(parent, bg=BLACK)
        self.app, self.days = app, 30
        tk.Label(self, text="COPILOT USAGE  //  AUDIT", bg=BLACK, fg=ORANGE, font=LABEL_FONT, anchor="w").pack(fill="x")
        bar = tk.Frame(self, bg=BLACK, height=48)
        bar.pack(fill="x", pady=(0, 6))
        bar.pack_propagate(False)
        self.period_pill = Pill(bar, "", ORANGE, self.cycle, width=10)
        self.period_pill.pack(side="left", fill="both", expand=True, padx=(0, 6))
        Pill(bar, "RELOAD [R]", BLUE, self.reload, width=10).pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.frame = RoundFrame(self, LAVENDER, height=500)
        self.frame.pack(fill="both", expand=True)
        th = tk.Frame(self.frame, bg=BLACK)
        self.text = tk.Text(th, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="none", bd=0, highlightthickness=0,
                            state="disabled", cursor="arrow")
        sb = ttk.Scrollbar(th, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.frame.set_child(th)
        self.frame.highlight(True)
        self.text.tag_configure("h", background=LAVENDER, foreground=BLACK, font=LABEL_FONT, spacing1=8, spacing3=2)
        self.text.tag_configure("k", foreground=ORANGE)
        self.text.tag_configure("bar", foreground=PERIWINKLE)
        self.text.tag_configure("dim", foreground=LAVENDER)
        self.status = tk.Label(self, text="", bg=BLACK, fg=BLUE, font=BODY_FONT, anchor="w")
        self.status.pack(fill="x")
        for k, fn in (("r", self.reload), ("d", self.cycle), ("j", lambda: self.scroll(1)), ("k", lambda: self.scroll(-1)),
                      ("g", lambda: self.text.yview_moveto(0)), ("G", lambda: self.text.yview_moveto(1)),
                      ("Escape", app.show_status)):
            self.text.bind(f"<Key-{k}>", lambda e, f=fn: (f(), "break")[1])
        self._label()

    def _label(self) -> None:
        self.period_pill.set(f"PERIOD: {self.days} DAYS [D]")

    def scroll(self, n: int) -> None:
        self.text.yview_scroll(n * 2, "units")

    def cycle(self) -> None:
        self.days = self.PERIODS[(self.PERIODS.index(self.days) + 1) % len(self.PERIODS)]
        self._label()
        self.reload()

    def open(self) -> None:
        self.text.focus_set()
        self.reload()

    def reload(self) -> None:
        self.status.configure(text="Loading usage...")
        days = self.days

        def done(u):
            if isinstance(u, Exception):
                self.status.configure(text=f"Error: {u}")
                return
            self.render(u)
            self.status.configure(text=f"Last {days} days from ~/.copilot/session-store.db")
        self.app.run_bg(lambda: copilot_ops.usage(days), done)

    def render(self, u: dict) -> None:
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")

        def bar(v, mx, width=34):
            return "█" * max(1 if v else 0, round(width * v / mx)) if mx else ""
        calls = sum(r[2] for r in u["per_day"])
        toks = sum(r[3] + r[4] for r in u["per_day"])
        reqs = sum(r[5] for r in u["per_day"])
        t.insert("end", " SUMMARY \n", "h")
        t.insert("end", f"Sessions started: {u['sessions']}   Model calls: {calls:,}   "
                        f"Tokens: {toks / 1e6:,.1f}M   Premium requests (multiplier sum): {reqs:,.0f}\n\n")
        t.insert("end", " PER DAY (MODEL CALLS) \n", "h")
        mx = max((r[2] for r in u["per_day"]), default=0)
        t.insert("end", f"{'DATE':<11}{'SESS':>5}{'CALLS':>8}{'TOKENS':>10}  \n", "dim")
        for d, ns, c, i, o, _m in u["per_day"]:
            t.insert("end", f"{d:<11}{ns:>5}{c:>8,}{(i + o) / 1e6:>9.1f}M  ")
            t.insert("end", bar(c, mx) + "\n", "bar")
        t.insert("end", "\n BY MODEL \n", "h")
        t.insert("end", f"{'MODEL':<26}{'SESS':>5}{'CALLS':>8}{'TOKENS':>10}{'REQS':>9}\n", "dim")
        for m, ns, c, i, o, r in u["per_model"]:
            t.insert("end", f"{(m or '?')[:25]:<26}{ns:>5}{c:>8,}{(i + o) / 1e6:>9.1f}M{r:>9,.0f}\n")
        t.insert("end", "\n BY FOLDER / REPO (TOP 15) \n", "h")
        t.insert("end", f"{'FOLDER':<34}{'SESS':>5}{'CALLS':>8}\n", "dim")
        folders = u["per_folder"][:15]
        mx = max((r[2] for r in folders), default=0)
        for name, ns, c, _tok in folders:
            t.insert("end", f"{name[:33]:<34}{ns:>5}{c:>8,}  ")
            t.insert("end", bar(c, mx, 28) + "\n", "bar")
        t.configure(state="disabled")
        t.yview_moveto(0)


class MonitorPane(tk.Frame):
    """One sparkline per running Copilot CLI session (events per 10 s over the last 10 minutes)."""
    STATE_TAG = {"WORKING": "work", "WAITING?": "wait", "IDLE": "dim"}

    def __init__(self, parent, app: "Dashboard"):
        super().__init__(parent, bg=BLACK)
        self.app, self.loading, self.job = app, False, None
        tk.Label(self, text="COPILOT MONITOR  //  RUNNING SESSIONS  //  LAST 10 MIN, 10 S PER BAR", bg=BLACK, fg=ORANGE,
                 font=LABEL_FONT, anchor="w").pack(fill="x")
        self.frame = RoundFrame(self, LAVENDER, height=500)
        self.frame.pack(fill="both", expand=True)
        th = tk.Frame(self.frame, bg=BLACK)
        self.text = tk.Text(th, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="none", bd=0, highlightthickness=0,
                            state="disabled", cursor="arrow")
        sb = ttk.Scrollbar(th, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.frame.set_child(th)
        self.frame.highlight(True)
        self.text.tag_configure("h", background=LAVENDER, foreground=BLACK, font=LABEL_FONT, spacing1=8, spacing3=2)
        self.text.tag_configure("work", foreground=BLUE)
        self.text.tag_configure("wait", foreground=ORANGE)
        self.text.tag_configure("dim", foreground=LAVENDER)
        self.status = tk.Label(self, text="", bg=BLACK, fg=BLUE, font=BODY_FONT, anchor="w")
        self.status.pack(fill="x")
        for k, fn in (("r", self.refresh), ("Escape", app.show_status)):
            self.text.bind(f"<Key-{k}>", lambda e, f=fn: (f(), "break")[1])

    def open(self) -> None:
        self.text.focus_set()
        self.refresh()
        if self.job is None:
            self.job = self.after(3000, self._auto)

    def _auto(self) -> None:
        self.job = None
        if self.app.view != "monitor":
            return
        self.refresh()
        self.job = self.after(3000, self._auto)

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True

        def done(rows):
            self.loading = False
            if isinstance(rows, Exception):
                self.status.configure(text=f"Error: {rows}")
            else:
                self.render(rows)
        self.app.run_bg(live_ops.snapshot, done)

    def render(self, rows: list[dict]) -> None:
        t = self.text
        top = t.yview()[0]
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f" {'STATE':<26}{'SESSION':<36}{'FOLDER':<22}{'ACTIVITY (OLD → NOW)':<62}{'LAST':>6}{'EVENTS':>8}{'PID':>8} \n", "h")
        for r in rows:
            tag = self.STATE_TAG.get(r["state"], "dim")
            state = r["state"] + (f" {r['detail']}" if r["detail"] and r["state"] != "IDLE" else "")
            t.insert("end", f" {state[:24]:<26}", tag)
            t.insert("end", f"{r['name'][:34]:<36}{r['folder'][:20]:<22}")
            t.insert("end", f"{live_ops.sparkline(r['counts']):<62}", tag)
            t.insert("end", f"{live_ops.age_label(r['age']):>6}{r['total']:>8}{r['pid']:>8}\n")
        if not rows:
            t.insert("end", "\n No running Copilot CLI sessions found.\n", "dim")
        t.configure(state="disabled")
        t.yview_moveto(top)
        n = sum(r["state"] == "WORKING" for r in rows)
        self.status.configure(text=f"{len(rows)} running session(s), {n} working  //  refreshes every 3 s  //  r: refresh")


class Dashboard(tk.Tk):
    def __init__(self, roots: list[Path] | None = None):
        set_theme(load_saved_theme())
        super().__init__()
        self.roots = roots or config.roots() or [Path.home()]
        self.root_dir = self.roots[0]
        self.scope = "status"
        self.test_results = tests_ops.load_results()
        self._loaded_n = 0
        self.tests_busy: set[str] = set()
        self.repos: dict[str, RepoStatus] = {}
        self.views: dict[str, str] = {}
        self.busy: set[str] = set()
        self.sort_col: str | None = None
        self.sort_desc = False
        self.q: queue.Queue = queue.Queue()
        self.detail_token = 0
        self.title("Assembla Repository Activity")
        self.geometry(f"{min(1500, self.winfo_screenwidth() - 60)}x{min(940, self.winfo_screenheight() - 100)}+20+20")
        self.configure(bg=BLACK)
        self._style()
        self._build()
        self._bind_keys()
        self.after(100, self._pump)
        self.after(1000, self._tick)
        self._tick()
        self.load_all()

    # ---------- themes ----------
    def _label_theme(self) -> None:
        self.theme_pill.set(f"THEME [F5 / C]\n{theme_name}")

    def cycle_theme(self) -> None:
        names = list(THEMES)
        self.apply_theme(names[(names.index(theme_name) + 1) % len(names)])

    def apply_theme(self, new: str) -> None:
        old = theme_name
        if new == old:
            return
        m = recolor_map(old, new)
        set_theme(new)
        opts = ("background", "foreground", "highlightbackground", "highlightcolor", "insertbackground",
                "selectbackground", "selectforeground", "activebackground", "activeforeground")

        def walk(w):
            yield w
            for c in w.winfo_children():
                yield from walk(c)

        for w in walk(self):
            for o in opts:
                try:
                    v = str(w.cget(o))
                except tk.TclError:
                    continue
                if m(v) != v:
                    w.configure(**{o: m(v)})
            if isinstance(w, (Pill, RoundFrame)):
                w.color = m(w.color)
                w.draw()
            if isinstance(w, tk.Text):
                for tag in w.tag_names():
                    for o in ("foreground", "background"):
                        v = str(w.tag_cget(tag, o))
                        if v and m(v) != v:
                            w.tag_configure(tag, **{o: m(v)})
            if isinstance(w, ttk.Treeview):
                for tag in ("behind", "ahead", "bad", "busy"):
                    v = str(w.tag_configure(tag, "foreground") or "")
                    if v and m(v) != v:
                        w.tag_configure(tag, foreground=m(v))
        self._style()
        self._label_theme()
        try:
            config.save(theme=new)
        except OSError:
            pass
        self.say(f"Theme: {new}")

    # ---------- layout ----------
    def destroy(self) -> None:
        self.terminal.shutdown()
        super().destroy()
    def _style(self) -> None:
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("Treeview", background=BLACK, fieldbackground=BLACK, foreground=TEXT,
                     font=BODY_FONT, rowheight=34, borderwidth=0)
        st.configure("Treeview.Heading", background=PERIWINKLE, foreground=BLACK, font=LABEL_FONT,
                     relief="flat")
        st.map("Treeview", background=[("selected", ORANGE)], foreground=[("selected", BLACK)])
        st.map("Treeview.Heading", background=[("active", PERIWINKLE)])
        st.configure("Vertical.TScrollbar", background=LAVENDER, troughcolor=BLACK, bordercolor=BLACK,
                     arrowcolor=BLACK)

    def _build(self) -> None:
        head = tk.Frame(self, bg=BLACK, height=62)
        head.pack(fill="x", padx=8, pady=(8, 0))
        head.pack_propagate(False)
        Pill(head, "STARFLEET REPOSITORY ACTIVITY  //  ASSEMBLA", ORANGE).pack(side="left", fill="both", expand=True)
        Pill(head, "", LAVENDER, width=70).pack(side="left", fill="y", padx=6)
        self.clock = Pill(head, "", PERIWINKLE, width=290, anchor="e")
        self.clock.pack(side="left", fill="y")

        body = tk.Frame(self, bg=BLACK)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        side = tk.Frame(body, bg=BLACK, width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        nav = (("SOFTWAREDEVELOPMENT\n[F1 / D]", ORANGE, self.show_status), ("HOMEDEV\n[F8 / H]", PEACH, self.show_homedev),
               ("TERMINAL\n[F2 / T]", PERIWINKLE, self.show_terminal),
               ("MINDCHUK\n[F3 / M]", PEACH, self.show_mindchuk), ("SESSIONS\n[F6 / S]", LAVENDER, self.show_sessions),
               ("USAGE\n[F7 / U]", BLUE, self.show_usage), ("MONITOR\n[F9 / W]", PERIWINKLE, self.show_monitor))
        self.nav_pills = []
        for text, color, cmd in nav:
            p = Pill(side, text, color, cmd, height=70)
            p.pack(fill="x", pady=(0, 6))
            self.nav_pills.append(p)
        Pill(side, "HELP\n[F4 / ?]", BLUE, self.show_help, height=70).pack(side="bottom", fill="x")
        self.theme_pill = Pill(side, "", PERIWINKLE, self.cycle_theme, height=70)
        self.theme_pill.pack(side="bottom", fill="x", pady=(0, 6))
        self._label_theme()
        Pill(side, "", LAVENDER).pack(fill="both", expand=True, pady=(0, 6))

        self.content = tk.Frame(body, bg=BLACK)
        self.content.pack(side="left", fill="both", expand=True, padx=(10, 0))
        main = tk.Frame(self.content, bg=BLACK)
        main.pack(fill="both", expand=True)
        self.status_view = main
        self.terminal = TerminalPane(self.content, self)
        self.mindchuk = MindchukPane(self.content, self)
        self.sessions = SessionsPane(self.content, self)
        self.usage = UsagePane(self.content, self)
        self.monitor = MonitorPane(self.content, self)
        self.panes = {"status": main, "terminal": self.terminal, "mindchuk": self.mindchuk,
                      "sessions": self.sessions, "usage": self.usage, "monitor": self.monitor}
        self.list_title = tk.Label(main, text="SOFTWAREDEVELOPMENT", bg=BLACK, fg=ORANGE, font=LABEL_FONT, anchor="w")
        self.list_title.pack(fill="x")
        self.list_frame = RoundFrame(main, PERIWINKLE, height=300)
        self.list_frame.pack(fill="both", expand=True)
        holder = tk.Frame(self.list_frame, bg=BLACK)
        self.tree = ttk.Treeview(holder, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for cid, title, w in COLUMNS:
            self.tree.heading(cid, text=title, command=lambda c=cid: self.sort_by(c))
            self.tree.column(cid, width=w, anchor="w")
        sb = ttk.Scrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for tag, color in (("behind", ORANGE), ("ahead", LAVENDER), ("bad", "#ff3333"), ("busy", BLUE)):
            self.tree.tag_configure(tag, foreground=color)
        self.list_frame.set_child(holder)

        self.detail_title = tk.Label(main, text="SUMMARY", bg=BLACK, fg=ORANGE, font=LABEL_FONT, anchor="w")
        self.detail_title.pack(fill="x", pady=(8, 0))
        self.detail_frame = RoundFrame(main, LAVENDER, height=380)
        self.detail_frame.pack(fill="both", expand=True)
        dh = tk.Frame(self.detail_frame, bg=BLACK)
        self.detail = tk.Text(dh, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="word", bd=0, highlightthickness=0,
                              insertbackground=BLACK, cursor="arrow", state="disabled", spacing1=1)
        dsb = ttk.Scrollbar(dh, command=self.detail.yview)
        self.detail.configure(yscrollcommand=dsb.set)
        dsb.pack(side="right", fill="y")
        self.detail.pack(side="left", fill="both", expand=True)
        self.detail_frame.set_child(dh)
        self.detail.tag_configure("title", background=LAVENDER, foreground=BLACK, font=LABEL_FONT,
                                  spacing1=10, spacing3=2)

        self.status = Pill(self, "", BLUE, height=34)
        self.status.pack(fill="x", padx=8, pady=(0, 8))
        self.say("j/k move  g/G top/bottom  l/Enter open  b branch  r/a refresh  x tests  o code  e explorer  p copilot  s sessions  u usage  ? help")

        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<FocusIn>", lambda e: self._focus_ring(True))
        self.detail.bind("<FocusIn>", lambda e: self._focus_ring(False))
        self.detail.bind("<Button-1>", lambda e: self.detail.focus_set())
        self.tree.focus_set()
        self._focus_ring(True)

    def _focus_ring(self, list_active: bool) -> None:
        self.list_frame.highlight(list_active)
        self.detail_frame.highlight(not list_active)

    # ---------- keys ----------
    def _bind_keys(self) -> None:
        def on(key, fn):
            def handler(e):
                if self.view != "status" and key not in ("<F1>", "<F2>", "<F3>", "<F4>", "<F5>", "<F6>", "<F7>", "<F8>", "<F9>"):
                    return None  # let the active pane receive typing
                fn()
                return "break"
            self.bind(key, handler)
        on("<F1>", self.show_status)
        on("<Key-d>", self.show_status)
        on("<F8>", self.show_homedev)
        on("<Key-h>", self.show_homedev)
        on("<F4>", self.show_help)
        on("<F5>", self.cycle_theme)
        on("<Key-c>", self.cycle_theme)
        self.bind("<Key-question>", lambda e: None if self.view == "terminal" else (self.show_help(), "break")[1])
        on("<F2>", self.show_terminal)
        on("<F3>", self.show_mindchuk)
        on("<Key-t>", self.show_terminal)
        on("<Key-m>", self.show_mindchuk)
        on("<F6>", self.show_sessions)
        on("<F7>", self.show_usage)
        on("<F9>", self.show_monitor)
        on("<Key-w>", self.show_monitor)
        on("<Key-s>", self.show_sessions)
        on("<Key-u>", self.show_usage)
        self.view = "status"
        on("<Key-r>", self.refresh_selected)
        on("<Key-a>", self.refresh_all)
        on("<Control-r>", self.load_all)
        on("<Key-o>", self.launch_code)
        on("<Key-e>", self.launch_explorer)
        on("<Key-p>", self.launch_copilot)
        on("<Key-x>", self.run_tests)
        on("<Key-b>", self.pick_branch)
        on("<Key-q>", self.destroy)
        on("<Key-j>", lambda: self.nav(1))
        on("<Key-k>", lambda: self.nav(-1))
        on("<Key-g>", lambda: self.nav("top"))
        on("<Key-G>", lambda: self.nav("bottom"))
        on("<Control-d>", lambda: self.nav(10))
        on("<Control-u>", lambda: self.nav(-10))
        for k in ("<Key-l>", "<Return>"):
            on(k, lambda: self.detail.focus_set() if self.focus_get() is self.tree else None)
        on("<Key-h>", lambda: self.tree.focus_set() if self.focus_get() is self.detail else self.show_homedev())
        on("<Tab>", lambda: (self.detail if self.focus_get() is self.tree else self.tree).focus_set())

    # ---------- help ----------
    HELP = {
        "status": ("SOFTWAREDEVELOPMENT / HOMEDEV", [
            ("j / k, ↓ / ↑", "Move through repositories (or scroll the summary)"),
            ("click a header", "Sort by that column; click again to reverse (▲/▼ shows direction)"),
            ("g / G", "Jump to first / last"),
            ("Ctrl+d / Ctrl+u", "Page down / up"),
            ("l / Enter", "Move focus to the summary pane"),
            ("h", "Back to the repository list (from the summary); from the list, open the HomeDev tab"),
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
            ("(tests)", "PASS/FAIL + age of the last run from the dashboard, RUNNING, N/A (no test command), - (never run)"),
            ("(source)", "ASSEMBLA, GITHUB, LOCAL (no remote), ... taken from the git remote URL"),
            ("(roots)", "Folders scanned (2 levels deep): set \"roots\" in ~/.lcars_dash.json; default SoftwareDevelopment + HomeDev"),
            ("(HomeDev tab)", "F8 / h lists repos under ~/HomeDev with the same keys; the SoftwareDevelopment tab lists the rest"),
        ]),
        "sessions": ("COPILOT SESSIONS", [
            ("j / k, g / G", "Move through sessions (or scroll the details)"),
            ("l / h", "Focus the details / the list"),
            ("Enter / double-click", "Resume the session: new PowerShell window running copilot --resume in its folder"),
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
            ("Ctrl+Enter", "Save and send to Mindchuk (or click SAVE)"),
            ("Esc", "Cancel"),
            ("TAGS field", "Space/comma separated; added as #hashtags (start of a new entry, end of an append)"),
            ("Enter in TAGS", "Also saves"),
        ]),
    }
    GLOBAL_HELP = [
        ("F1 / d", "SoftwareDevelopment repos"), ("F8 / h", "HomeDev repos (under ~/HomeDev)"), ("F2 / t", "Terminal"), ("F3 / m", "Mindchuk"),
        ("F6 / s", "Copilot Sessions"), ("F7 / u", "Copilot Usage"), ("F9 / w", "Monitor running Copilot sessions"),
        ("F4 / ?", "This help"), ("F5 / c", "Cycle colour theme (TNG, DS9, Klingon, Romulan, Vulcan; saved)"),
        ("q", "Quit (not while typing in the terminal)"),
    ]

    def show_help(self) -> None:
        if getattr(self, "help_win", None) and self.help_win.winfo_exists():
            self.help_win.destroy()
            return
        title, rows = self.HELP[self.view]
        win = self.help_win = tk.Toplevel(self, bg=BLACK)
        win.title("Help")
        win.geometry("760x680")
        win.transient(self)
        tk.Label(win, text=f"HELP  //  {title}", bg=ORANGE, fg=BLACK, font=LABEL_FONT, anchor="w",
                 padx=10).pack(fill="x", padx=10, pady=10)
        box = tk.Text(win, bg=BLACK, fg=TEXT, font=BODY_FONT, wrap="word", bd=0, highlightthickness=2,
                      highlightbackground=LAVENDER, state="normal", cursor="arrow", tabs=("240",))
        box.tag_configure("h", background=LAVENDER, foreground=BLACK, font=LABEL_FONT, spacing1=8, spacing3=4)
        box.tag_configure("k", foreground=ORANGE, font=(BODY_FONT[0], BODY_FONT[1], "bold"))
        for heading, items in ((title, rows), ("ANYWHERE", self.GLOBAL_HELP)):
            box.insert("end", f" {heading} \n", "h")
            for key, desc in items:
                box.insert("end", f"{key}", "k")
                box.insert("end", f"\t{desc}\n")
            box.insert("end", "\n")
        box.insert("end", "Press Esc, q, ? or F4 to close.", "k")
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for k in ("<Escape>", "<Key-q>", "<Key-question>", "<F4>"):
            win.bind(k, lambda e: (win.destroy(), "break")[1])
        win.focus_set()

    # ---------- views ----------
    def switch(self, name: str) -> None:
        for n, pane in self.panes.items():
            if n != name:
                pane.pack_forget()
        self.view = name
        self.panes[name].pack(fill="both", expand=True)

    def show_status(self, scope: str = "status") -> None:
        if self.view != "status" or scope != self.scope:
            self.switch("status")
            self.tree.focus_set()
            if scope != self.scope:
                self.scope = scope
                self._set_scope()

    def show_homedev(self) -> None:
        self.show_status("homedev")

    def _in_homedev(self, s: RepoStatus) -> bool:
        try:
            return s.path.resolve().is_relative_to(HOMEDEV.resolve())
        except OSError:
            return False

    def _visible(self, s: RepoStatus) -> bool:
        return self._in_homedev(s) == (self.scope == "homedev")

    def _set_scope(self) -> None:
        home = self.scope == "homedev"
        self.list_title.configure(text="HOMEDEV  //  ~/HomeDev" if home else "SOFTWAREDEVELOPMENT")
        self.tree.delete(*self.tree.get_children())
        for s in self.repos.values():
            self._render_row(s)
        self.apply_sort()
        rows = self.tree.get_children()
        if rows:
            self.tree.selection_set(rows[0])
            self.tree.focus(rows[0])
        else:
            self.detail_token += 1
            self.detail_title.configure(text="SUMMARY")
            self._fill([])
        self.say(f"{len(rows)} repositories in " + ("~/HomeDev" if home else "SoftwareDevelopment"))

    def show_terminal(self) -> None:
        self.switch("terminal")
        s = self.selected()
        self.terminal.open(s.path if s else self.root_dir)

    def show_mindchuk(self) -> None:
        self.switch("mindchuk")
        self.mindchuk.open()

    def show_sessions(self) -> None:
        self.switch("sessions")
        self.sessions.open()

    def show_usage(self) -> None:
        self.switch("usage")
        self.usage.open()

    def show_monitor(self) -> None:
        self.switch("monitor")
        self.monitor.open()

    # ---------- launchers / tests ----------
    def _launch(self, fn) -> None:
        s = self.selected()
        if s:
            try:
                self.say(fn(s.path))
            except OSError as e:
                self.say(f"{s.name}: {e}")

    def launch_code(self) -> None:
        self._launch(copilot_ops.open_vscode)

    def launch_explorer(self) -> None:
        self._launch(copilot_ops.open_explorer)

    def launch_copilot(self) -> None:
        self._launch(copilot_ops.open_copilot)

    def run_tests(self) -> None:
        s = self.selected()
        if not s or s.name in self.tests_busy:
            return
        cmd = tests_ops.detect(s.path, s.name)
        if not cmd:
            self.say(f"{s.name}: no test command detected (set \"test_commands\" in ~/.lcars_dash.json)")
            return
        name, path = s.name, s.path
        self.tests_busy.add(name)
        self._render_row(s)
        self.say(f"{name}: running `{cmd}` ...")

        def done(res):
            self.tests_busy.discard(name)
            if isinstance(res, Exception):
                self.say(f"{name}: {res}")
            else:
                self.test_results[str(path)] = res
                self.say(f"{name}: tests {'PASSED' if res['rc'] == 0 else 'FAILED' if res['rc'] is not None else 'not run'}"
                         f" ({res['secs']}s)")
            cur = self.repos.get(name)
            if cur:
                self._render_row(cur)
                self.apply_sort()
                sel = self.selected()
                if sel and sel.name == name:
                    self.show_detail(cur)
        self.run_bg(lambda: tests_ops.run(path, name), done)

    # ---------- keys ----------
    def nav(self, step) -> None:
        if self.focus_get() is self.detail:
            if step == "top":
                self.detail.yview_moveto(0)
            elif step == "bottom":
                self.detail.yview_moveto(1)
            else:
                self.detail.yview_scroll(step * 2, "units")
            return
        rows = self.tree.get_children()
        if not rows:
            return
        cur = self.tree.selection()
        i = rows.index(cur[0]) if cur else 0
        i = 0 if step == "top" else len(rows) - 1 if step == "bottom" else min(max(i + step, 0), len(rows) - 1)
        self.tree.selection_set(rows[i])
        self.tree.focus(rows[i])
        self.tree.see(rows[i])

    # ---------- plumbing ----------
    def say(self, msg: str) -> None:
        self.status.set(msg)

    def _tick(self) -> None:
        self.clock.set(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(1000, self._tick)

    def run_bg(self, fn, then) -> None:
        def go():
            try:
                res = fn()
            except Exception as e:  # keep UI alive
                res = e
            self.q.put((then, res))
        threading.Thread(target=go, daemon=True).start()

    def _pump(self) -> None:
        try:
            while True:
                then, res = self.q.get_nowait()
                then(res)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    # ---------- table ----------
    def _row(self, s: RepoStatus) -> tuple[tuple[str, ...], str]:
        if s.name in self.busy:
            sync, tag = "REFRESHING", "busy"
        elif s.last_date == "-":
            sync, tag = "ERROR", "bad"
        elif s.error:
            sync, tag = "FAILED", "bad"
        elif s.behind:
            sync, tag = f"↓{s.behind}", "behind"
        elif s.ahead:
            sync, tag = f"↑{s.ahead}", "ahead"
        else:
            sync, tag = ("OK*" if s.dirty else "OK"), ""
        health = " ".join(p for p in (f"M{s.changed}" if s.changed else "", f"?{s.untracked}" if s.untracked else "",
                                      f"S{s.stashes}" if s.stashes else "", f"U{s.unmerged}" if s.unmerged else "") if p)
        tests = "RUNNING" if s.name in self.tests_busy else tests_ops.label(self.test_results.get(str(s.path)))
        return (s.name, s.view_branch, s.branch, s.last_date, s.last_rel, s.last_author, sync,
                health or "clean", tests, s.source), tag

    def _render_row(self, s: RepoStatus) -> None:
        if not self._visible(s):
            if self.tree.exists(s.name):
                self.tree.delete(s.name)
            return
        vals, tag = self._row(s)
        if self.tree.exists(s.name):
            self.tree.item(s.name, values=vals, tags=(tag,))
        else:
            self.tree.insert("", "end", iid=s.name, values=vals, tags=(tag,))

    def selected(self) -> RepoStatus | None:
        sel = self.tree.selection()
        return self.repos.get(sel[0]) if sel else None

    def _store(self, s: RepoStatus) -> None:
        old = self.repos.get(s.name)
        if old and not s.pulled:
            s.pulled = old.pulled
        self.repos[s.name] = s
        self._render_row(s)
        self.apply_sort()
        cur = self.selected()
        if cur and cur.name == s.name:
            self.show_detail(s)

    # ---------- sorting ----------
    SORT_KEYS = {
        "repo": lambda s: s.name.lower(),
        "view": lambda s: s.view_branch.lower(),
        "co": lambda s: s.branch.lower(),
        "date": lambda s: s.last_date if s.last_date != "-" else "",
        "age": lambda s: s.last_date if s.last_date != "-" else "",
        "by": lambda s: s.last_author.lower(),
        "sync": lambda s: (s.last_date == "-" or bool(s.error), s.behind, s.ahead, s.dirty),
        "health": lambda s: (s.changed + s.untracked, s.stashes, s.unmerged),
        "tests": None,  # needs instance state, see apply_sort
        "src": lambda s: s.source,
    }

    def _test_key(self, s: RepoStatus):
        r = self.test_results.get(str(s.path))
        return (r is not None, r is not None and r.get("rc") not in (0, None), r["when"] if r else "")

    def sort_by(self, col: str) -> None:
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            # newest-first is the natural order for date/age
            self.sort_col, self.sort_desc = col, col in ("date", "age")
        for cid, title, _ in COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if cid == self.sort_col else ""
            self.tree.heading(cid, text=title + arrow)
        self.apply_sort()
        sel = self.tree.selection()
        if sel:
            self.tree.see(sel[0])

    def apply_sort(self) -> None:
        if not self.sort_col:
            return
        key = self.SORT_KEYS[self.sort_col] or self._test_key
        order = sorted(self.repos.values(), key=lambda s: (key(s), s.name.lower()), reverse=self.sort_desc)
        for i, s in enumerate(order):
            if self.tree.exists(s.name):
                self.tree.move(s.name, "", i)

    # ---------- actions ----------
    def load_all(self) -> None:
        def work():
            found = git_ops.discover_all(self.roots)
            self.q.put((lambda _: setattr(self, "_loaded_n", 0), None))
            total = len(found)

            def one(item):
                p, n = item
                s = git_ops.read_status(p, self.views.get(n), n)
                self.q.put((lambda r: self._loaded(r, total), s))
            with ThreadPoolExecutor(6) as ex:
                list(ex.map(one, found))
            return found

        def done(found):
            if isinstance(found, Exception):
                self.say(f"Error: {found}")
                return
            where = ", ".join(str(r) for r in self.roots)
            self.say(f"{len(found)} repositories tracked in {where}" if found else f"No repositories found in {where}")
        self.say("Reading repositories...")
        self.run_bg(work, done)

    def _loaded(self, s: RepoStatus, total: int) -> None:
        self._loaded_n += 1
        self._store(s)
        rows = self.tree.get_children()
        if rows and not self.selected():
            self.tree.selection_set(rows[0])
            self.tree.focus(rows[0])
        self.say(f"Reading repositories... {self._loaded_n}/{total}")

    def refresh_selected(self) -> None:
        s = self.selected()
        if s:
            self.refresh_repo(s.name)

    def refresh_all(self) -> None:
        for n in list(self.repos):
            self.refresh_repo(n)

    def refresh_repo(self, name: str) -> None:
        if name in self.busy:
            return
        self.busy.add(name)
        self._render_row(self.repos[name])

        def done(res):
            self.busy.discard(name)
            if isinstance(res, Exception):
                self._render_row(self.repos[name])
                self.say(f"{name}: {res}")
                return
            self._store(res)
            self.say(f"{name}: " + (res.error or f"refreshed, {len(res.pulled)} new commit(s)"))
        path, view = self.repos[name].path, self.views.get(name)
        self.run_bg(lambda: git_ops.refresh(path, view, name), done)

    def pick_branch(self) -> None:
        s = self.selected()
        if not s:
            return

        def done(names):
            if isinstance(names, Exception) or not names:
                self.say(f"{s.name}: no branches")
            else:
                BranchPicker(self, s.name, names, s.view_branch)
        self.run_bg(lambda: git_ops.branch_names(s.path), done)

    def set_branch(self, repo: str, branch: str) -> None:
        self.views[repo] = branch
        path = self.repos[repo].path
        self.run_bg(lambda: git_ops.read_status(path, branch, repo),
                    lambda s: self._store(s) if isinstance(s, RepoStatus) else self.say(str(s)))
        self.tree.focus_set()

    # ---------- detail ----------
    def on_select(self) -> None:
        s = self.selected()
        if s:
            self.show_detail(s)

    def show_detail(self, s: RepoStatus) -> None:
        self.detail_token += 1
        token = self.detail_token

        def work():
            out = []
            for title, fn in panels.PANELS:
                try:
                    out.append((title, fn(s)))
                except Exception as e:
                    out.append((title, f"[red]panel error: {e}[/]"))
            return out

        def done(sections):
            if token != self.detail_token or isinstance(sections, Exception):
                return
            self.detail_title.configure(text=f"SUMMARY  //  {s.name.upper()}")
            self._fill(sections)
        self.run_bg(work, done)

    def _fill(self, sections) -> None:
        d = self.detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        for title, body in sections:
            d.insert("end", f" {title} \n", "title")
            self._insert_markup(body)
            d.insert("end", "\n")
        d.configure(state="disabled")
        d.yview_moveto(0)

    def _insert_markup(self, markup: str) -> None:
        t = Text.from_markup(markup)
        plain, d = t.plain, self.detail
        pos = 0
        for span in sorted(t.spans, key=lambda s: s.start):
            if span.start > pos:
                d.insert("end", plain[pos:span.start])
            style = span.style if isinstance(span.style, Style) else Style.parse(str(span.style))
            tag = f"s{abs(hash(str(style)))}"
            color = TEXT
            if style.color is not None:
                color = themed(style.color.get_truecolor().hex)
            if style.dim:
                r, g, b = (int(PEACH[i:i + 2], 16) * 0.6 for i in (1, 3, 5))
                color = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
            font = (BODY_FONT[0], BODY_FONT[1], "bold") if style.bold else BODY_FONT
            d.tag_configure(tag, foreground=color, font=font)
            d.insert("end", plain[span.start:span.end], tag)
            pos = max(pos, span.end)
        d.insert("end", plain[pos:] + "\n")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, action="append",
                    help="repository root to scan (repeatable); default: roots from ~/.lcars_dash.json")
    Dashboard(ap.parse_args().root).mainloop()


if __name__ == "__main__":
    main()
