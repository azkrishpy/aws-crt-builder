"""Fragments to markdown. Reads fragments; writes nothing."""

from fragments import BREAKING_SECTION, CATEGORY, audit_released, frozen_lines, load_dir, releases
from pathlib import Path


# ---------- render primitives ----------

SENTENCE_END = (".", "!", "?")


# A pull request link is derived from the number, not stored beside it: the two
# could disagree, and only one of them is the fragment's identity. `up` is how
# many segments the rendered file sits below the repo root, because
# /<owner>/<repo>/blob/<branch>/<file> reaches /<owner>/<repo>/pull/<n> only from
# the right depth. The root file is two down; an archive under .changes/ is three.
ROOT_UP, ARCHIVE_UP = "../../", "../../../"


def pr_link(frag, up):
    """`#843` linked to the pull request, so an archived file still resolves."""
    return f"[#{frag['pr']}]({up}pull/{frag['pr']})"


def render_entry(frag, up):
    summary = frag["summary"].strip()
    if not summary.endswith(SENTENCE_END):
        summary += "."
    return f"- {summary} ({pr_link(frag, up)})"


def render_note(frag, up):
    """A note is its own entry, led by the pull request it explains."""
    body = frag["notes"].strip().splitlines()
    return "\n  ".join([f"- {pr_link(frag, up)} — {body[0]}", *body[1:]])


def _section(heading, entries, render, up):
    if not entries:
        return []
    return [f"### {heading}",
            *(render(e, up) for e in sorted(entries, key=lambda f: f["pr"])), ""]


def render_grouped(fragments, up=ROOT_UP):
    """Sections in a fixed order, each omitted when it would be empty."""
    breaking = [f for f in fragments if f.get("impact") == "minor"]
    lines = _section(BREAKING_SECTION, breaking, render_entry, up)
    for pr_type, cat in CATEGORY.items():
        rest = [f for f in fragments
                if f["type"] == pr_type and f.get("impact") != "minor"]
        lines += _section(cat, rest, render_entry, up)
    lines += _section("Notes", [f for f in fragments if f.get("notes", "").strip()],
                      render_note, up)
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def _release_sections(groups, up=ROOT_UP):
    out = []
    for version, frags in groups:
        body = render_grouped(frags, up)
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
    return "\n".join(body + _release_sections(groups, ARCHIVE_UP)).rstrip() + "\n"


def cmd_render(args):
    if audit_released(args.changes_dir):
        return 2
    Path(args.changelog).write_text(
        render_root_changelog(args.changes_dir, preview=True))
    print(f"rendered → {args.changelog}")
    return 0
