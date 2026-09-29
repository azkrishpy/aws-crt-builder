#!/usr/bin/env python3
"""Changelog fragment tooling: seed, check, render, rollup.

Fragments are the source of truth. CHANGELOG.md is fully regenerated from them
— nothing appends manually.

  .changes/
  ├── preview/<pr>.json      awaiting release; written by the pull request author
  ├── released/<pr>.json      shipped; stamped with its version and date at release
  └── <M>.<N>.x.md            archive of a closed minor line
"""

from check import cmd_check
from fragments import cmd_seed
from release import cmd_rollup
from render import cmd_render
import argparse
import sys


# ---------- CLI ----------

def main(argv=None):
    p = argparse.ArgumentParser(prog="changelog")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed",
                       help="write the template a missing fragment should be filled from")
    s.add_argument("--pr", type=int, required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--out", required=True,
                   help="Where to write it; never inside the changes directory.")
    s.set_defaults(func=cmd_seed)

    c = sub.add_parser("check", help="CI: assert the PR title and its fragment are valid")
    c.add_argument("--pr", type=int, required=True)
    c.add_argument("--title", default="", help="PR title; the change type is derived from it")
    c.add_argument("--bot-author", default="",
                   help="login of the PR author when it is a bot; waives both checks")
    c.add_argument("--changes-dir", default=".changes")
    c.add_argument("--changed-paths-file", default="",
                   help="file of `status<TAB>path` lines for the PR's changes under .changes/")
    c.add_argument("--changes-prefix", default=".changes",
                   help="repo-relative changes directory, for matching changed paths")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("render", help="regenerate CHANGELOG.md from preview/ + released/")
    r.add_argument("--changes-dir", default=".changes")
    r.add_argument("--changelog", default="CHANGELOG.md")
    r.set_defaults(func=cmd_render)

    u = sub.add_parser("rollup",
                       help="cut a release: a minor archives the outgoing line")
    u.add_argument("--version", required=True)
    u.add_argument("--date", required=True)
    u.add_argument("--changes-dir", default=".changes")
    u.add_argument("--changelog", default="CHANGELOG.md")
    u.add_argument("--docs-branch", default="docs",
                   help="Branch named in the pointer to the in-flight changelog.")
    u.add_argument("--minor-prs", default="",
                   help="Comma-separated PRs the ABI check labelled `minor`; "
                        "their entries render under Possible Breaking Changes.")
    u.set_defaults(func=cmd_rollup)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
