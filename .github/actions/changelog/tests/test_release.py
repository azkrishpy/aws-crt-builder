"""Cutting a release: guards, stamping, archiving."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import changelog
import fragments
import release  # noqa: E402
from helpers import _changes, _preview, _released, _render, _rollup, _seed, _write  # noqa: E402


def test_rollup_patch_accretes_into_same_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    _rollup(tmp_path, "2.0.1", "2026-08-15")
    released = tmp_path / ".changes" / "released"
    assert {p.name for p in released.glob("*.json")} == {"1.json", "2.json"}
    assert not (tmp_path / ".changes" / "2.0.x.md").exists()
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [2.0.1] — 2026-08-15" in text
    assert "## [2.0.0] — 2026-08-01" in text
    assert text.index("[2.0.1]") < text.index("[2.0.0]")


def test_rollup_with_no_fragments_still_releases(tmp_path):
    # A patch of nothing but chores is routine; failing here would fail the
    # release job after it has already tagged. It renders no section, because
    # there is nothing customer-facing to put under one.
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 0
    assert "## [1.0.0]" not in (tmp_path / "CHANGELOG.md").read_text()


def test_rollup_minor_freezes_previous_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    _rollup(tmp_path, "2.0.1", "2026-08-15")
    _seed(tmp_path, 3, "feat: tcp_nodelay")
    _rollup(tmp_path, "2.1.0", "2026-08-19")

    changes = tmp_path / ".changes"
    # Pruned at freeze: the archive is the record, git keeps the fragments.
    assert {p.name for p in (changes / "released").glob("*.json")} == {"3.json"}
    frozen = (changes / "2.0.x.md").read_text()
    assert "## [Preview]" not in frozen
    assert frozen.startswith("# Changelog — 2.0.x")
    assert "## [2.0.1]" in frozen and "## [2.0.0]" in frozen
    assert "## [2.1.0]" not in frozen

    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [2.1.0]" in root
    assert "## [2.0.0]" not in root and "## [2.0.1]" not in root
    assert "## [Preview]" not in root
    assert "docs" in root


def test_the_first_release_archives_nothing(tmp_path):
    _seed(tmp_path, 1, "feat: initial")
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 0
    assert fragments.releases(tmp_path / ".changes")[0][0] == "1.0.0"
    assert fragments.frozen_lines(tmp_path / ".changes") == []


def test_rollup_major_archives_the_current_minor_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.0", "2026-08-01")
    _seed(tmp_path, 2, "feat: big change")
    _rollup(tmp_path, "3.0.0", "2027-01-01")
    changes = tmp_path / ".changes"
    assert (changes / "2.0.x.md").exists()
    assert {p.name for p in (changes / "released").glob("*.json")} == {"2.json"}


def test_rollup_rejects_duplicate_version(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    assert _rollup(tmp_path, "2.0.0", "2026-08-02") == 2


def test_rollup_bad_semver_rejected(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "notaversion", "2026-01-01") == 2


def test_rollup_bad_date_rejected(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "1.0.0", "not-a-date") == 2


def test_rollup_rejects_downgrade_in_latest(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.1", "2026-08-15")
    _seed(tmp_path, 2, "fix: b")
    assert _rollup(tmp_path, "2.0.0", "2026-08-20") == 2


def test_full_lifecycle_end_to_end(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    _seed(tmp_path, 850, "fix: idempotency token drop on 429")
    _seed(tmp_path, 858, "chore: bump aws-lc")
    _rollup(tmp_path, "2.0.0", "2026-08-01")

    _seed(tmp_path, 867, "fix: leaking fd on socket teardown")
    _write(tmp_path, 870, "revert", summary="Reverted the retry-default change",
           notes="It changed behaviour customers relied on.")
    _seed(tmp_path, 872, "fix: null-deref in event loop")
    _render(tmp_path)

    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [Preview]" in root
    assert "#867" in root and "#870" in root and "#872" in root

    _rollup(tmp_path, "2.0.1", "2026-08-15")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [2.0.1] — 2026-08-15" in root
    assert "## [2.0.0] — 2026-08-01" in root
    assert not (tmp_path / ".changes" / "2.0.x.md").exists()

    _seed(tmp_path, 875, "fix: retry backoff off-by-one")
    _seed(tmp_path, 878, "feat: add tcp_nodelay to socket options")
    _rollup(tmp_path, "2.1.0", "2026-08-19")

    frozen = (tmp_path / ".changes" / "2.0.x.md").read_text()
    assert frozen.startswith("# Changelog — 2.0.x")
    assert "## [2.0.1]" in frozen and "## [2.0.0]" in frozen
    assert "## [Preview]" not in frozen

    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [2.1.0] — 2026-08-19" in root
    assert "## [2.0.1]" not in root and "## [2.0.0]" not in root
    assert "## [Preview]" not in root


def test_rollup_refuses_to_reopen_a_frozen_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "2.1.0", "2026-02-01")
    _seed(tmp_path, 3, "fix: backport")
    assert _rollup(tmp_path, "2.0.1", "2026-03-01") == 2
    assert not (tmp_path / ".changes" / "latest" / "2.0.1").exists()


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


def test_an_archive_hides_chores_like_the_root_does(tmp_path):
    _seed(tmp_path, 1, "feat: visible")
    _seed(tmp_path, 2, "chore: internal only")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    _seed(tmp_path, 3, "feat: next line")
    _rollup(tmp_path, "1.1.0", "2026-02-01")
    frozen = (tmp_path / ".changes" / "1.0.x.md").read_text()
    assert "visible" in frozen
    assert "internal only" not in frozen


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


def test_archive_links_are_repo_relative(tmp_path):
    # An absolute --changes-dir must not leak a local path into the markdown.
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "1.1.0", "2026-02-01")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "- [1.0.x](.changes/1.0.x.md)" in root
    assert str(tmp_path) not in root


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


def test_rollup_refuses_a_version_belonging_to_an_archived_line(tmp_path):
    # released/ empty beside an archive: reopening 2.0.x would split the line,
    # since the root changelog only renders released/.
    (tmp_path / ".changes").mkdir(parents=True)
    (tmp_path / ".changes" / "2.0.x.md").write_text("# Changelog — 2.0.x\n")
    _seed(tmp_path, 2, "fix: backport")
    assert _rollup(tmp_path, "2.0.1", "2026-02-01") == 2


def test_rollup_refuses_a_version_older_than_an_archived_line(tmp_path):
    (tmp_path / ".changes").mkdir(parents=True)
    (tmp_path / ".changes" / "2.0.x.md").write_text("# Changelog — 2.0.x\n")
    _seed(tmp_path, 2, "fix: b")
    assert _rollup(tmp_path, "1.9.9", "2026-02-01") == 2


def test_the_root_changelog_links_archived_lines(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "1.1.0", "2026-02-01")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## Earlier releases" in root
    assert "1.0.x.md" in root


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


def test_rollup_refuses_a_version_before_the_first_changelogged_one(tmp_path):
    # Everything before 1.0.0 shipped without fragments, so rolling one up
    # would publish a release whose entries do not exist.
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "0.9.9", "2026-01-01") == 2
    assert not (tmp_path / "CHANGELOG.md").exists()


def test_rollup_refuses_a_second_fragment_for_a_released_pull_request(tmp_path):
    # Two entries for one pull request in two releases: whichever is stale keeps
    # rendering, because a re-render trusts what is on disk.
    _released(tmp_path, 7, "1.0.0")
    _seed(tmp_path, 7, "fix: same pr again")
    assert _rollup(tmp_path, "1.0.1", "2026-02-01") == 2


def test_rollup_finishes_an_interrupted_freeze(tmp_path):
    # Crash after the archive is written but before its fragments are pruned.
    # The archive is a pure function of those fragments, so the next rollup
    # rewrites it and completes the prune rather than wedging.
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    (tmp_path / ".changes" / "1.0.x.md").write_text("# Changelog — 1.0.x\n")
    _seed(tmp_path, 2, "feat: b")
    assert _rollup(tmp_path, "1.1.0", "2026-02-01") == 0
    archive = (tmp_path / ".changes" / "1.0.x.md").read_text()
    assert "## [1.0.0]" in archive
    assert {p.name for p in (tmp_path / ".changes" / "released").glob("*.json")} \
        == {"2.json"}


def test_a_released_fragment_must_carry_its_version(tmp_path):
    # Without the stamp the entry renders nowhere, so a caller that writes a
    # changelog must stop instead of publishing a file that lost it.
    _released(tmp_path, 1, "1.0.0")
    p = tmp_path / ".changes" / "released" / "1.json"
    p.write_text(json.dumps({"pr": 1, "type": "feat", "summary": "A",
                             "notes": "", "date": "2026-01-01"}))
    assert fragments.audit_released(tmp_path / ".changes")


def test_a_pull_request_link_resolves_from_both_depths(tmp_path):
    # /owner/repo/blob/<branch>/CHANGELOG.md needs ../../ to reach the repo root;
    # an archive one directory deeper needs ../../../. Verified against urljoin.
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "1.1.0", "2026-02-01")
    assert "(../../pull/2)" in (tmp_path / "CHANGELOG.md").read_text()
    assert "(../../../pull/1)" in (tmp_path / ".changes" / "1.0.x.md").read_text()


def test_an_archive_points_back_at_the_current_changelog(tmp_path):
    # .changes/<line>.md is one level down, so `..` reaches the repo root.
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "1.1.0", "2026-02-01")
    assert "(../CHANGELOG.md)" in (tmp_path / ".changes" / "1.0.x.md").read_text()
