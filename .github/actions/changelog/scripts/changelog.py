#!/usr/bin/env python3
"""Changelog fragment tooling: seed, validate, check, render, rollup, revert.

Fragments (`.changes/preview/<pr>.json`) are the source of truth. CHANGELOG.md
is fully regenerated from them — nothing appends manually.

Directory layout (identical on main and docs):
  .changes/
  ├── preview/            fragments awaiting the next release
  ├── <version>/          one dir per release: _meta.json + the shipped fragments
  │                       the last release of a closed minor line also holds
  │                       that line's frozen CHANGELOG.md snapshot
  └── ...

Releases are grouped into minor lines by parsing semver off the directory
names, so there is no `latest/` directory and nothing is ever renamed.

Root CHANGELOG.md carries every release in the *current* minor line. On docs
it also carries a [Preview] block; on main it does not (`--no-preview`).
"""
import argparse
import json
import re
import sys
from pathlib import Path

VALID_TYPES = {"feat", "fix", "doc", "chore", "revert"}
CATEGORIES = ["Features", "Fixes", "Docs", "Maintenance"]
HIDDEN_TYPES_CUSTOMER = {"chore"}

PREVIEW_START = "<!-- changelog:preview:start -->"
PREVIEW_END = "<!-- changelog:preview:end -->"

TITLE_RE = re.compile(
    r"^(feat|fix|docs?|chore|revert)(?:\([^)]+\))?:\s*(.+)$", re.IGNORECASE
)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MINOR_LINE_RE = re.compile(r"^(\d+)\.(\d+)\.x$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- parsing / schema ----------

def parse_title(title):
    m = TITLE_RE.match(title.strip())
    if not m:
        return None, title.strip()
    t = m.group(1).lower()
    if t == "docs":
        t = "doc"
    return t, m.group(2).strip()


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
    if not isinstance(data.get("pr"), int):
        errs.append(f"{path}: pr must be int")
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        errs.append(f"{path}: notes must be a string")
    return errs


META_REQUIRED = {"version", "date"}


def validate_meta(path):
    errs = []
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path}: invalid JSON: {e}"]
    for k in sorted(META_REQUIRED - set(data)):
        errs.append(f"{path}: missing field: {k}")
    if not SEMVER_RE.match(str(data.get("version", ""))):
        errs.append(f"{path}: version must be x.y.z")
    if not ISO_DATE_RE.match(str(data.get("date", ""))):
        errs.append(f"{path}: date must be YYYY-MM-DD")
    return errs


def parse_semver(s):
    m = SEMVER_RE.match(s)
    if not m:
        raise ValueError(f"not a semver x.y.z: {s!r}")
    return tuple(int(g) for g in m.groups())


# ---------- render primitives ----------

def categorize(frag):
    return {
        "feat": "Features",
        "fix": "Fixes",
        "doc": "Docs",
        "chore": "Maintenance",
        "revert": "Maintenance",
    }.get(frag["type"], "Maintenance")


SENTENCE_END = (".", "!", "?")


def render_entry(frag):
    summary = frag["summary"].strip()
    if not summary.endswith(SENTENCE_END):
        summary += "."
    line = f"- {summary} (#{frag['pr']})"
    if frag.get("notes"):
        indented = "\n  ".join(frag["notes"].splitlines())
        line += "\n  " + indented
    return line


def render_grouped(fragments, hidden_types=HIDDEN_TYPES_CUSTOMER):
    grouped = {c: [] for c in CATEGORIES}
    for f in fragments:
        if f["type"] in hidden_types:
            continue
        grouped[categorize(f)].append(f)
    lines = []
    for cat in CATEGORIES:
        entries = sorted(grouped[cat], key=lambda f: f["pr"])
        if not entries:
            continue
        lines.append(f"### {cat}")
        for e in entries:
            lines.append(render_entry(e))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else "_Nothing yet._\n"


# ---------- fragment / release IO ----------

def _safe_load_json(path):
    """Load a JSON file; on parse failure emit a warning and return None."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        print(f"WARN: skipping {path}: {e}", file=sys.stderr)
        return None


def _load_valid_fragment(path):
    """Load a fragment JSON; skip with warning if malformed or schema-invalid."""
    data = _safe_load_json(path)
    if data is None:
        return None
    errs = validate_fragment(path)
    if errs:
        for e in errs:
            print(f"WARN: skipping {e}", file=sys.stderr)
        return None
    return data


def load_preview(changes_dir):
    d = Path(changes_dir) / "preview"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        data = _load_valid_fragment(f)
        if data is not None:
            out.append(data)
    return out


def load_release(release_dir):
    """Return (meta, [fragments]) for a single release directory."""
    release_dir = Path(release_dir)
    meta_path = release_dir / "_meta.json"
    if not meta_path.exists():
        return None, []
    meta_errs = validate_meta(meta_path)
    if meta_errs:
        for e in meta_errs:
            print(f"WARN: skipping release ({e})", file=sys.stderr)
        return None, []
    meta = json.loads(meta_path.read_text())
    frags = []
    for f in sorted(release_dir.glob("*.json")):
        if f.name == "_meta.json":
            continue
        data = _load_valid_fragment(f)
        if data is not None:
            frags.append(data)
    return meta, frags


def list_releases(changes_dir):
    """Every release dir `.changes/<x.y.z>/`, semver-descending."""
    changes_dir = Path(changes_dir)
    if not changes_dir.exists():
        return []
    dirs = [d for d in changes_dir.iterdir() if d.is_dir() and SEMVER_RE.match(d.name)]
    return sorted(dirs, key=lambda d: parse_semver(d.name), reverse=True)


def minor_of(version):
    M, N, _ = parse_semver(version)
    return M, N


def line_label(minor):
    return f"{minor[0]}.{minor[1]}.x"


def releases_in_line(changes_dir, minor):
    """Release dirs belonging to one minor line, semver-descending."""
    return [d for d in list_releases(changes_dir) if minor_of(d.name) == minor]


def current_minor(changes_dir):
    """(M, N) of the newest release, or None if nothing has shipped yet."""
    releases = list_releases(changes_dir)
    return minor_of(releases[0].name) if releases else None


def closed_minors(changes_dir):
    """Every minor line except the current one, newest first."""
    current = current_minor(changes_dir)
    out = []
    for d in list_releases(changes_dir):
        m = minor_of(d.name)
        if m != current and m not in out:
            out.append(m)
    return out


def snapshot_path(changes_dir, minor):
    """A closed line's frozen CHANGELOG.md lives in its final release dir."""
    releases = releases_in_line(changes_dir, minor)
    return (releases[0] / "CHANGELOG.md") if releases else None


def render_release_section(meta, fragments, hidden_types=HIDDEN_TYPES_CUSTOMER):
    header = f"## [{meta['version']}] — {meta['date']}\n"
    if meta.get("highlights"):
        header += f"Highlights: {meta['highlights']}\n\n"
    else:
        header += "\n"
    return header + render_grouped(fragments, hidden_types=hidden_types)


def render_root_changelog(changes_dir, include_preview=True):
    """Root CHANGELOG.md: optional [Preview] block + the current minor line.

    Older lines are not repeated here; each is frozen into its own snapshot
    (see snapshot_path), which is what keeps this file openable forever.
    """
    body = ["# Changelog", ""]
    if include_preview:
        body += [
            PREVIEW_START,
            "## [Preview]",
            "",
            render_grouped(load_preview(changes_dir)).rstrip(),
            PREVIEW_END,
            "",
        ]
    minor = current_minor(changes_dir)
    if minor is not None:
        for rel_dir in releases_in_line(changes_dir, minor):
            meta, frags = load_release(rel_dir)
            if meta is None:
                continue
            body.append(render_release_section(meta, frags).rstrip())
            body.append("")
    return "\n".join(body).rstrip() + "\n"


def render_line_snapshot(changes_dir, minor):
    """Render a self-contained CHANGELOG.md for one (closed) minor line."""
    body = [f"# Changelog — {line_label(minor)}", ""]
    for rel_dir in releases_in_line(changes_dir, minor):
        meta, frags = load_release(rel_dir)
        if meta is None:
            continue
        body.append(render_release_section(meta, frags).rstrip())
        body.append("")
    return "\n".join(body).rstrip() + "\n"


# ---------- commands ----------

def cmd_seed(args):
    typ, summary = parse_title(args.title)
    if typ is None:
        typ = "chore"
        summary = args.title.strip()
    frag = {
        "pr": args.pr,
        "type": typ,
        "summary": summary,
        "url": args.url,
        "notes": "",
    }
    print(json.dumps(frag, indent=2))
    return 0


def cmd_validate(args):
    target = Path(args.target)
    files = [target] if target.is_file() else sorted(target.glob("*.json"))
    if not files:
        print(f"no fragments found under {target}")
        return 0
    errs = []
    for f in files:
        errs.extend(validate_fragment(f))
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    print(f"OK: {len(files)} fragment(s)")
    return 0


def cmd_check(args):
    frag = Path(args.changes_dir) / "preview" / f"{args.pr}.json"
    if not frag.exists():
        print(
            f"ERROR: no changelog fragment for PR #{args.pr}.\n"
            f"       expected: {frag}\n"
            f"       generate the fragment JSON (see PR template) and commit it,\n"
            f"       or apply the `skip-changelog` label for CI-only / pure-infra PRs.",
            file=sys.stderr,
        )
        return 1
    errs = validate_fragment(frag)
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    declared_pr = json.loads(frag.read_text()).get("pr")
    if declared_pr != args.pr:
        print(
            f"ERROR: {frag} declares pr={declared_pr} but this PR is #{args.pr}",
            file=sys.stderr,
        )
        return 1
    print(f"OK: fragment for #{args.pr} is present and valid")
    return 0


def cmd_render(args):
    text = render_root_changelog(args.changes_dir, include_preview=args.preview)
    Path(args.changelog).write_text(text)
    print(f"rendered → {args.changelog}")
    return 0


def _err(msg):
    print(f"ERROR: {msg}", file=sys.stderr)


def _check_no_downgrade(changes_dir, new_tuple, new_version):
    """Error string if new_version is not strictly newer than every prior release."""
    releases = list_releases(changes_dir)
    if not releases:
        return None
    highest = parse_semver(releases[0].name)
    if new_tuple <= highest:
        return (
            f"{new_version} is not newer than the latest released "
            f"{'.'.join(str(x) for x in highest)}"
        )
    return None


def _infer_bump(current_minor, new_tuple):
    M_new, N_new, _ = new_tuple
    if current_minor is None:
        return "minor"
    if (M_new, N_new) == current_minor:
        return "patch"
    if M_new != current_minor[0]:
        return "major"
    return "minor"


def _archive_closing_line(changes_dir, minor):
    """Freeze a minor line by writing its snapshot into its final release dir.

    No renames are involved: the release dirs stay exactly where they are and
    grouping is recomputed from their names, so this step is idempotent and
    safe to re-run.
    """
    dest = snapshot_path(changes_dir, minor)
    if dest is None:
        return None
    dest.write_text(render_line_snapshot(changes_dir, minor))
    return None


def _check_missing_snapshots(changes_dir):
    """Every closed minor line must carry its frozen CHANGELOG.md snapshot."""
    for minor in closed_minors(changes_dir):
        dest = snapshot_path(changes_dir, minor)
        if dest is not None and not dest.exists():
            return (
                f"closed minor line {line_label(minor)} has no frozen snapshot "
                f"(expected {dest}). Re-run: "
                f"python3 changelog.py snapshot --line {line_label(minor)}"
            )
    return None


def _open_release_dir(changes_dir, new_version, date, highlights):
    """Create .changes/<version>/ with _meta.json and move preview fragments in."""
    release_dir = Path(changes_dir) / new_version
    if release_dir.exists():
        return None, f"release dir {release_dir} already exists"
    release_dir.mkdir(parents=True)
    meta = {"version": new_version, "date": date, "highlights": highlights or ""}
    (release_dir / "_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    for f in (Path(changes_dir) / "preview").glob("*.json"):
        f.rename(release_dir / f.name)
    return release_dir, None


def cmd_rollup(args):
    """Patch: add a release dir to the current line. Minor/major: freeze the
    outgoing line's snapshot first, then open the new line's first release.

    Intended to run on the default branch as part of the release commit that
    bumps the version file, so VERSION and CHANGELOG.md move together.
    """
    changes = Path(args.changes_dir)
    changes.mkdir(parents=True, exist_ok=True)

    err = _check_missing_snapshots(changes)
    if err:
        _err(err)
        return 2

    preview = load_preview(changes)
    if not preview:
        print("nothing to roll up (preview/ empty)", file=sys.stderr)
        return 1

    try:
        new_tuple = parse_semver(args.version)
    except ValueError as e:
        _err(str(e))
        return 2

    if not ISO_DATE_RE.match(args.date):
        _err(f"--date must be YYYY-MM-DD, got {args.date!r}")
        return 2

    err = _check_no_downgrade(changes, new_tuple, args.version)
    if err:
        _err(err)
        return 2

    current = current_minor(changes)
    bump = args.bump or _infer_bump(current, new_tuple)
    if bump not in ("patch", "minor", "major"):
        _err(f"--bump must be patch|minor|major, got {bump!r}")
        return 2

    M_new, N_new, _ = new_tuple
    if bump == "patch" and current is not None and (M_new, N_new) != current:
        _err(
            f"--bump patch requires {args.version} to share a minor line with "
            f"current {'.'.join(str(x) for x in current)}"
        )
        return 2

    if bump in ("minor", "major") and current is not None:
        err = _archive_closing_line(changes, current)
        if err:
            _err(err)
            return 2

    _, err = _open_release_dir(changes, args.version, args.date, args.highlights)
    if err:
        _err(err)
        return 2

    Path(args.changelog).write_text(
        render_root_changelog(changes, include_preview=args.preview)
    )
    print(f"rolled up {len(preview)} fragment(s) into {args.version} ({bump})")
    return 0


def _find_original_fragment(changes_dir, pr):
    """Locate a PR's fragment in preview/ or in any release dir."""
    changes = Path(changes_dir)
    candidates = [changes / "preview" / f"{pr}.json"]
    for rel_dir in list_releases(changes):
        candidates.append(rel_dir / f"{pr}.json")
    for c in candidates:
        if c.exists():
            return c
    return None


def cmd_revert(args):
    orig_summary = ""
    orig_path = _find_original_fragment(args.changes_dir, args.original_pr)
    if orig_path is not None:
        data = _safe_load_json(orig_path)
        if data:
            orig_summary = (data.get("summary") or "").strip()
    frag = {
        "pr": args.revert_pr,
        "type": "revert",
        "summary": f"Revert #{args.original_pr}"
        + (f": {orig_summary}" if orig_summary else ""),
        "url": args.url,
        "notes": f"Reverts #{args.original_pr}.",
    }
    out = Path(args.changes_dir) / "preview" / f"{args.revert_pr}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(frag, indent=2) + "\n")
    print(str(out))
    return 0


def cmd_snapshot(args):
    """Recovery: (re-)write a closed minor line's frozen CHANGELOG.md."""
    m = MINOR_LINE_RE.match(args.line)
    if not m:
        _err(f"--line must look like 0.29.x, got {args.line!r}")
        return 2
    minor = (int(m.group(1)), int(m.group(2)))
    dest = snapshot_path(args.changes_dir, minor)
    if dest is None:
        _err(f"no releases found for line {args.line}")
        return 2
    dest.write_text(render_line_snapshot(args.changes_dir, minor))
    print(f"wrote {dest}")
    return 0


def cmd_list(args):
    """Debugging aid: show staged fragments and every released line."""
    changes = Path(args.changes_dir)
    unrel = load_preview(changes)
    print(f"[preview]  {len(unrel)} fragment(s)")
    for f in unrel:
        print(f"  #{f['pr']:<6} {f['type']:<6} {f['summary']}")
    current = current_minor(changes)
    for minor in ([current] if current else []) + closed_minors(changes):
        tag = "current" if minor == current else "frozen"
        print(f"\n[{line_label(minor)}]  ({tag})")
        for rel_dir in releases_in_line(changes, minor):
            meta, frags = load_release(rel_dir)
            v = meta["version"] if meta else rel_dir.name
            d = meta["date"] if meta else "?"
            snap = " + snapshot" if (rel_dir / "CHANGELOG.md").exists() else ""
            print(f"  {v}  {d}  ({len(frags)} fragment(s)){snap}")
    return 0


# ---------- CLI ----------

def main(argv=None):
    p = argparse.ArgumentParser(prog="changelog")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="print a fragment JSON to stdout; author places it into .changes/preview/<PR>.json themselves")
    s.add_argument("--pr", type=int, required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--url", required=True)
    s.set_defaults(func=cmd_seed)

    v = sub.add_parser("validate", help="validate a fragment file or directory")
    v.add_argument("target")
    v.set_defaults(func=cmd_validate)

    c = sub.add_parser("check", help="CI: assert a valid fragment exists for a given PR")
    c.add_argument("--pr", type=int, required=True)
    c.add_argument("--changes-dir", default=".changes")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("render", help="regenerate root CHANGELOG.md from .changes/")
    r.add_argument("--changes-dir", default=".changes")
    r.add_argument("--changelog", default="CHANGELOG.md")
    r.add_argument("--no-preview", dest="preview", action="store_false",
                   help="Omit the [Preview] block (use when rendering on the "
                        "default branch; docs keeps the block).")
    r.set_defaults(func=cmd_render, preview=True)

    u = sub.add_parser("rollup", help="cut a release: open .changes/<version>/ and rewrite CHANGELOG.md")
    u.add_argument("--version", required=True)
    u.add_argument("--date", required=True)
    u.add_argument("--highlights", default="")
    u.add_argument("--bump", choices=["patch", "minor", "major"],
                   help="Optional; inferred from --version and the newest release if omitted.")
    u.add_argument("--changes-dir", default=".changes")
    u.add_argument("--changelog", default="CHANGELOG.md")
    u.add_argument("--preview", dest="preview", action="store_true",
                   help="Keep a [Preview] block. Off by default: rollup runs on "
                        "the default branch, which carries released history only.")
    u.set_defaults(func=cmd_rollup, preview=False)

    rv = sub.add_parser("revert", help="create a revert fragment (never deletes original)")
    rv.add_argument("--original-pr", type=int, required=True)
    rv.add_argument("--revert-pr", type=int, required=True)
    rv.add_argument("--url", required=True)
    rv.add_argument("--changes-dir", default=".changes")
    rv.set_defaults(func=cmd_revert)

    ls = sub.add_parser("list", help="show preview fragments and every released line")
    ls.add_argument("--changes-dir", default=".changes")
    ls.set_defaults(func=cmd_list)

    fs = sub.add_parser("snapshot",
                        help="recovery: re-render a closed line's frozen CHANGELOG.md")
    fs.add_argument("--line", required=True, help="minor line, e.g. 0.29.x")
    fs.add_argument("--changes-dir", default=".changes")
    fs.set_defaults(func=cmd_snapshot)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
