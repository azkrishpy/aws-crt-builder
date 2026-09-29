"""Fixtures shared by the per-module test files."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import changelog  # noqa: E402


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
