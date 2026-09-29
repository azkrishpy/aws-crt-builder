"""Cutting a release: what a version is allowed to be, stamping fragments as
released, and archiving a minor line that will take no more."""

from fragments import ISO_DATE_RE, _err, audit_released, load_dir, parse_semver
from pathlib import Path
from render import render_root_changelog
import json


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
