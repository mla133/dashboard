"""Git helpers: discovery, status, and refresh. No UI code here."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path.home() / "SoftwareDevelopment"
SEP = "\x1f"


def git(repo: Path, *args: str, timeout: int = 120) -> tuple[int, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, env=env,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, str(e)
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr or p.stdout).strip()


def discover(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted((d for d in root.iterdir() if (d / ".git").exists()), key=lambda d: d.name.lower())


def discover_all(roots: list[Path], depth: int = 2) -> list[tuple[Path, str]]:
    """Repos under several roots (up to `depth` folders down) as (path, unique display name)."""
    found: list[Path] = []
    seen: set[str] = set()

    def walk(d: Path, level: int, inside_repo: bool = False) -> None:
        try:
            kids = sorted((k for k in d.iterdir() if k.is_dir() and not k.name.startswith(".")
                           and k.name not in ("node_modules", "venv", "__pycache__")),
                          key=lambda k: k.name.lower())
        except OSError:
            return
        for k in kids:
            if (k / ".git").exists():
                if inside_repo and not (k / ".git").is_dir():
                    continue  # submodule, not a separate clone
                key = str(k.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    found.append(k)
                if level < depth:
                    walk(k, level + 1, True)
            elif level < depth:
                walk(k, level + 1, inside_repo)

    for r in roots:
        walk(r, 1)
    counts: dict[str, int] = {}
    for p in found:
        counts[p.name.lower()] = counts.get(p.name.lower(), 0) + 1
    out = [(p, p.name if counts[p.name.lower()] == 1 else f"{p.parent.name}/{p.name}") for p in found]
    return sorted(out, key=lambda t: t[1].lower())


def source_of(path: Path) -> str:
    rc, out = git(path, "remote", "get-url", "origin")
    if rc != 0:
        rc, remotes = git(path, "remote")
        if rc != 0 or not remotes:
            return "LOCAL"
        rc, out = git(path, "remote", "get-url", remotes.splitlines()[0])
        if rc != 0:
            return "LOCAL"
    low = out.lower()
    if "assembla" in low:
        return "ASSEMBLA"
    if "github" in low:
        return "GITHUB"
    for host in ("gitlab", "bitbucket", "dev.azure", "visualstudio"):
        if host in low:
            return host.split(".")[0].upper()
    return "REMOTE"


def default_branch(path: Path) -> str:
    rc, out = git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out:
        return out
    for cand in ("main", "master"):
        if git(path, "rev-parse", "--verify", "--quiet", f"refs/heads/{cand}")[0] == 0:
            return cand
    return ""


def unmerged_branches(path: Path) -> list[str]:
    base = default_branch(path)
    if not base:
        return []
    rc, out = git(path, "branch", "--no-merged", base, "--format=%(refname:short)")
    return [b for b in out.splitlines() if b and b != base] if rc == 0 else []


@dataclass
class RepoStatus:
    name: str
    path: Path
    branch: str = "?"  # checked out
    view_branch: str = ""  # branch being displayed
    last_date: str = "-"
    last_rel: str = "-"
    last_author: str = "-"
    last_subject: str = ""
    behind: int = 0
    ahead: int = 0
    dirty: bool = False
    source: str = ""  # ASSEMBLA / GITHUB / LOCAL / host name
    changed: int = 0  # tracked files modified or staged
    untracked: int = 0
    stashes: int = 0
    unmerged: int = 0  # local branches not merged into the default branch
    error: str = ""
    pulled: list[str] = field(default_factory=list)  # commit lines from last refresh


def branch_names(path: Path) -> list[str]:
    """Local and remote branch names (remote prefix stripped), most recently updated first."""
    _, out = git(path, "for-each-ref", "--sort=-committerdate", "--format=%(refname)", "refs/heads", "refs/remotes")
    names: list[str] = []
    for ref in out.splitlines():
        if ref.startswith("refs/heads/"):
            n = ref[len("refs/heads/"):]
        elif ref.startswith("refs/remotes/"):
            n = ref[len("refs/remotes/"):].partition("/")[2]
        else:
            continue
        if n and n != "HEAD" and n not in names:
            names.append(n)
    return names


def resolve_ref(path: Path, name: str) -> str:
    if git(path, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")[0] == 0:
        return f"refs/heads/{name}"
    _, out = git(path, "for-each-ref", "--format=%(refname)", f"refs/remotes/*/{name}")
    return out.splitlines()[0] if out else "HEAD"


def read_status(path: Path, view: str | None = None, name: str | None = None) -> RepoStatus:
    s = RepoStatus(name=name or path.name, path=path)
    s.source = source_of(path)
    names = branch_names(path)
    s.view_branch = view if view in names else (names[0] if names else "")
    ref = resolve_ref(path, s.view_branch) if s.view_branch else "HEAD"
    rc, out = git(path, "log", "-1", ref, f"--format=%ad{SEP}%ar{SEP}%an{SEP}%s", "--date=format:%Y-%m-%d %H:%M")
    if rc != 0:
        s.error = out.splitlines()[0] if out else "no commits"
        return s
    s.last_date, s.last_rel, s.last_author, s.last_subject = (out.split(SEP) + [""] * 4)[:4]
    rc, out = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    s.branch = out if rc == 0 else "?"
    rc, out = git(path, "rev-list", "--left-right", "--count", "@{u}...HEAD")
    if rc == 0:
        b, a = out.split()
        s.behind, s.ahead = int(b), int(a)
    rc, out = git(path, "status", "--porcelain")
    lines = out.splitlines() if rc == 0 else []
    s.dirty = bool(lines)
    s.untracked = sum(1 for ln in lines if ln.startswith("??"))
    s.changed = len(lines) - s.untracked
    rc, out = git(path, "stash", "list")
    s.stashes = len(out.splitlines()) if rc == 0 and out else 0
    s.unmerged = len(unmerged_branches(path))
    return s


def refresh(path: Path, view: str | None = None, name: str | None = None) -> RepoStatus:
    """Fetch all remotes, fast-forward the current branch, report pulled commits."""
    _, old = git(path, "rev-parse", "HEAD")
    rc, out = git(path, "fetch", "--all", "--prune", "--tags", timeout=300)
    err = "" if rc == 0 else f"fetch: {out.splitlines()[0] if out else 'failed'}"
    has_upstream = git(path, "rev-parse", "--abbrev-ref", "@{u}")[0] == 0
    if not err and has_upstream:  # detached/untracked branches: fetch only
        rc, out = git(path, "pull", "--ff-only", timeout=300)
        if rc != 0:
            err = f"pull: {out.splitlines()[0] if out else 'failed'}"
    s = read_status(path, view, name)
    _, new = git(path, "rev-parse", "HEAD")
    if old != new:
        _, log = git(path, "log", f"{old}..{new}", f"--format=%h{SEP}%an{SEP}%ar{SEP}%s", "-50")
        s.pulled = [ln for ln in log.splitlines() if ln]
    s.error = err
    return s


# --- data used by detail panels -------------------------------------------

def recent_commits(path: Path, branch: str, n: int = 15) -> list[tuple[str, ...]]:
    _, out = git(path, "log", resolve_ref(path, branch), f"-{n}", f"--format=%h{SEP}%an{SEP}%ar{SEP}%s")
    return [tuple(ln.split(SEP)) for ln in out.splitlines() if SEP in ln]


def branches(path: Path, n: int = 12) -> list[tuple[str, ...]]:
    _, out = git(
        path, "for-each-ref", "--sort=-committerdate", f"--count={n}",
        f"--format=%(refname:short){SEP}%(committerdate:relative){SEP}%(authorname)", "refs/heads", "refs/remotes",
    )
    return [tuple(ln.split(SEP)) for ln in out.splitlines() if SEP in ln]


def authors(path: Path, branch: str, days: int = 30) -> list[tuple[int, str]]:
    _, out = git(path, "shortlog", "-sn", f"--since={days} days ago", resolve_ref(path, branch))
    rows = []
    for ln in out.splitlines():
        c, _, who = ln.strip().partition("\t")
        if c.isdigit():
            rows.append((int(c), who))
    return rows[:8]


VERSION_RE = r"(\d+\.\d+|release|rebuild|hotfix|v\d)"


def tags(path: Path, n: int = 15) -> list[tuple[str, ...]]:
    """Newest tags first: (tag, date, short hash, subject, commits since previous tag)."""
    _, out = git(path, "for-each-ref", "--sort=-creatordate", f"--count={n + 1}",
                 f"--format=%(refname:short){SEP}%(creatordate:short){SEP}%(objectname:short){SEP}%(subject)", "refs/tags")
    rows = [ln.split(SEP) for ln in out.splitlines() if SEP in ln]
    result = []
    for i, r in enumerate(rows[:n]):
        gap = ""
        if i + 1 < len(rows):
            rc, cnt = git(path, "rev-list", "--count", f"{rows[i + 1][0]}..{r[0]}")
            gap = f"+{cnt}" if rc == 0 else ""
        result.append((r[0], r[1], r[2], r[3] if len(r) > 3 else "", gap))
    return result


def version_branches(path: Path, n: int = 15) -> list[tuple[str, ...]]:
    """Branches that look like release/version lines: (name, relative date, last author)."""
    import re
    rows = [b for b in branches(path, 200) if re.search(VERSION_RE, b[0], re.I)]
    return rows[:n]


def incoming(path: Path, n: int = 15) -> list[tuple[str, ...]]:
    """Commits on upstream not yet pulled."""
    _, out = git(path, "log", "HEAD..@{u}", f"-{n}", f"--format=%h{SEP}%an{SEP}%ar{SEP}%s")
    return [tuple(ln.split(SEP)) for ln in out.splitlines() if SEP in ln]
