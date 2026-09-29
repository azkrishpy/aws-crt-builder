#!/usr/bin/env python3
"""Changelog fragment tooling: seed, check, render, rollup.

Fragments are the source of truth. CHANGELOG.md is fully regenerated from them
— nothing appends manually.

  .changes/
  ├── preview/<pr>.json      awaiting release; written by the pull request author
  ├── released/<pr>.json      shipped; stamped with its version and date at release
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
REQUIRED_FRAGMENT = {"pr", "type", "summary", "url"}
def validate_fragment(path, released=False):
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
    if "impact" in data and data["impact"] != "minor":
        errs.append(f'{path}: impact, when present, must be "minor"')
    if "version" in data and not SEMVER_RE.match(str(data["version"])):
        errs.append(f"{path}: version, when present, must be x.y.z")
    if "date" in data and not ISO_DATE_RE.match(str(data["date"])):
        errs.append(f"{path}: date, when present, must be YYYY-MM-DD")
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        errs.append(f"{path}: notes must be a string")
    elif data.get("type") == "revert" and not notes.strip():
        # The whole reason a revert needs its own entry is to say why.
        errs.append(f"{path}: a revert needs notes explaining why")
    if released:
        # Without the stamp the entry groups under no version, so it renders
        # nowhere -- a published entry silently disappearing.
        errs += [f"{path}: released fragment is missing {k}"
                 for k in ("version", "date") if k not in data]
    return errs
def parse_semver(s):
    m = SEMVER_RE.match(s)
    if not m:
        raise ValueError(f"not a semver x.y.z: {s!r}")
    return tuple(int(g) for g in m.groups())
def fmt_semver(t):
    return ".".join(str(x) for x in t)
# ---------- render primitives ----------

SENTENCE_END = (".", "!", "?")
def pr_link(frag):
    """`#843` linked to the pull request, so an archived file still resolves."""
    return f"[#{frag['pr']}]({frag['url']})"
def render_entry(frag):
    summary = frag["summary"].strip()
    if not summary.endswith(SENTENCE_END):
        summary += "."
    return f"- {summary} ({pr_link(frag)})"
def render_note(frag):
    """A note is its own entry, led by the pull request it explains."""
    body = frag["notes"].strip().splitlines()
    return "\n  ".join([f"- {pr_link(frag)} — {body[0]}", *body[1:]])
def _section(heading, entries, render):
    if not entries:
        return []
    return [f"### {heading}",
            *(render(e) for e in sorted(entries, key=lambda f: f["pr"])), ""]
def render_grouped(fragments):
    """Sections in a fixed order, each omitted when it would be empty."""
    breaking = [f for f in fragments if f.get("impact") == "minor"]
    lines = _section(BREAKING_SECTION, breaking, render_entry)
    for typ, cat in CATEGORY.items():
        rest = [f for f in fragments
                if f["type"] == typ and f.get("impact") != "minor"]
        lines += _section(cat, rest, render_entry)
    lines += _section("Notes", [f for f in fragments if f.get("notes", "").strip()],
                      render_note)
    return "\n".join(lines).rstrip() + "\n" if lines else ""
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
def _release_sections(groups):
    out = []
    for version, frags in groups:
        body = render_grouped(frags)
        # A release whose every fragment was a chore renders nothing, and a bare
        # header reads as a broken file.
        if body:
            out += [f"## [{version}] — {frags[0]['date']}", "", body.rstrip(), ""]
    return out
def render_root_changelog(changes_dir, preview=True, docs_branch="docs"):
    """The whole rendered file.

    `preview=True` is the docs-branch shape: it leads with the in-flight block,
    and something regenerates it on every merge. The release branch gets
    `preview=False`, because only a release rewrites the file there and a
    Preview block would sit permanently stale.
    """
    body = ["# Changelog", ""]
    if preview:
        body += [
            "## [Preview]",
            "",
            (render_grouped(load_dir(Path(changes_dir) / "preview"))
             or "_Nothing yet._\n").rstrip(),
            "",
        ]
    else:
        # The relative link resolves from /owner/repo/blob/<branch>/CHANGELOG.md,
        # so it only reaches the repo root when the branch name is a single path
        # segment. A branch with a slash in it gets the name without a link.
        pointer = (f"[`{docs_branch}`](../../tree/{docs_branch}/CHANGELOG.md)"
                   if "/" not in docs_branch else f"`{docs_branch}`")
        body += [f"Unreleased changes are rendered on the {pointer} branch.", ""]
    body += _release_sections(releases(changes_dir))
    frozen = frozen_lines(changes_dir)
    if frozen:
        rel = Path(changes_dir).name
        body += ["## Earlier releases", ""]
        body += [f"- [{f.stem}]({rel}/{f.name})" for f in frozen]
        body.append("")
    return "\n".join(body).rstrip() + "\n"
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
def _release_preview(changes, version, date, minor_prs):
    """Stamp each preview fragment with its release and move it to released/."""
    out = changes / "released"
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted((changes / "preview").glob("*.json")):
        data = json.loads(f.read_text())
        data["version"], data["date"] = version, date
        # The ABI verdict lives on the pull request, not in the fragment the
        # author wrote. Stamp it in as the fragment is released, so every later
        # re-render reaches the same answer without asking GitHub.
        if data.get("pr") in minor_prs:
            data["impact"] = "minor"
        (out / f.name).write_text(json.dumps(data, indent=2) + "\n")
        f.unlink()
def cmd_render(args):
    if audit_released(args.changes_dir):
        return 2
    Path(args.changelog).write_text(
        render_root_changelog(args.changes_dir, preview=True))
    print(f"rendered → {args.changelog}")
    return 0
def cmd_rollup(args):
    """Move every preview fragment into released/, stamped with this release."""
    changes = Path(args.changes_dir)
    if audit_released(changes):
        return 2

    try:
        new = parse_semver(args.version)
    except ValueError as e:
        _err(str(e))
        return 2
    if not ISO_DATE_RE.match(args.date):
        _err(f"--date must be YYYY-MM-DD, got {args.date!r}")
        return 2

    preview_dir = changes / "preview"
    on_disk = sorted(preview_dir.glob("*.json")) if preview_dir.exists() else []
    # An empty preview/ is a valid release: a patch of nothing but chores is
    # routine, and failing here would fail the release job after it has tagged.
    preview = load_dir(preview_dir)
    if len(preview) != len(on_disk):
        # Releasing anyway would move the rejected files into released/, where
        # they render nowhere and are never looked at again.
        _err(f"{len(on_disk) - len(preview)} of {len(on_disk)} fragment(s) in "
             f"{preview_dir} are invalid (see the warnings above); fix them first")
        return 2

    _release_preview(changes, args.version, args.date,
                     {int(p) for p in args.minor_prs.split(",") if p.strip()})
    Path(args.changelog).write_text(
        render_root_changelog(changes, preview=False, docs_branch=args.docs_branch))
    print(f"rolled up {len(preview)} fragment(s) into {args.version}")
    return 0


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
