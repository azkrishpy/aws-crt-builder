"""The fragment: its schema, how one is validated, and how a tree of them is
loaded and grouped into the releases they shipped in."""

from pathlib import Path
import json
import re
import sys


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


LINE_FILE_RE = re.compile(r"^(\d+)\.(\d+)\.x\.md$")


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


REQUIRED_FRAGMENT = {"pr", "type", "summary"}


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
        # Whether the number is a real pull request cannot be settled here: this
        # runs with no token and no network. `check` does settle it, by asserting
        # the fragment agrees with the --pr the caller was triggered for. What is
        # left is the placeholder, which renders as a dead `(#0)` reference.
        errs.append(f"{path}: pr must be the real pull request number, not {pr}")
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


# ---------- fragment IO ----------

def _load_valid_fragment(path):
    errs = validate_fragment(path)
    data = {}
    if not errs:
        data = json.loads(Path(path).read_text())
        stem = Path(path).stem
        if stem.isdigit() and data.get("pr") != int(stem):
            errs.append(f"{path}: pr {data.get('pr')!r} does not match the filename")
    if errs:
        for e in errs:
            print(f"WARN: skipping {e}", file=sys.stderr)
        return None
    return data


def load_dir(d):
    """Every valid fragment in one directory; invalid ones warn and drop out."""
    d = Path(d)
    if not d.exists():
        return []
    return [f for f in map(_load_valid_fragment, sorted(d.glob("*.json")))
            if f is not None]


def releases(changes_dir):
    """Released fragments grouped as (version, fragments), newest release first."""
    by_version = {}
    for frag in load_dir(Path(changes_dir) / "released"):
        by_version.setdefault(str(frag.get("version", "")), []).append(frag)
    return sorted(((v, f) for v, f in by_version.items() if SEMVER_RE.match(v)),
                  key=lambda kv: parse_semver(kv[0]), reverse=True)


def frozen_lines(changes_dir):
    """Archive files for closed minor lines, newest line first."""
    d = Path(changes_dir)
    if not d.exists():
        return []
    files = [f for f in d.iterdir() if LINE_FILE_RE.match(f.name)]
    return sorted(files, key=lambda f: _line_of(f.name), reverse=True)


def _line_of(name):
    return tuple(int(x) for x in LINE_FILE_RE.match(name).groups())


def audit_released(changes_dir):
    """Report released fragments that would not render. True if any did.

    A released fragment is a published entry: if it fails the schema or lost its
    version stamp, it silently vanishes from the regenerated file. Every caller
    that writes a changelog stops instead.
    """
    errs = [e for f in sorted((Path(changes_dir) / "released").glob("*.json"))
            for e in validate_fragment(f, released=True)]
    for e in errs:
        _err(e)
    return bool(errs)


# ---------- commands ----------
#
# One `cmd_<verb>` per CLI subcommand, wired to its subparser in main(). Each
# returns the process exit code rather than raising, so a caller in a shell step
# can branch on it. Everything above this line is a pure function of its inputs;
# these are the only entry points that read argv or write files.

def cmd_seed(args):
    """Write the template the bot comments with when a fragment is missing.

    The counterpart to validate_fragment, not a duplicate of it: this produces a
    fragment and validation consumes one. It exists for the two fields a comment
    cannot state generically -- the type, derived from the title prefix, and a
    revert's summary, derived from the Revert button's generated title.

    The output is never the author's file. It goes to --out, outside the tree the
    check reads, and the author copies it from the comment. So it writes without
    validating: the summary is a starting point they are expected to rewrite, and
    `check` is what refuses a bad one at the gate.
    """
    if args.pr <= 0:
        _err(f"--pr must be the real pull request number, not {args.pr}")
        return 2
    pr_type, summary = parse_title(args.title)
    if pr_type is None:
        pr_type = "chore"
    if pr_type == "revert":
        # The button's title is `Revert "<original title> (#N)"`; neither the
        # original type prefix nor its number belongs in this entry.
        summary = re.sub(r"^(feat|fix|chore|revert)(\([^)]+\))?:\s*", "", summary,
                         flags=re.IGNORECASE)
        summary = re.sub(r"\s*\(#\d+\)\s*$", "", summary)
        if not summary.lower().startswith("revert"):
            summary = f"Reverted {summary}"
    frag = {"pr": args.pr, "type": pr_type, "summary": summary, "notes": ""}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(frag, indent=2) + "\n")
    print(str(out))
    return 0


def _err(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
