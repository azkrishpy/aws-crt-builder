#!/usr/bin/env python3
"""Changelog fragment tooling: seed, check, render, rollup.

Fragments are the source of truth. CHANGELOG.md is fully regenerated from them
— nothing appends manually.

  .changes/
  ├── preview/<pr>.json      awaiting release; written by the pull request author
"""
import argparse
import json
import re
import sys
from pathlib import Path
VALID_TYPES = {"feat", "fix", "chore", "revert"}
# Section order. chore has no row: documentation and maintenance are internal,
# so requiring a fragment would force authors to write text no customer reads.
CATEGORY = {"feat": "Features", "fix": "Fixes", "revert": "Reverts"}
# A fragment the ABI check called `minor` renders here instead of its own type
# section: a consumer may have to change something to take the release.
BREAKING_SECTION = "Possible Breaking Changes"

# Every accepted type either renders or is chore. Without this, narrowing the
# type set would silently drop released entries from a regenerated file.
assert set(CATEGORY) | {"chore"} == VALID_TYPES
TITLE_RE = re.compile(
    r"^(feat|fix|chore|revert)(?:\([^)]+\))?:\s*(.+)$", re.IGNORECASE
)
# GitHub's Revert button generates `Revert "<original title> (#<n>)"`, which
# carries no `<type>:` prefix. Accepting it verbatim means a maintainer using
# the button never has to retitle; the author still writes the fragment, since
# only they can say WHY it was reverted.
REVERT_TITLE_RE = re.compile(r'^revert\s+"(.+)"\s*$', re.IGNORECASE)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ---------- parsing / schema ----------

def parse_title(title):
    title = title.strip()
    m = TITLE_RE.match(title)
    if m:
        return m.group(1).lower(), m.group(2).strip()
    m = REVERT_TITLE_RE.match(title)
    if m:
        return "revert", m.group(1).strip()
    return None, title
REQUIRED_FRAGMENT = {"pr", "type", "summary", "url"}
def validate_fragment(path):
    errs = []
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path}: invalid JSON: {e}"]
    for k in sorted(REQUIRED_FRAGMENT - set(data)):
        errs.append(f"{path}: missing field: {k}")
    if data.get("type") not in VALID_TYPES:
        errs.append(f"{path}: type must be one of {sorted(VALID_TYPES)}")
    s = data.get("summary")
    if not isinstance(s, str) or not s.strip():
        errs.append(f"{path}: summary must be non-empty string")
    pr = data.get("pr")
    if not isinstance(pr, int) or isinstance(pr, bool):
        errs.append(f"{path}: pr must be int")
    elif pr <= 0:
        # A placeholder renders as a dead `(#0)` reference.
        errs.append(f"{path}: pr must be the real pull request number, not {pr}")
    u = data.get("url")
    if not isinstance(u, str) or not u.strip():
        errs.append(f"{path}: url must be non-empty string")
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        errs.append(f"{path}: notes must be a string")
    elif data.get("type") == "revert" and not notes.strip():
        # The whole reason a revert needs its own entry is to say why.
        errs.append(f"{path}: a revert needs notes explaining why")
    return errs


def parse_semver(s):
    m = SEMVER_RE.match(s)
    if not m:
        raise ValueError(f"not a semver x.y.z: {s!r}")
    return tuple(int(g) for g in m.groups())
def fmt_semver(t):
    return ".".join(str(x) for x in t)
# ---------- commands ----------

def cmd_seed(args):
    if args.pr <= 0:
        _err(f"--pr must be the real pull request number, not {args.pr}")
        return 2
    typ, summary = parse_title(args.title)
    if typ is None:
        typ = "chore"
    if typ == "revert":
        # The button's title is `Revert "<original title> (#N)"`; neither the
        # original type prefix nor its number belongs in this entry.
        summary = re.sub(r"^(feat|fix|chore|revert)(\([^)]+\))?:\s*", "", summary,
                         flags=re.IGNORECASE)
        summary = re.sub(r"\s*\(#\d+\)\s*$", "", summary)
        if not summary.lower().startswith("revert"):
            summary = f"Reverted {summary}"
    frag = {"pr": args.pr, "type": typ, "summary": summary, "url": args.url,
            "notes": ""}
    out = Path(args.changes_dir) / "preview" / f"{args.pr}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not args.force:
        # Non-zero, so a caller cannot mistake "declined" for "wrote it".
        print(f"exists (use --force to overwrite): {out}", file=sys.stderr)
        return 1
    out.write_text(json.dumps(frag, indent=2) + "\n")
    print(str(out))
    return 0
def _err(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
# ---------- CLI ----------

def main(argv=None):
    p = argparse.ArgumentParser(prog="changelog")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed",
                       help="create a fragment for a PR (usually via new-change helper)")
    s.add_argument("--pr", type=int, required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--url", required=True)
    s.add_argument("--changes-dir", default=".changes")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_seed)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
