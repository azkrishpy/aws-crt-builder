#!/usr/bin/env python3
"""Changelog fragment tooling: seed, check, render, rollup.

Fragments are the source of truth. CHANGELOG.md is fully regenerated from them
— nothing appends manually.

  .changes/
  ├── preview/<pr>.json      awaiting release; written by the pull request author
  ├── released/<pr>.json      shipped; stamped with its version and date at release
  └── <M>.<N>.x.md            archive of a closed minor line
"""

from fragments import cmd_seed
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
