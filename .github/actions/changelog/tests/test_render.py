"""Fragments to markdown."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import changelog
import render  # noqa: E402
from helpers import _changes, _render, _seed, _write  # noqa: E402


def test_render_only_preview_when_no_releases(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    text = _render(tmp_path)
    assert text.startswith("# Changelog")
    assert "## [Preview]" in text
    assert "### Features" in text
    assert text.count("## [") == 1


def test_render_groups_by_category_and_hides_chore(tmp_path):
    _seed(tmp_path, 843, "feat: Add SSO sign-in")
    _seed(tmp_path, 850, "fix: retry token drop")
    _write(tmp_path, 855, "revert", summary="Reverted something earlier",
           notes="It regressed the event loop.")
    _seed(tmp_path, 858, "chore: bump aws-lc to 1.34")
    text = _render(tmp_path)

    assert "### Features" in text
    assert "### Fixes" in text
    assert "### Reverts" in text
    assert "### Maintenance" not in text  # chore hidden from customer view
    # Order: Features -> Fixes -> Reverts
    assert text.index("### Features") < text.index("### Fixes") < text.index("### Reverts")


def test_render_omits_reverts_section_when_none(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _seed(tmp_path, 2, "fix: b")
    text = _render(tmp_path)
    assert "### Reverts" not in text


def test_render_preserves_summary_punctuation(tmp_path):
    _seed(tmp_path, 1, "fix: Retries no longer drop 429?")
    _seed(tmp_path, 2, "fix: Handle overflow!")
    _seed(tmp_path, 3, "feat: Add SSO")
    text = _render(tmp_path)
    assert "429? ([#1](../../pull/1)" in text
    assert "overflow! ([#2]" in text
    assert "SSO. ([#3]" in text
    assert "429?." not in text and "overflow!." not in text


def test_render_skips_malformed_fragment(tmp_path, capsys):
    _seed(tmp_path, 1, "feat: good")
    (tmp_path / ".changes" / "preview" / "2.json").write_text("{not valid json")
    text = _render(tmp_path)
    assert "#1" in text
    err = capsys.readouterr().err
    assert "WARN" in err and "2.json" in err


def test_render_skips_schema_invalid_fragment(tmp_path, capsys):
    _seed(tmp_path, 1, "feat: good")
    (tmp_path / ".changes" / "preview" / "2.json").write_text(
        json.dumps({"pr": 2, "type": "feat"})  # missing summary+url
    )
    text = _render(tmp_path)
    assert "#1" in text
    assert "#2" not in text
    err = capsys.readouterr().err
    assert "WARN" in err


def test_reverts_render_under_their_own_heading(tmp_path):
    _write(tmp_path, 1, "revert", summary='Revert "feat: a".', notes="Broke X.")
    text = _render(tmp_path)
    assert "### Reverts" in text
    assert "Broke X." in text


def test_render_subcommand_writes_the_file(tmp_path):
    _seed(tmp_path, 1, "feat: a thing")
    out = tmp_path / "CHANGELOG.md"
    assert changelog.main(["render", "--changes-dir", _changes(tmp_path),
                    "--changelog", str(out)]) == 0
    assert "a thing" in out.read_text()


def test_notes_render_as_their_own_section_last(tmp_path):
    _write(tmp_path, 40, "revert", summary="Reverted the retry default",
           notes="It changed behaviour customers relied on.\nA replacement lands later.")
    _seed(tmp_path, 41, "feat: a widget")
    text = _render(tmp_path)
    assert text.index("### Features") < text.index("### Notes")
    notes = text.split("### Notes", 1)[1]
    # Led by the linked pull request, with continuation lines indented.
    assert "- [#40](" in notes
    assert "It changed behaviour" in notes and "\n  A replacement lands later." in notes
    # And lifted out of the entry itself.
    reverts = text.split("### Reverts", 1)[1].split("###", 1)[0]
    assert "It changed behaviour" not in reverts


def test_a_section_is_omitted_when_empty(tmp_path):
    _seed(tmp_path, 50, "feat: only a feature")
    text = _render(tmp_path)
    assert "### Features" in text
    for absent in ("### Fixes", "### Reverts", "### Notes",
                   "### Possible Breaking Changes", "### Docs"):
        assert absent not in text


def test_render_on_a_tree_with_no_changes_dir(tmp_path):
    assert "## [Preview]" in _render(tmp_path)
