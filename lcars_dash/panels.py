"""Detail panels shown in the summary view.

To extend: write a function taking (RepoStatus) and returning Rich markup,
decorate it with @panel("TITLE"). It appears automatically, in order.
"""
from __future__ import annotations

from typing import Callable

from rich.markup import escape

from . import copilot_ops, git_ops, tests_ops
from .git_ops import RepoStatus

PANELS: list[tuple[str, Callable[[RepoStatus], str]]] = []


def panel(title: str):
    def deco(fn):
        PANELS.append((title, fn))
        return fn
    return deco


def _rows(rows, fmt) -> str:
    return "\n".join(fmt(*(escape(c) for c in r)) for r in rows) or "[dim]none[/]"


def _commit(h, a, t, m) -> str:
    return f"[#ff9900]{h}[/] {a} [dim]{t}[/] {m}"


@panel("OVERVIEW")
def overview(s: RepoStatus) -> str:
    flags = []
    if s.behind:
        flags.append(f"[b #ff9900]{s.behind} behind[/]")
    if s.ahead:
        flags.append(f"[b #cc99cc]{s.ahead} ahead[/]")
    if s.dirty:
        flags.append("[b #ff3333]uncommitted changes[/]")
    return (
        f"Viewing: [b #ff9900]{escape(s.view_branch)}[/]   [dim]checked out:[/] {escape(s.branch)}   "
        f"{' '.join(flags) or '[#99ccff]in sync[/]'}\n"
        f"Last commit: {escape(s.last_date)} ({escape(s.last_rel)}) by [b]{escape(s.last_author)}[/]\n"
        f"[dim]{escape(s.last_subject)}[/]\n"
        + (f"[#ff3333]{escape(s.error)}[/]" if s.error else "")
    )


@panel("WORKING TREE")
def working_tree(s: RepoStatus) -> str:
    unmerged = git_ops.unmerged_branches(s.path)
    base = git_ops.default_branch(s.path) or "default branch"
    lines = [
        f"Source: [b]{escape(s.source or '?')}[/]   Path: [dim]{escape(str(s.path))}[/]",
        f"Modified/staged: [b #ff3333]{s.changed}[/]   Untracked: [b #ff3333]{s.untracked}[/]   Stashes: [b]{s.stashes}[/]"
        if (s.changed or s.untracked or s.stashes) else "[#99ccff]Working tree clean, no stashes[/]",
    ]
    if unmerged:
        lines.append(f"Not merged into [b]{escape(base)}[/] ({len(unmerged)}): "
                     + ", ".join(f"[#cc99cc]{escape(b)}[/]" for b in unmerged[:12]) + (" ..." if len(unmerged) > 12 else ""))
    else:
        lines.append(f"[dim]No unmerged local branches (vs {escape(base)})[/]")
    if s.view_branch and s.branch != s.view_branch:
        lines.append(f"[b #ff9900]Note:[/] checked out [b]{escape(s.branch)}[/] but viewing [b]{escape(s.view_branch)}[/]")
    return "\n".join(lines)


@panel("TESTS (x = RUN)")
def tests(s: RepoStatus) -> str:
    cmd = tests_ops.detect(s.path, s.name)
    res = tests_ops.load_results().get(str(s.path))
    head = f"Command: [b]{escape(cmd)}[/]" if cmd else "[dim]No test command detected (set one in ~/.lcars_dash.json)[/]"
    if not res:
        return head + "\n[dim]Never run from the dashboard[/]"
    colour = "#99ccff" if res.get("rc") == 0 else "#ff3333"
    verdict = "N/A" if res.get("rc") is None else ("PASSED" if res["rc"] == 0 else f"FAILED (exit {res['rc']})")
    tail = "\n".join(escape(ln) for ln in res.get("tail", "").splitlines()[-12:])
    return (f"{head}\nLast run: [b {colour}]{verdict}[/] {escape(res.get('when', ''))} "
            f"[dim]({res.get('secs', 0)}s)[/]\n[dim]{tail}[/]")


@panel("PULLED IN LAST REFRESH")
def pulled(s: RepoStatus) -> str:
    return _rows([tuple(l.split(git_ops.SEP)) for l in s.pulled], _commit)


@panel("INCOMING (UPSTREAM, NOT YET PULLED)")
def incoming(s: RepoStatus) -> str:
    return _rows(git_ops.incoming(s.path), _commit)


@panel("RECENT COMMITS (VIEWED BRANCH)")
def recent(s: RepoStatus) -> str:
    return _rows(git_ops.recent_commits(s.path, s.view_branch), _commit)


@panel("RECENTLY ACTIVE BRANCHES")
def branches(s: RepoStatus) -> str:
    return _rows(git_ops.branches(s.path), lambda b, t, a: f"[#cc99cc]{b}[/] [dim]{t}[/] {a}")


@panel("RELEASE TAGS (NEWEST FIRST)")
def release_tags(s: RepoStatus) -> str:
    return _rows(git_ops.tags(s.path),
                 lambda t, d, h, m, gap: f"[#ff9900]{t}[/] [dim]{d}[/] {h} [#cc99cc]{gap}[/] {m}")


@panel("VERSION / RELEASE BRANCHES")
def version_branches(s: RepoStatus) -> str:
    return _rows(git_ops.version_branches(s.path), lambda b, t, a: f"[#cc99cc]{b}[/] [dim]{t}[/] {a}")


@panel("COPILOT SESSIONS IN THIS REPO (p = START / F6 = ALL)")
def copilot_sessions(s: RepoStatus) -> str:
    rows = [((x["updated"] or "")[:16].replace("T", " "), str(x["turns"]), x["summary"] or "(no summary)")
            for x in copilot_ops.sessions(5, under=s.path)]
    return _rows(rows, lambda d, n, t: f"[#ff9900]{d}[/] [dim]{n} turns[/] {t}")


@panel("CONTRIBUTORS (30 DAYS, VIEWED BRANCH)")
def contributors(s: RepoStatus) -> str:
    return "\n".join(f"{c:>4}  {escape(w)}" for c, w in git_ops.authors(s.path, s.view_branch)) or "[dim]none[/]"
