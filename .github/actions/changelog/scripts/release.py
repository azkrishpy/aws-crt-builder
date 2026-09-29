"""Cutting a release: what a version is allowed to be, stamping fragments as
released, and archiving a minor line that will take no more."""

from fragments import ISO_DATE_RE, _err, _line_of, audit_released, fmt_semver, frozen_lines, load_dir, parse_semver, releases
from pathlib import Path
from render import render_line_archive, render_root_changelog
import json


# No changelog before this. Everything earlier shipped without fragments, so a
# rollup of it would render a release whose entries do not exist.
FIRST_VERSION = (1, 0, 0)


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
