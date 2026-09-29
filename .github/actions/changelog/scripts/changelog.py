#!/usr/bin/env python3
"""Changelog fragment tooling: seed, check, render, rollup.

Fragments are the source of truth. CHANGELOG.md is fully regenerated from them
— nothing appends manually.

  .changes/
  ├── preview/<pr>.json      awaiting release; written by the pull request author
  ├── released/<pr>.json      shipped; stamped with its version and date at release
  └── <M>.<N>.x.md            archive of a closed minor line
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

# Release-time fields. The author writes none of them: `impact` decides whether
# an entry lands under Possible Breaking Changes, so accepting it from a pull
# request would let that pull request classify itself.
STAMPED = ("version", "date", "impact")

# No changelog before this. Everything earlier shipped without fragments, so a
# rollup of it would render a release whose entries do not exist.
FIRST_VERSION = (1, 0, 0)

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


def render_line_archive(line, groups):
    """A self-contained file for a minor line that will take no more releases."""
    body = [f"# Changelog — {line}", "",
            "Current releases are in the [top-level changelog](../CHANGELOG.md).", ""]
    return "\n".join(body + _release_sections(groups)).rstrip() + "\n"


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


def parse_changed_paths(path, prefix):
    """Read `status<TAB>path` lines, keeping only entries under `prefix`."""
    out = []
    for line in Path(path).read_text().splitlines():
        status, _, p = line.strip().partition("\t")
        if p.startswith(f"{prefix}/"):
            out.append((status, p))
    return out


def check_fragment_changes(args, typ, reason):
    """Assert the PR's changes under `prefix` are exactly one new fragment.

    Returns an exit code to stop on, or None to carry on with the usual checks.
    """
    prefix = args.changes_prefix.rstrip("/")
    expected = f"{prefix}/preview/{args.pr}.json"
    entries = parse_changed_paths(args.changed_paths_file, prefix)

    if not entries:
        # Nothing under .changes/ at all -- the normal "author forgot" case,
        # which the fragment check below reports and which earns a template.
        return None

    wrong = [(st, p) for st, p in entries if p != expected]
    if wrong:
        listed = "\n".join(f"         {st:<10} {p}" for st, p in wrong)
        print(
            f"ERROR: a `{typ}` change may only add its own changelog fragment.\n"
            f"       expected exactly one new file:\n"
            f"         added      {expected}\n"
            f"       but this pull request also changes:\n{listed}\n"
            f"       A fragment named for another pull request renders under that\n"
            f"       number; one at another path renders nowhere, and a released\n"
            f"       entry is already published.",
            file=sys.stderr,
        )
        reason("stray-fragment")
        return 1

    status = entries[0][0]
    if status != "added":
        print(
            f"ERROR: {expected} is `{status}` in this pull request, not `added`.\n"
            f"       That path already exists on the base branch, so this pull\n"
            f"       request is rewriting a released or in-flight entry rather than\n"
            f"       contributing its own. Move the change to a new fragment.",
            file=sys.stderr,
        )
        reason("modified-fragment")
        return 1

    return None


def cmd_check(args):
    """CI gate. Exit 0 pass, 1 author-fixable, 2 caller error.

    Two independent assertions:
      * the PR title follows the convention, so a type can be derived at all;
      * a fragment exists and agrees with that type -- unless the type is
        exempt (chore), or the author is a bot we waive.
    """
    title = (args.title or "").strip()
    frag = Path(args.changes_dir) / "preview" / f"{args.pr}.json"

    # A single machine-readable reason on stdout, so a caller can tell an
    # author who does not know the convention (missing-fragment -> show them a
    # template) from one who does (everything else -> just the diagnostic).
    def reason(tag):
        print(f"CHANGELOG_CHECK_REASON::{tag}")

    if args.bot_author:
        print(f"OK: #{args.pr} is authored by a bot ({args.bot_author}); "
              "title convention and changelog fragment both waived")
        reason("waived-bot")
        return 0

    if not title:
        print("ERROR: --title is required to derive the change type", file=sys.stderr)
        return 2

    typ, _summary = parse_title(title)
    if typ is None:
        print(
            f'ERROR: PR title does not follow the convention: "{title}"\n'
            f"       expected `<type>: <summary>` with type one of "
            f"{sorted(VALID_TYPES)}, an optional scope such as `chore(ci):`,\n"
            f'       or the Revert button\'s `Revert "<original title>"`.',
            file=sys.stderr,
        )
        reason("bad-title")
        return 1

    if typ not in CATEGORY:
        print(f"OK: #{args.pr} is a `{typ}` change; no changelog fragment required")
        reason("exempt-type")
        return 0

    if args.changed_paths_file:
        rc = check_fragment_changes(args, typ, reason)
        if rc is not None:
            return rc

    if not frag.exists():
        print(
            f"ERROR: no changelog fragment for PR #{args.pr}.\n"
            f"       expected: {frag}\n"
            f"       a `{typ}` change is customer-visible, so it needs an entry.\n"
            f"       commit that file with this pull request -- the bot comments a\n"
            f"       ready-to-paste template.",
            file=sys.stderr,
        )
        reason("missing-fragment")
        return 1

    errs = validate_fragment(frag)
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        reason("invalid-fragment")
        return 1

    data = json.loads(frag.read_text())
    stamped = [k for k in STAMPED if k in data]
    if stamped:
        print(
            f"ERROR: {frag} sets {', '.join(stamped)}, which the release stamps in.\n"
            f"       `impact` decides whether the entry renders under "
            f"\"{BREAKING_SECTION}\"; the ABI check settles that, not the\n"
            f"       pull request. Remove {'them' if len(stamped) > 1 else 'it'}.",
            file=sys.stderr,
        )
        reason("stamped-field")
        return 1

    declared_pr = data.get("pr")
    if declared_pr != args.pr:
        print(
            f"ERROR: {frag} declares pr={declared_pr} but this PR is #{args.pr}",
            file=sys.stderr,
        )
        reason("pr-mismatch")
        return 1

    if data.get("type") != typ:
        print(
            f'ERROR: type mismatch. The PR title says `{typ}` but {frag} says '
            f'`{data.get("type")}`.\n'
            f"       Fix whichever is wrong -- they must agree.",
            file=sys.stderr,
        )
        reason("type-mismatch")
        return 1

    print(f"OK: #{args.pr} title is `{typ}` and its fragment is present and valid")
    reason("ok")
    return 0


def _err(msg):
    print(f"ERROR: {msg}", file=sys.stderr)


def _check_version(changes, new, version, groups):
    """Error string if `version` cannot be the next release."""
    if new < FIRST_VERSION:
        return (f"{version} predates {fmt_semver(FIRST_VERSION)}; releases before "
                f"that shipped without fragments and are not in the changelog")
    if groups:
        highest = parse_semver(groups[0][0])
        if new <= highest:
            return f"{version} is not newer than the released {fmt_semver(highest)}"
    for archive in frozen_lines(changes):
        # Reopening a closed line would split it: its archive is already written
        # and the root changelog only renders released/.
        line = _line_of(archive.name)
        if new[:2] == line:
            return f"{version} belongs to {archive.name}, which is already archived"
        if new[:2] < line:
            return f"{version} is older than the archived line {archive.name}"
    return None


def _freeze(changes, line, groups):
    """Archive a closing minor line to one file and drop its fragments.

    Re-runnable: a crash between writing the archive and pruning leaves both, and
    the next rollup rewrites the archive from the same fragments and finishes.
    """
    archive = changes / f"{line[0]}.{line[1]}.x.md"
    closing = [(v, f) for v, f in groups if parse_semver(v)[:2] == line]
    archive.write_text(render_line_archive(archive.stem, closing))
    # The archive is the record from here on. Keeping the fragments too would
    # add one file per merged pull request forever, for nothing that reads them;
    # `git log -- .changes` still has every one.
    for _version, frags in closing:
        for frag in frags:
            (changes / "released" / f"{frag['pr']}.json").unlink()


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
    """Two flows: a patch accretes into released/; a minor archives the old line."""
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

    groups = releases(changes)
    err = _check_version(changes, new, args.version, groups)
    if err:
        _err(err)
        return 2

    shipped = {f["pr"]: v for v, frags in groups for f in frags}
    dupes = sorted(f["pr"] for f in preview if f["pr"] in shipped)
    if dupes:
        # Two entries for one pull request, in two releases. Whichever is stale
        # would keep rendering, because a re-render trusts what is on disk.
        _err("preview/ holds a fragment for a pull request already released: "
             + ", ".join(f"#{pr} in {shipped[pr]}" for pr in dupes))
        return 2

    current = parse_semver(groups[0][0])[:2] if groups else None
    bump = "patch" if current == new[:2] else "minor"
    if bump == "minor" and current is not None:
        _freeze(changes, current, groups)

    _release_preview(changes, args.version, args.date,
                     {int(p) for p in args.minor_prs.split(",") if p.strip()})
    Path(args.changelog).write_text(
        render_root_changelog(changes, preview=False, docs_branch=args.docs_branch))
    print(f"rolled up {len(preview)} fragment(s) into {args.version} ({bump})")
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
