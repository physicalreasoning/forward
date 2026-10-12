"""The `forward` command: one entry point for every step of a round, and for adding to it.

    forward list                                  tasks and entries, from forward/registry.py
    forward history                               scripts/build_history.py
    forward capture [--out DIR]                   scripts/capture.py
    forward freeze --round N                      scripts/freeze.py
    forward score [--task NAME] [ARGS...]         the task's scorer (default: station-highs)
    forward rehearse DIR                          scripts/rehearse.py
    forward leaderboard                           scripts/leaderboard.py
    forward site [--out FILE]                     scripts/site.py
    forward new entry NAME [--kind gaussian|ladder] [--summary TEXT]
    forward new task NAME [--summary TEXT]

Each step runs the script in the repo, with the arguments after it passed through unchanged, so
`forward score --dry-run 2026-07-01 2026-10-09` is `uv run scripts/score.py --dry-run ...`. The
scripts stay the entry points the scheduled jobs call. Adding a task or an entry:
docs/ADDING.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from . import ROOT, registry, scaffold

SCRIPTS = {
    "history": ("scripts/build_history.py", "gather truth and model archives for fitting"),
    "capture": ("scripts/capture.py", "capture live inputs at the read into a ledger file"),
    "freeze": ("scripts/freeze.py", "fit and hash a round (run once, by the scheduled job)"),
    "rehearse": ("scripts/rehearse.py", "the sealed path on the Round 0 window; must match the dry run"),
    "leaderboard": ("scripts/leaderboard.py", "results/LEADERBOARD.md from results/*.json"),
    "site": ("scripts/site.py", "the results page from results/*.json"),
}


def run(script: str, args: list[str]) -> int:
    return subprocess.call([sys.executable, str(ROOT / script), *args], cwd=ROOT)


def show() -> None:
    for t in registry.TASKS.values():
        print(f"{t.name}: {t.summary}\n  score: {t.score}" + (f"  spec: {t.spec}" if t.spec else ""))
        for e in registry.entries(t.name):
            print(f"  {e.name:26s} {e.kind:8s} {e.source:5s} {e.module:24s} {e.summary}")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="forward", description="Sealed forward tests for world models.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMMAND")
    sub.add_parser("list", help="tasks and entries")
    for name, (_, what) in SCRIPTS.items():
        sub.add_parser(name, help=what, add_help=False)
    sc = sub.add_parser("score", help="score a task (arguments pass through to its scorer)", add_help=False)
    sc.add_argument("--task", default="station-highs", choices=sorted(registry.TASKS))
    new = sub.add_parser("new", help="scaffold and register a new entry or task").add_subparsers(
        dest="what", required=True, metavar="WHAT"
    )
    ne = new.add_parser("entry", help="forward/entry_NAME.py and its test, for station highs")
    ne.add_argument("name")
    ne.add_argument("--kind", choices=["gaussian", "ladder"], default="gaussian")
    ne.add_argument("--summary", default="")
    nt = new.add_parser("task", help="forward/tasks/NAME.py and its test")
    nt.add_argument("name")
    nt.add_argument("--summary", default="")
    return ap


def main(argv: list[str] | None = None) -> int:
    a, rest = parser().parse_known_args(argv)
    if a.cmd in SCRIPTS:
        return run(SCRIPTS[a.cmd][0], rest)
    if a.cmd == "score":
        return run(registry.TASKS[a.task].score, rest)
    if rest:
        parser().error(f"unrecognized arguments: {' '.join(rest)}")
    if a.cmd == "list":
        show()
        return 0
    if a.what == "entry":
        paths = scaffold.new_entry(a.name, a.kind, a.summary)
    else:
        paths = scaffold.new_task(a.name, a.summary)
    for p in paths:
        print("wrote", p.relative_to(ROOT))
    print("registered in forward/registry.py; next: docs/ADDING.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
