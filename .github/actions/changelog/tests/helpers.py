"""Fixtures shared by the per-module test files."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import changelog
import render  # noqa: E402


def _changes(tmp_path):
    d = tmp_path / ".changes" / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return str(tmp_path / ".changes")


def _seed(tmp_path, pr, title):
    """Seed writes a template, then place it where an author would have put it."""
    out = tmp_path / "template.json"
    rc = changelog.main(["seed", "--pr", str(pr), "--title", title, "--out", str(out)])
    if rc == 0:
        frag = tmp_path / ".changes" / "preview" / f"{pr}.json"
        frag.parent.mkdir(parents=True, exist_ok=True)
        frag.write_text(out.read_text())
    return rc


def _write(tmp_path, pr, typ, summary="s", notes="", **over):
    _changes(tmp_path)
    frag = {"pr": pr, "type": typ, "summary": summary,
            "notes": notes}
    frag.update(over)
    (tmp_path / ".changes" / "preview" / f"{pr}.json").write_text(
        json.dumps(frag) + "\n")


def _preview(tmp_path, name, text):
    p = tmp_path / ".changes" / "preview" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _render(tmp_path):
    text = render.render_root_changelog(tmp_path / ".changes")
    (tmp_path / "CHANGELOG.md").write_text(text)
    return text


def _rollup(tmp_path, version, date, minor_prs=""):
    argv = [
        "rollup", "--version", version, "--date", date,
        "--changes-dir", str(tmp_path / ".changes"),
        "--changelog", str(tmp_path / "CHANGELOG.md"),
    ]
    if minor_prs:
        argv += ["--minor-prs", minor_prs]
    return changelog.main(argv)


def _released(tmp_path, pr, version, date="2026-01-01", **over):
    """Write one already-released fragment, as a rollup would have stamped it."""
    d = tmp_path / ".changes" / "released"
    d.mkdir(parents=True, exist_ok=True)
    frag = {"pr": pr, "type": "feat", "summary": "A", "notes": "",
            "version": version, "date": date}
    frag.update(over)
    p = d / f"{pr}.json"
    p.write_text(json.dumps(frag))
    return p
