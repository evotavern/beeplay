#!/usr/bin/env python3
"""Ship a green pull request to beeplay.top. Run through deploy/push.sh:

    deploy/push.sh 12             briefing, then type "ship": merges PR #12 and releases it
    deploy/push.sh --dry-run 12   the briefing and the server's checks; nothing merged or changed
    deploy/push.sh main           releases main as it is, e.g. after a PR merged on GitHub
    deploy/push.sh rollback       puts the previous release back and opens a revert PR
    deploy/push.sh setup          once per server: installs beeplay-release

The server downloads what it releases straight from GitHub (beeplay-release),
so this laptop only needs GitHub for the pull request itself. "ship" is read
from the terminal, not from a pipe: agents cannot release.
"""

from __future__ import annotations

import base64
import datetime
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = "evotavern/beeplay"
HOST = os.environ.get("BEEPLAY_HOST", "evotavern")
ROOT = Path(__file__).resolve().parent.parent
TESTER = "@李佳蓓"  # Double tests every release on her phone
SUMMARY_MODEL = os.environ.get("BEEPLAY_SUMMARY_MODEL", "claude-sonnet-5")
LARGE_FILES, LARGE_LINES = 25, 800


class Refused(SystemExit):
    pass


def run(args: list[str], *, timeout: int = 60, input: str | None = None, check: bool = True) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input)
    except subprocess.TimeoutExpired:
        raise Refused(f"{args[0]} did not answer within {timeout}s. Nothing was changed; try again.")
    if check and result.returncode != 0:
        raise Refused(f"{' '.join(args[:3])}: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def gh(*args: str, timeout: int = 30) -> str:
    """GitHub, read-only, with one retry: connections from here sometimes stall."""
    try:
        return run(["gh", *args], timeout=timeout)
    except Refused:
        print("GitHub did not answer as expected, trying once more…", file=sys.stderr)
    try:
        return run(["gh", *args], timeout=timeout)
    except Refused as second:
        raise Refused(f"{second}\nIf GitHub is unreachable from here, try again in a minute. "
                      "Nothing was changed.")


def gh_json(*args: str):
    return json.loads(gh(*args) or "null")


def server(*args: str, tty: bool = False, timeout: int = 60) -> str:
    try:
        return run(["ssh", *(["-t"] if tty else []), HOST, "beeplay-release", *args], timeout=timeout)
    except Refused as refusal:
        if "command not found" in str(refusal) or "No such file" in str(refusal):
            raise Refused("the server has no beeplay-release yet: run deploy/push.sh setup")
        raise


# --- facts --------------------------------------------------------------

@dataclass
class Candidate:
    """What a release would put live: a pull request, or main itself."""
    kind: str  # "pr" or "main"
    title: str
    commit: str  # the PR's head, or main's tip
    pr: int | None = None
    node_id: str = ""
    url: str = ""
    author: str = ""
    state: str = "OPEN"
    draft: bool = False
    base: str = "main"
    mergeable: str = "MERGEABLE"
    body: str = ""
    files: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    commits: int = 0
    checks: list[dict] = field(default_factory=list)


def load_pr(number: int) -> Candidate:
    data = gh_json("pr", "view", str(number), "-R", REPO, "--json",
                   "number,id,title,body,url,author,state,isDraft,baseRefName,headRefOid,mergeable,"
                   "files,additions,deletions,commits,statusCheckRollup")
    return Candidate(
        kind="pr", pr=data["number"], node_id=data["id"], title=data["title"], commit=data["headRefOid"],
        url=data["url"], author=(data.get("author") or {}).get("login", "?"), state=data["state"],
        draft=data["isDraft"], base=data["baseRefName"], mergeable=data["mergeable"],
        body=data.get("body") or "", files=[f["path"] for f in data.get("files") or []],
        additions=data.get("additions", 0), deletions=data.get("deletions", 0),
        commits=len(data.get("commits") or []), checks=data.get("statusCheckRollup") or [])


def compare(base: str, head: str) -> dict:
    return gh_json("api", f"repos/{REPO}/compare/{base}...{head}")


def load_main(live: str | None) -> Candidate:
    tip = gh("api", f"repos/{REPO}/branches/main", "--jq", ".commit.sha").strip()
    changed = compare(live, tip) if live else {"files": [], "commits": []}
    return Candidate(
        kind="main", title=f"main as it is ({tip[:7]})", commit=tip,
        files=[f["filename"] for f in changed.get("files") or []],
        additions=sum(f.get("additions", 0) for f in changed.get("files") or []),
        deletions=sum(f.get("deletions", 0) for f in changed.get("files") or []),
        commits=len(changed.get("commits") or []))


def open_prs() -> list[dict]:
    return gh_json("pr", "list", "-R", REPO, "--state", "open", "--limit", "50",
                   "--json", "number,title,author,isDraft,files") or []


def has_ci() -> bool:
    return int(gh("api", f"repos/{REPO}/actions/workflows", "--jq", ".total_count").strip() or 0) > 0


def git_lines(path: str, *args: str) -> list[str]:
    result = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=20)
    return result.stdout.splitlines() if result.returncode == 0 else []


def local_work() -> list[dict]:
    """Worktrees on this laptop with uncommitted or unpushed work, and whether
    a Claude session is running in them."""
    sessions = session_dirs()
    work = []
    listing = git_lines(str(ROOT), "worktree", "list", "--porcelain")
    for path in [line[len("worktree "):] for line in listing if line.startswith("worktree ")]:
        if not os.path.isdir(path):
            continue
        dirty = bool(git_lines(path, "status", "--porcelain", "--untracked-files=no"))
        unpushed = len(git_lines(path, "rev-list", "HEAD", "--not", "--remotes"))
        running = any(s == path or s.startswith(path + os.sep) for s in sessions)
        if dirty or unpushed:
            work.append({"name": os.path.basename(path), "dirty": dirty, "unpushed": unpushed,
                         "session": running})
    return work


def session_dirs() -> list[str]:
    """Working directories of the Claude sessions running here (Linux)."""
    dirs = []
    for pid in subprocess.run(["pgrep", "-f", "claude.*stream-json"], capture_output=True,
                              text=True).stdout.split():
        try:
            dirs.append(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            pass
    return dirs


def summarize(candidate: Candidate, diff: str) -> tuple[list[str], list[str]]:
    """A plain summary for the briefing and what to test, in Chinese, for the
    Lark post. Written by Claude from the diff; falls back to the title and
    says why."""

    def fallback(why: str) -> tuple[list[str], list[str]]:
        return ([f"{candidate.title}  (no summary: {why})"],
                [f"打开 beeplay.top，看看「{candidate.title}」是否正常"])

    prompt = (f"Title: {candidate.title}\n\nDescription:\n{candidate.body[:4000]}\n\n"
              f"Files: {', '.join(candidate.files[:80])}\n\nDiff (may be cut):\n{diff[:60000]}")
    system = ("You describe a change to BeePlay, a mobile-first web feed of small games, for the person "
              "about to release it and for a tester on a phone. Reply with JSON only: "
              '{"summary": ["at most 2 short English lines: what changes for players"], '
              '"test": ["2 to 4 short Chinese lines, each one concrete thing to try on a phone"]}')
    try:
        out = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--max-turns", "1", "--tools", "",
             "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
             "--model", SUMMARY_MODEL, "--system-prompt", system],
            input=prompt, capture_output=True, text=True, timeout=180, cwd=tempfile.gettempdir(),
            # A terminal inside the Claude desktop app inherits the app's
            # session credentials, which the CLI may not use (403): let it use
            # its own login.
            env={k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")})
    except OSError:
        return fallback("claude is not installed here")
    except subprocess.TimeoutExpired:
        return fallback("claude took over 3 minutes")
    try:
        envelope = json.loads(out.stdout)
    except ValueError:
        return fallback(f"claude answered {(out.stderr or out.stdout).strip()[:100]!r}")
    if envelope.get("is_error"):  # e.g. the claude CLI is not logged in here: run `claude` once
        return fallback(f"claude: {str(envelope.get('result') or envelope.get('subtype'))[:100]}")
    try:
        answer = json.loads(re.search(r"\{.*\}", envelope["result"], re.S).group(0))
    except (ValueError, KeyError, TypeError, AttributeError):
        return fallback("claude's answer was not the JSON asked for")
    summary = [str(line) for line in answer.get("summary", [])][:2]
    tests = [str(line) for line in answer.get("test", [])][:4]
    return (summary, tests) if summary and tests else fallback("claude gave no test steps")


# --- judgement ----------------------------------------------------------

@dataclass
class Facts:
    candidate: Candidate
    status: dict  # beeplay-release status
    live_in_main: bool | None  # does main contain the live commit?
    behind_main: int  # commits on main missing from the PR
    ci_exists: bool
    others: list[dict]  # other open PRs
    work: list[dict]  # local worktrees with unpushed work
    summary: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)


def assess(facts: Facts) -> tuple[list[str], list[str]]:
    """Hard stops (no override) and warnings (acknowledged by typing ship)."""
    c, s = facts.candidate, facts.status
    stops, warnings = [], []
    if not s.get("github"):
        stops.append("the server cannot read the repository on GitHub (it has to be public)")
    if s.get("lock"):
        stops.append(f"another release is running: {s['lock']}")
    if not s.get("live") and not str(s.get("live_known_by", "")).startswith("nothing live"):
        stops.append(f"cannot tell what is live ({s.get('live_known_by', '?')})")
    elif facts.live_in_main is False:
        stops.append(f"main does not contain the live {s['live'][:7]}: releasing would take back what "
                     "players have. Merge the live code into main first")
    if c.kind == "pr":
        if c.state != "OPEN":
            stops.append(f"PR #{c.pr} is {c.state.lower()}, not open (to release main, run deploy/push.sh main)")
        if c.draft:
            stops.append(f"PR #{c.pr} is a draft")
        if c.base != "main":
            stops.append(f"PR #{c.pr} is based on {c.base}, not main: merge that first")
        if c.mergeable == "CONFLICTING":
            stops.append(f"PR #{c.pr} conflicts with main")
        if facts.behind_main > 0:
            stops.append(f"PR #{c.pr} is {facts.behind_main} commit(s) behind main: merge main into it first")
    failed = [ch.get("name") or ch.get("context") for ch in c.checks
              if (ch.get("conclusion") or ch.get("state") or "").upper() in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED")]
    pending = [ch.get("name") or ch.get("context") for ch in c.checks
               if (ch.get("status") or "").upper() in ("QUEUED", "IN_PROGRESS", "PENDING")
               or (ch.get("state") or "").upper() == "PENDING"]
    if failed:
        stops.append("tests failed: " + ", ".join(failed))
    elif pending:
        stops.append("tests still running: " + ", ".join(pending))
    elif facts.ci_exists and not c.checks and c.kind == "pr":
        stops.append("the tests have not run on this PR")
    elif not facts.ci_exists:
        warnings.append("no CI yet: nothing has run the tests")

    mine = set(c.files)
    for other in facts.others:
        if other["number"] == c.pr:
            continue
        shared = sorted(mine.intersection(f["path"] for f in other.get("files") or []))
        if shared:
            warnings.append(f"PR #{other['number']} {other['title'][:40]} ({(other.get('author') or {}).get('login', '?')}) "
                            f"also edits {', '.join(shared[:3])}{' …' if len(shared) > 3 else ''}")
    for w in facts.work:
        what = ", ".join(filter(None, [f"{w['unpushed']} unpushed commit(s)" if w["unpushed"] else "",
                                       "uncommitted changes" if w["dirty"] else "",
                                       "a session is running there" if w["session"] else ""]))
        warnings.append(f"worktree {w['name']}: {what}")
    migrations = [f for f in c.files if f.startswith("migrations/versions/")]
    if migrations:
        warnings.append("changes the database: " + ", ".join(os.path.basename(m) for m in migrations))
    if {"pyproject.toml", "uv.lock"}.intersection(c.files):
        warnings.append("changes dependencies")
    touched = [f for f in c.files if f.startswith("deploy/")]
    if touched:
        warnings.append("changes the server setup: " + ", ".join(os.path.basename(f) for f in touched[:5]))
    if len(c.files) > LARGE_FILES or c.additions + c.deletions > LARGE_LINES:
        warnings.append(f"large change: {len(c.files)} files, +{c.additions} −{c.deletions}")
    since = s.get("since_release") or {}
    if since.get("client_error") or since.get("server_error"):
        warnings.append(f"prod since the last release: {since.get('client_error', 0)} page errors, "
                        f"{since.get('server_error', 0)} server errors")
    last = s.get("last") or {}
    if last.get("action") == "rollback":
        which = f" (PR #{last['pr']})" if last.get("pr") else ""
        warnings.append(f"the last release{which} was rolled back: main still has it unless its "
                        "revert PR was merged")
    return stops, warnings


def render(facts: Facts, stops: list[str], warnings: list[str]) -> str:
    c, s = facts.candidate, facts.status

    def tick(ok: bool) -> str:
        return "✓" if ok else "✗"

    lines = [f"BeePlay release · {datetime.datetime.now():%Y-%m-%d %H:%M}"]
    if c.kind == "pr":
        lines.append(f"SHIPPING  PR #{c.pr} {c.title} ({c.author})")
        lines.append(f"          up to date with main {tick(facts.behind_main == 0)} · "
                     f"keeps what's live {tick(facts.live_in_main is not False)} · {c.url}")
    else:
        lines.append(f"SHIPPING  {c.title}")
    live = [(s.get("live") or "unknown")[:7]]
    if s.get("pr"):
        live.append(f"PR #{s['pr']}")
    if s.get("released_at"):
        live.append("since " + s["released_at"][:16].replace("T", " "))
    if s.get("live") and s.get("live_known_by") != "version.json":
        live.append(str(s.get("live_known_by")))
    live.append(f"database {s.get('database', '?')}")
    lines.append("LIVE NOW  " + " · ".join(live))
    assets = sorted({os.path.basename(f) for f in c.files if f.startswith("assets/")})
    lines.append(f"CHANGES   {c.commits} commit(s) · {len(c.files)} files (+{c.additions} −{c.deletions})"
                 f"{' · new file URLs: ' + ', '.join(assets[:5]) if assets else ''}")
    for i, line in enumerate(facts.summary):
        lines.append(("IN SHORT  " if i == 0 else "          ") + line)
    for i, line in enumerate(facts.tests):
        lines.append(("TO TEST   " if i == 0 else "          ") + "• " + line)
    since = s.get("since_release") or {}
    if s.get("released_at"):
        lines.append(f"PROD      since the last release: {since.get('play_ok', 0)} plays ok, "
                     f"{since.get('client_error', 0)} page errors, {since.get('server_error', 0)} server errors")
    else:
        lines.append("PROD      no release on record yet: counts start with this one")
    lines.append("STOPS     " + ("none" if not stops else stops[0]))
    lines.extend("          " + stop for stop in stops[1:])
    lines.append("WARNINGS  " + ("none" if not warnings else "⚠ " + warnings[0]))
    lines.extend("          ⚠ " + warning for warning in warnings[1:])
    return "\n".join(lines)


def lark_post(candidate: Candidate, tests: list[str], when: datetime.datetime) -> str:
    what = f"PR #{candidate.pr} {candidate.title}" if candidate.kind == "pr" else f"{candidate.commits} 个提交"
    lines = [f"🚀 BeePlay 已更新（{when:%H:%M}）：{what}", f"{TESTER} 请在手机上测试："]
    lines += [f"• {line}" for line in tests]
    lines.append("https://beeplay.top")
    if candidate.url:
        lines.append(candidate.url)
    return "\n".join(lines)


# --- commands -----------------------------------------------------------

def ask(question: str) -> str:
    """Read an answer from the terminal itself, never from a pipe."""
    try:
        # Buffered r+ streams require seeking, which terminals do not support.
        with open("/dev/tty", "r") as reader, open("/dev/tty", "w") as writer:
            writer.write(question)
            writer.flush()
            return reader.readline().strip()
    except OSError:
        raise Refused("the ship prompt needs a terminal: run this in the Terminal pane or your own "
                      "terminal. Commands run from a chat or by an agent have none.")


def gather(target: str) -> Facts:
    print("gathering: server, GitHub, this laptop…", file=sys.stderr)
    status = json.loads(server("status"))
    live = status.get("live")
    candidate = load_main(live) if target == "main" else load_pr(int(target))
    main_tip = candidate.commit if candidate.kind == "main" else gh(
        "api", f"repos/{REPO}/branches/main", "--jq", ".commit.sha").strip()
    live_in_main = None
    if live:
        try:
            live_in_main = compare(live, main_tip).get("status") in ("ahead", "identical")
        except Refused:  # e.g. the live commit was never pushed to GitHub
            live_in_main = False
    behind = compare(main_tip, candidate.commit).get("behind_by", 0) if candidate.kind == "pr" else 0
    facts = Facts(candidate, status, live_in_main, behind, has_ci(), open_prs(), local_work())
    diff = gh("pr", "diff", str(candidate.pr), "-R", REPO) if candidate.kind == "pr" else (
        gh("api", "-H", "Accept: application/vnd.github.diff", f"repos/{REPO}/compare/{live}...{main_tip}")
        if live else "")
    facts.summary, facts.tests = summarize(candidate, diff)
    return facts


def ship(target: str, dry_run: bool) -> int:
    facts = gather(target)
    stops, warnings = assess(facts)
    print(render(facts, stops, warnings))
    c = facts.candidate
    if stops:
        raise Refused(f"cannot ship: {len(stops)} hard stop(s) above. Nothing was changed.")
    who = f"{getpass.getuser()}@{socket.gethostname()}"
    if dry_run:
        print("\n== dry run on the server (nothing live changes) ==", flush=True)
        args = ["release", c.commit, "--dry-run", "--by", who] + (["--pr", str(c.pr)] if c.pr else [])
        return subprocess.run(["ssh", "-t", HOST, "beeplay-release", *args]).returncode
    what = f"merge PR #{c.pr} and release it" if c.kind == "pr" else f"release main at {c.commit[:7]}"
    if ask(f'\nType "ship" to {what} (anything else cancels): ') != "ship":
        print("cancelled: nothing was changed")
        return 1
    commit = c.commit
    if c.kind == "pr":
        # --match-head-commit: refuse if the PR moved since the briefing. Not
        # retried: if the answer is lost, the PR's state says what happened.
        try:
            run(["gh", "pr", "merge", str(c.pr), "-R", REPO, "--merge", "--match-head-commit", c.commit],
                timeout=90)
        except Refused:
            if gh("pr", "view", str(c.pr), "-R", REPO, "--json", "state", "--jq", ".state").strip() != "MERGED":
                raise
        commit = ""
        for _ in range(10):
            commit = gh("pr", "view", str(c.pr), "-R", REPO, "--json", "mergeCommit",
                        "--jq", ".mergeCommit.oid").strip()
            if commit:
                break
        if not commit:
            raise Refused(f"PR #{c.pr} merged, but GitHub has not given its merge commit yet: "
                          "run deploy/push.sh main in a minute")
        print(f"merged PR #{c.pr} as {commit[:7]}")
    notes = base64.b64encode(lark_post(c, facts.tests, datetime.datetime.now()).encode()).decode()
    args = ["release", commit, "--by", who, "--notes-b64", notes] + (["--pr", str(c.pr)] if c.pr else [])
    return subprocess.run(["ssh", "-t", HOST, "beeplay-release", *args]).returncode


def rollback() -> int:
    status = json.loads(server("status"))
    live, previous, pr = status.get("live"), status.get("previous"), status.get("pr")
    print(f"live now:  {str(live)[:7]}{f' (PR #{pr})' if pr else ''}\ngoing back to: {str(previous)[:7]}")
    if ask('Type "rollback" to put the previous release back (anything else cancels): ') != "rollback":
        print("cancelled: nothing was changed")
        return 1
    who = f"{getpass.getuser()}@{socket.gethostname()}"
    code = subprocess.run(["ssh", "-t", HOST, "beeplay-release", "rollback", "--by", who]).returncode
    if code == 0 and pr:
        node = gh("pr", "view", str(pr), "-R", REPO, "--json", "id", "--jq", ".id").strip()
        mutation = ("mutation($id: ID!) { revertPullRequest(input: {pullRequestId: $id}) "
                    "{ revertPullRequest { url } } }")
        try:  # not retried: a lost answer must not open a second revert
            url = run(["gh", "api", "graphql", "-f", f"query={mutation}", "-f", f"id={node}",
                       "--jq", ".data.revertPullRequest.revertPullRequest.url"], timeout=60).strip()
            print(f"main still has PR #{pr}: its revert is {url}. Ship that, or a fix.")
        except Refused:
            print(f"main still has PR #{pr}: open its revert on GitHub (Revert button), then ship it.")
    return code


def setup() -> int:
    """Installs beeplay-release, which later releases keep up to date, and
    gives it its copy of the repository. Safe to run again."""
    print("installing beeplay-release on the server…")
    run(["scp", "-q", str(ROOT / "deploy" / "beeplay-release"), f"{HOST}:/tmp/beeplay-release.new"])
    run(["ssh", HOST, "install -m 755 /tmp/beeplay-release.new /usr/local/bin/beeplay-release"
                      " && rm /tmp/beeplay-release.new"])
    main = server("setup", timeout=300).strip().splitlines()[-1]
    print(f"the server reads main from GitHub at {main[:7]}: ready")
    return 0


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    rest = [a for a in argv if a != "--dry-run"]
    if len(rest) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    target = rest[0]
    try:
        if target == "setup":
            return setup()
        if target == "rollback":
            return rollback()
        if target == "main" or target.isdigit():
            return ship(target, dry_run)
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    except Refused as refusal:
        print(f"\n{refusal}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
