"""TUI HOME pane: one-screen daily overview (monitor, usage, work-week calendars, inboxes, Mindchuk quick entry)."""
from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, TextArea

from . import copilot_ops, google_ops, home_ops, live_ops, mindchuk_ops, outlook_ops
from .tui_panes import Navigable

MON_COLS = " {:<3}{:<27}{:<34}{:<18}{:<6}{:>9}  {:<7}"


class HomeView(Navigable):
    BINDINGS = [Binding("r", "reload", "Reload"), Binding("n", "entry", "Quick entry"),
                Binding("ctrl+s", "send", "Send entry", priority=True), Binding("escape", "back", "Back")]
    can_focus = True
    STALE_S = 60

    def __init__(self, **kw):
        super().__init__(**kw)
        self.data: dict[str, object] = {}
        self.loading, self.last_load, self.timer = False, 0.0, None

    def compose(self) -> ComposeResult:
        mon, fri = home_ops.week_range()
        week = f"{mon:%m-%d} to {fri:%m-%d}"
        yield Static("", id="hm-mon", classes="hm-box")
        with Horizontal(classes="hm-row hm-top"):
            yield Static("", id="hm-usage", classes="hm-box")
            with Vertical(classes="hm-box", id="hm-quick"):
                yield TextArea(id="hm-entry")
                yield Static("", id="hm-entry-status")
        with Horizontal(classes="hm-row hm-cal"):
            for src in ("outlook", "google"):
                yield VerticalScroll(Static("", id=f"hm-cal-{src}"), id=f"hm-calbox-{src}", classes="hm-box")
        with Horizontal(classes="hm-row hm-mail"):
            for src in ("outlook", "google"):
                yield Static("", id=f"hm-mail-{src}", classes="hm-box")
        yield Static(f"r reload  //  n quick entry (Ctrl+S sends, Esc leaves)  //  monitor 2 s, rest 5 min  //  week {week}",
                     id="hm-status", classes="view-status")

    def on_mount(self) -> None:
        mon, fri = home_ops.week_range()
        week = f"{mon:%m-%d} to {fri:%m-%d}"
        titles = {"#hm-mon": "COPILOT MONITOR", "#hm-usage": "TODAY'S COPILOT USAGE", "#hm-quick": "MINDCHUK QUICK ENTRY",
                  "#hm-calbox-outlook": f"OUTLOOK CALENDAR  {week}", "#hm-calbox-google": f"GMAIL CALENDAR  {week}",
                  "#hm-mail-outlook": "OUTLOOK INBOX", "#hm-mail-google": "GMAIL INBOX"}
        for sel, title in titles.items():
            self.query_one(sel).border_title = title
        self.timer = self.set_interval(2, self._auto)

    def on_resize(self) -> None:
        self.render_all()

    # ---- actions ----
    def open(self) -> None:
        self.screen.set_focus(self)
        self.refresh_monitor()
        if time.time() - self.last_load > self.STALE_S:
            self.action_reload()

    def action_entry(self) -> None:
        self.query_one("#hm-entry", TextArea).focus()

    def action_back(self) -> None:
        self.screen.set_focus(self)

    def action_send(self) -> None:
        box = self.query_one("#hm-entry", TextArea)
        status = self.query_one("#hm-entry-status", Static)
        text = box.text.strip()
        if not text:
            status.update("Nothing to add")
            return
        status.update("Sending to Mindchuk...")

        def done(res):
            if isinstance(res, Exception):
                status.update(f"Error: {res}")
                return
            box.text = ""
            status.update(f"Added {str(res).strip()[:60]}")
        self.app.run_bg(lambda: mindchuk_ops.add(text), done)

    def say(self, msg: str) -> None:
        self.query_one("#hm-status", Static).update(msg)

    # ---- data ----
    def _auto(self) -> None:
        if self.app.current_view != "home":
            return
        self.refresh_monitor()
        if time.time() - self.last_load > 300:
            self.action_reload()

    def refresh_monitor(self) -> None:
        if self.loading:
            return
        self.loading = True

        def done(rows):
            self.loading = False
            self.data["monitor"] = rows
            self.render_monitor()
        self.app.run_bg(live_ops.snapshot, done)

    def action_reload(self) -> None:
        self.last_load = time.time()
        jobs = {"usage": copilot_ops.today_usage,
                "cal_outlook": lambda: home_ops.week_events(outlook_ops), "cal_google": lambda: home_ops.week_events(google_ops),
                "mail_outlook": lambda: outlook_ops.mail(8), "mail_google": lambda: google_ops.mail(8)}
        for key, fn in jobs.items():
            def done(res, key=key):
                self.data[key] = res
                self.render_all()
            self.app.run_bg(fn, done)

    # ---- render ----
    def _styles(self) -> dict[str, str]:
        c = self.app.colors
        return {"h": c["ORANGE"], "today": f"bold {c['BLACK']} on {c['ORANGE']}", "unread": c["ORANGE"], "dim": c["LAVENDER"],
                "err": c["RED"], "row": "", "hdr": f"bold reverse {c['LAVENDER']}"}

    def _lines(self, lines: list[tuple[str, str]]) -> Text:
        st, t = self._styles(), Text()
        for tag, text in lines:
            t.append(text + "\n", style=st.get(tag, ""))
        return t

    def _width(self, sel: str) -> int:
        return max(30, self.query_one(sel).size.width - 4)

    def render_all(self) -> None:
        self.render_monitor()
        self.render_usage()
        for src in ("outlook", "google"):
            self.render_cal(src)
            self.render_mail(src)

    def render_monitor(self) -> None:
        rows = self.data.get("monitor")
        if rows is None:
            return
        box = self.query_one("#hm-mon", Static)
        if isinstance(rows, Exception):
            return box.update(self._lines([("err", f"Error: {rows}")]))
        st = self._styles()
        t = Text(MON_COLS.format("", "STATE", "SESSION", "FOLDER", "LAST", "AIC", "PID") + "  ACTIVITY\n", style=st["hdr"])
        for r in rows:
            mode = live_ops.MODE_COLOR.get(r["mode"], live_ops.REGULAR_COLOR)
            t.append(f" {live_ops.ICONS.get(r['state'], '?'):<3}", style=live_ops.ICON_COLOR.get(r["state"], "white"))
            t.append(f"{live_ops.state_text(r)[:26]:<27}", style=mode)
            t.append(f"{live_ops.short(r['name'], 33):<34}{live_ops.short(r['folder'], 17):<18}"
                     f"{live_ops.age_label(r['age']):<6}{r['aic']:>9,.2f}  {r['pid']:<7}")
            t.append(f"  {live_ops.sparkline(r['counts'][-20:])}\n", style=mode)
        if not rows:
            t.append("No running Copilot CLI sessions.\n", style=st["dim"])
        box.update(t)

    def render_usage(self) -> None:
        u = self.data.get("usage")
        if u is None:
            return
        box = self.query_one("#hm-usage", Static)
        if isinstance(u, Exception):
            return box.update(self._lines([("err", f"Error: {u}")]))
        lines = [("h", f"{u['sessions']} session(s)  {u['calls']:,} calls  {u['tokens']:,} tokens"),
                 ("today", f"AIC {u['aic']:,.2f}   =   ${u['aic'] / 100:,.2f}"),
                 ("hdr", f"{'MODEL':<24}{'CALLS':>7}{'TOKENS':>11}{'AIC':>9}{'COST':>8}")]
        for model, _, calls, toks, aic in u["models"]:
            lines.append(("row", f"{live_ops.short(model or '?', 23):<24}{calls:>7}{toks:>11,}{aic:>9,.2f}{'$' + format(aic / 100, ',.2f'):>8}"))
        if not u["models"]:
            lines.append(("dim", "No Copilot activity yet today"))
        box.update(self._lines(lines))

    def render_cal(self, src: str) -> None:
        ev = self.data.get(f"cal_{src}")
        if ev is None:
            return
        lines = [("err", f"Error: {ev}")] if isinstance(ev, Exception) else \
            home_ops.calendar_lines(ev, self._width(f"#hm-calbox-{src}"))
        self.query_one(f"#hm-cal-{src}", Static).update(self._lines(lines))

    def render_mail(self, src: str) -> None:
        rows = self.data.get(f"mail_{src}")
        if rows is None:
            return
        lines = [("err", f"Error: {rows}")] if isinstance(rows, Exception) else \
            home_ops.mail_lines(rows, self._width(f"#hm-mail-{src}"))
        self.query_one(f"#hm-mail-{src}", Static).update(self._lines(lines))
