"""Cutting a release: guards, stamping, archiving."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import changelog
import fragments
import release  # noqa: E402
from helpers import _changes, _preview, _released, _render, _rollup, _seed  # noqa: E402


def test_rollup_with_no_fragments_still_releases(tmp_path):
    # A patch of nothing but chores is routine; failing here would fail the
    # release job after it has already tagged. It renders no section, because
    # there is nothing customer-facing to put under one.
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 0
    assert "## [1.0.0]" not in (tmp_path / "CHANGELOG.md").read_text()


def test_rollup_bad_semver_rejected(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "notaversion", "2026-01-01") == 2


def test_rollup_bad_date_rejected(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "1.0.0", "not-a-date") == 2


def test_rollup_refuses_a_malformed_fragment(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _preview(tmp_path, "2.json", "{ not json")
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2
    assert (tmp_path / ".changes" / "preview" / "1.json").exists()
    assert not (tmp_path / ".changes" / "latest" / "1.0.0").exists()


def test_rollup_refuses_a_schema_invalid_fragment(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _preview(tmp_path, "2.json", json.dumps(
        {"pr": "two", "type": "feat", "summary": ""}))
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2


def test_rollup_refuses_a_fragment_whose_name_and_pr_disagree(tmp_path):
    # Would render the entry under someone else's number.
    _preview(tmp_path, "1.json", json.dumps(
        {"pr": 999, "type": "feat", "summary": "Mislabelled", "notes": ""}))
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2


def test_rollup_reports_an_all_invalid_preview_as_invalid_not_empty(tmp_path):
    _preview(tmp_path, "1.json", "{ not json")
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2


def test_a_release_with_nothing_visible_renders_no_section(tmp_path):
    # A bare header with nothing under it reads as a broken file, so the release
    # simply does not appear -- the fragment is kept, it just renders nowhere.
    _seed(tmp_path, 1, "chore: internal only")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [1.0.0]" not in root
    assert "_Nothing yet._" not in root
    assert (tmp_path / ".changes" / "released" / "1.json").exists()


def test_render_refuses_to_drop_a_released_entry(tmp_path):
    _released(tmp_path, 1, "1.0.0")
    _released(tmp_path, 2, "1.0.0", type="bogus")
    assert changelog.main(["render", "--changes-dir", _changes(tmp_path),
                    "--changelog", str(tmp_path / "CHANGELOG.md")]) == 2


def test_rollup_refuses_to_drop_a_released_entry(tmp_path):
    _released(tmp_path, 1, "1.0.0")
    _released(tmp_path, 2, "1.0.0", type="bogus")
    assert _rollup(tmp_path, "1.1.0", "2026-01-01") == 2


def test_a_minor_pr_renders_under_possible_breaking_changes(tmp_path):
    _seed(tmp_path, 20, "feat: replace the socket options layout")
    _seed(tmp_path, 21, "feat: add a knob")
    assert _rollup(tmp_path, "1.0.0", "2026-01-01", minor_prs="20") == 0
    root = (tmp_path / "CHANGELOG.md").read_text()
    breaking = root.split("### Possible Breaking Changes", 1)[1].split("###", 1)[0]
    assert "#20" in breaking and "#21" not in breaking
    # Excluded from its own type section, not duplicated into it.
    features = root.split("### Features", 1)[1]
    assert "#21" in features and "#20" not in features


def test_the_impact_stamp_survives_a_re_render(tmp_path):
    # The label is read once, at release. Later renders must not need it again.
    _seed(tmp_path, 30, "fix: change a struct")
    _rollup(tmp_path, "1.0.0", "2026-01-01", minor_prs="30")
    assert "Possible Breaking Changes" in _render(tmp_path)


def test_the_release_branch_points_at_the_docs_branch(tmp_path):
    _seed(tmp_path, 60, "feat: a thing")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [Preview]" not in root
    assert "tree/docs/CHANGELOG.md" in root


def test_the_docs_pointer_is_only_linked_when_it_resolves(tmp_path):
    # ../../tree/<branch>/ reaches the repo root only for a one-segment branch.
    _seed(tmp_path, 1, "feat: a")
    assert changelog.main(["rollup", "--version", "1.0.0", "--date", "2026-01-01",
                    "--changes-dir", _changes(tmp_path),
                    "--changelog", str(tmp_path / "a.md"),
                    "--docs-branch", "docs"]) == 0
    assert "(../../tree/docs/CHANGELOG.md)" in (tmp_path / "a.md").read_text()

    _seed(tmp_path, 2, "feat: b")
    assert changelog.main(["rollup", "--version", "1.1.0", "--date", "2026-02-01",
                    "--changes-dir", _changes(tmp_path),
                    "--changelog", str(tmp_path / "b.md"),
                    "--docs-branch", "team/docs"]) == 0
    text = (tmp_path / "b.md").read_text()
    assert "`team/docs` branch" in text and "../../tree/team/docs" not in text


def test_rollup_stamps_and_moves_fragments(tmp_path):
    _seed(tmp_path, 1, "feat: initial")
    _seed(tmp_path, 2, "chore: bump")
    assert _rollup(tmp_path, "1.0.0", "2026-08-01") == 0
    assert list((tmp_path / ".changes" / "preview").glob("*.json")) == []
    released = tmp_path / ".changes" / "released"
    assert {p.name for p in released.glob("*.json")} == {"1.json", "2.json"}
    data = json.loads((released / "1.json").read_text())
    # The version and date live on the fragment; there is no side file.
    assert data["version"] == "1.0.0" and data["date"] == "2026-08-01"


def test_a_released_fragment_must_carry_its_version(tmp_path):
    # Without the stamp the entry renders nowhere, so a caller that writes a
    # changelog must stop instead of publishing a file that lost it.
    _released(tmp_path, 1, "1.0.0")
    p = tmp_path / ".changes" / "released" / "1.json"
    p.write_text(json.dumps({"pr": 1, "type": "feat", "summary": "A",
                             "notes": "", "date": "2026-01-01"}))
    assert fragments.audit_released(tmp_path / ".changes")
