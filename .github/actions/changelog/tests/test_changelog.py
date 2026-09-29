"""Local tests: python3 -m pytest .github/actions/changelog/tests -v"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import changelog as cl  # noqa: E402


def _seed(tmp_path, pr, title):
    return cl.main([
        "seed", "--pr", str(pr), "--title", title, "--url", f"https://x/pr/{pr}",
        "--changes-dir", str(tmp_path / ".changes"),
    ])


def _render(tmp_path):
    text = cl.render_root_changelog(tmp_path / ".changes")
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
    return cl.main(argv)


# ---------- seed ----------

def test_seed_refuses_a_placeholder_pr(tmp_path):
    assert cl.main(["seed", "--pr", "0", "--title", "feat: x", "--url", "u",
                    "--changes-dir", _changes(tmp_path)]) == 2
    assert not (tmp_path / ".changes" / "preview" / "0.json").exists()


def test_seed_writes_fragment(tmp_path):
    _seed(tmp_path, 843, "feat: Add SSO sign-in for enterprise accounts.")
    p = tmp_path / ".changes" / "preview" / "843.json"
    data = json.loads(p.read_text())
    assert data == {
        "pr": 843,
        "type": "feat",
        "summary": "Add SSO sign-in for enterprise accounts.",
        "url": "https://x/pr/843",
        "notes": "",
    }


def test_seed_no_prefix_becomes_chore(tmp_path):
    _seed(tmp_path, 500, "Just some cleanup")
    d = json.loads((tmp_path / ".changes" / "preview" / "500.json").read_text())
    assert d["type"] == "chore"
    assert d["summary"] == "Just some cleanup"


def test_seed_does_not_overwrite_without_force(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    # Non-zero, so a caller cannot mistake "declined" for "wrote it".
    assert _seed(tmp_path, 1, "feat: b") == 1
    d = json.loads((tmp_path / ".changes" / "preview" / "1.json").read_text())
    assert d["summary"] == "a"


def test_validate_rejects_missing_fields(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"pr": 1, "type": "feat"}))
    assert cl.validate_fragment(bad)


def test_validate_rejects_bad_type(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 1, "type": "bogus", "summary": "x", "url": "u"}))
    assert cl.validate_fragment(p)


# ---------- check ----------

def test_check_passes_when_fragment_present(tmp_path):
    _seed(tmp_path, 5, "feat: hello")
    assert cl.main([
        "check", "--pr", "5", "--title", "feat: hello",
        "--changes-dir", str(tmp_path / ".changes")
    ]) == 0


def test_check_rejects_an_invalid_fragment(tmp_path, capsys):
    _changes(tmp_path)
    p = tmp_path / ".changes" / "preview" / "5.json"
    p.write_text(json.dumps(
        {"pr": 5, "type": "feat", "summary": "s", "url": "u", "notes": 7}))
    assert cl.main(["check", "--pr", "5", "--title", "feat: x",
                    "--changes-dir", _changes(tmp_path)]) == 1
    assert "CHANGELOG_CHECK_REASON::invalid-fragment" in capsys.readouterr().out


def test_check_fails_on_pr_mismatch(tmp_path):
    _seed(tmp_path, 5, "feat: hello")
    src = tmp_path / ".changes" / "preview" / "5.json"
    dst = tmp_path / ".changes" / "preview" / "7.json"
    src.rename(dst)
    assert cl.main([
        "check", "--pr", "7", "--title", "feat: hello",
        "--changes-dir", str(tmp_path / ".changes")
    ]) == 1


# ---------- render ----------

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
    assert "429? ([#1]" in text
    assert "overflow! ([#2]" in text
    assert "SSO. ([#3]" in text
    assert "429?." not in text and "overflow!." not in text


# ---------- rollup: patch ----------

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


# ---------- rollup: minor / freeze ----------

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
    assert cl.releases(tmp_path / ".changes")[0][0] == "1.0.0"
    assert cl.frozen_lines(tmp_path / ".changes") == []


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


# ---------- resilience ----------

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


# ---------- list smoke ----------

# ---------- full lifecycle ----------

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


# ---------- type set, title forms, and the fragment waiver ----------

def _changes(tmp_path):
    d = tmp_path / ".changes" / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return str(tmp_path / ".changes")


def _write(tmp_path, pr, typ, summary="s", notes="", **over):
    _changes(tmp_path)
    frag = {"pr": pr, "type": typ, "summary": summary,
            "url": f"https://x/pull/{pr}", "notes": notes}
    frag.update(over)
    (tmp_path / ".changes" / "preview" / f"{pr}.json").write_text(
        json.dumps(frag) + "\n")


def _check(tmp_path, pr, title, bot=""):
    args = ["check", "--pr", str(pr), "--title", title,
            "--changes-dir", _changes(tmp_path)]
    if bot:
        args += ["--bot-author", bot]
    return cl.main(args)


def test_chore_needs_no_fragment(tmp_path):
    _changes(tmp_path)
    for title in ("chore: tidy", "chore(ci): bump runner", "chore(release): 1.2.3"):
        assert _check(tmp_path, 1, title) == 0


def test_feat_fix_and_revert_all_need_a_fragment(tmp_path):
    _changes(tmp_path)
    for title in ("feat: x", "fix: y", 'Revert "feat: z (#9)"'):
        assert _check(tmp_path, 1, title) == 1


def test_revert_button_title_is_accepted(tmp_path):
    # GitHub's Revert button emits no `<type>:` prefix.
    assert cl.parse_title('Revert "Fix CI issues (#538)"') == (
        "revert", 'Fix CI issues (#538)')
    _write(tmp_path, 4, "revert", summary='Revert "Fix CI issues".',
           notes="Broke the macos job.")
    assert _check(tmp_path, 4, 'Revert "Fix CI issues (#538)"') == 0


def test_title_without_a_recognised_prefix_fails(tmp_path):
    _changes(tmp_path)
    assert _check(tmp_path, 1, "Add more getters for metrics") == 1
    assert _check(tmp_path, 1, "perf: make it faster") == 1


def test_type_mismatch_between_title_and_fragment_fails(tmp_path):
    _write(tmp_path, 5, "chore")
    assert _check(tmp_path, 5, "feat: a real feature") == 1


def test_bot_author_waives_everything(tmp_path):
    _changes(tmp_path)
    assert _check(tmp_path, 6, "Bump actions/checkout from 4 to 7",
                  bot="dependabot[bot]") == 0


def test_missing_title_is_a_caller_error_not_an_author_error(tmp_path):
    assert cl.main(["check", "--pr", "1", "--changes-dir", _changes(tmp_path)]) == 2


def test_check_reason_is_emitted_for_each_outcome(tmp_path, capsys):
    cases = [
        ("chore: x", "exempt-type"),
        ("feat: x", "missing-fragment"),
        ("nonsense title", "bad-title"),
    ]
    for title, expected in cases:
        _check(tmp_path, 1, title)
        assert f"CHANGELOG_CHECK_REASON::{expected}" in capsys.readouterr().out


def test_reverts_render_under_their_own_heading(tmp_path):
    _write(tmp_path, 1, "revert", summary='Revert "feat: a".', notes="Broke X.")
    text = _render(tmp_path)
    assert "### Reverts" in text
    assert "Broke X." in text


# ---------- exactly one fragment, at the right path, added ----------

def _paths(tmp_path, *entries):
    f = tmp_path / "paths.tsv"
    f.write_text("".join(f"{st}\t{p}\n" for st, p in entries))
    return str(f)


def _check_paths(tmp_path, pr, title, paths_file):
    return cl.main([
        "check", "--pr", str(pr), "--title", title,
        "--changes-dir", _changes(tmp_path),
        "--changed-paths-file", paths_file,
        "--changes-prefix", ".changes",
    ])


def test_one_added_fragment_at_the_expected_path_passes(tmp_path):
    _write(tmp_path, 1259, "feat")
    p = _paths(tmp_path, ("added", ".changes/preview/1259.json"))
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 0


def test_a_stray_fragment_for_another_pr_fails(tmp_path):
    # Would otherwise render an entry attributed to PR 9999.
    _write(tmp_path, 1259, "feat")
    _write(tmp_path, 9999, "feat")
    p = _paths(tmp_path,
               ("added", ".changes/preview/1259.json"),
               ("added", ".changes/preview/9999.json"))
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 1


def test_fragment_at_the_wrong_path_fails(tmp_path):
    p = _paths(tmp_path, ("added", ".changes/1259.json"))
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 1


def test_modifying_an_existing_fragment_fails(tmp_path):
    # Only reachable when the path already exists on the base branch: the files
    # API reports status against base, so a fragment added and then edited inside
    # one pull request stays `added`. Verified against real GitHub.
    _write(tmp_path, 1259, "feat")
    p = _paths(tmp_path, ("modified", ".changes/preview/1259.json"))
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 1


def test_touching_anything_else_under_changes_fails(tmp_path):
    _write(tmp_path, 1259, "feat")
    p = _paths(tmp_path,
               ("added", ".changes/preview/1259.json"),
               ("modified", ".changes/README.md"))
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 1


def test_chore_ignores_fragment_shape_entirely(tmp_path):
    p = _paths(tmp_path,
               ("added", ".changes/preview/9999.json"),
               ("modified", ".changes/README.md"))
    assert _check_paths(tmp_path, 1259, "chore: x", p) == 0


def test_no_changes_paths_still_reports_a_missing_fragment(tmp_path):
    # Must stay `missing-fragment` so the author still gets a template.
    p = _paths(tmp_path)
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 1


# ---------- the version decides the bump ----------

def _preview(tmp_path, name, text):
    p = tmp_path / ".changes" / "preview" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_rollup_refuses_to_reopen_a_frozen_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "2.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "2.1.0", "2026-02-01")
    _seed(tmp_path, 3, "fix: backport")
    assert _rollup(tmp_path, "2.0.1", "2026-03-01") == 2
    assert not (tmp_path / ".changes" / "latest" / "2.0.1").exists()


# ---------- a release never silently drops a fragment ----------

def test_rollup_refuses_a_malformed_fragment(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _preview(tmp_path, "2.json", "{ not json")
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2
    assert (tmp_path / ".changes" / "preview" / "1.json").exists()
    assert not (tmp_path / ".changes" / "latest" / "1.0.0").exists()


def test_rollup_refuses_a_schema_invalid_fragment(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _preview(tmp_path, "2.json", json.dumps(
        {"pr": "two", "type": "feat", "summary": "", "url": "u"}))
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2


def test_rollup_refuses_a_fragment_whose_name_and_pr_disagree(tmp_path):
    # Would render the entry under someone else's number.
    _preview(tmp_path, "1.json", json.dumps(
        {"pr": 999, "type": "feat", "summary": "Mislabelled", "url": "u", "notes": ""}))
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2


def test_rollup_reports_an_all_invalid_preview_as_invalid_not_empty(tmp_path):
    _preview(tmp_path, "1.json", "{ not json")
    assert _rollup(tmp_path, "1.0.0", "2026-01-01") == 2


# ---------- one hiding policy, one placeholder ----------

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


# ---------- changed-paths hygiene ----------

def test_changes_outside_the_changes_dir_are_ignored(tmp_path):
    _write(tmp_path, 1259, "feat")
    p = _paths(tmp_path,
               ("modified", "source/event_loop.c"),
               ("added", ".changes/preview/1259.json"))
    assert _check_paths(tmp_path, 1259, "feat: x", p) == 0


# ---------- guards that only a hand-mangled tree can reach ----------

def test_render_refuses_to_drop_a_released_entry(tmp_path):
    _released(tmp_path, 1, "1.0.0")
    _released(tmp_path, 2, "1.0.0", type="bogus")
    assert cl.main(["render", "--changes-dir", _changes(tmp_path),
                    "--changelog", str(tmp_path / "CHANGELOG.md")]) == 2


def test_rollup_refuses_to_drop_a_released_entry(tmp_path):
    _released(tmp_path, 1, "1.0.0")
    _released(tmp_path, 2, "1.0.0", type="bogus")
    assert _rollup(tmp_path, "1.1.0", "2026-01-01") == 2


def test_render_subcommand_writes_the_file(tmp_path):
    _seed(tmp_path, 1, "feat: a thing")
    out = tmp_path / "CHANGELOG.md"
    assert cl.main(["render", "--changes-dir", _changes(tmp_path),
                    "--changelog", str(out)]) == 0
    assert "a thing" in out.read_text()


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


def test_a_revert_title_is_not_double_prefixed(tmp_path):
    _seed(tmp_path, 2, "revert: Reverted the retry default")
    data = json.loads((tmp_path / ".changes" / "preview" / "2.json").read_text())
    assert data["summary"] == "Reverted the retry default"


def test_the_docs_pointer_is_only_linked_when_it_resolves(tmp_path):
    # ../../tree/<branch>/ reaches the repo root only for a one-segment branch.
    _seed(tmp_path, 1, "feat: a")
    assert cl.main(["rollup", "--version", "1.0.0", "--date", "2026-01-01",
                    "--changes-dir", _changes(tmp_path),
                    "--changelog", str(tmp_path / "a.md"),
                    "--docs-branch", "docs"]) == 0
    assert "(../../tree/docs/CHANGELOG.md)" in (tmp_path / "a.md").read_text()

    _seed(tmp_path, 2, "feat: b")
    assert cl.main(["rollup", "--version", "1.1.0", "--date", "2026-02-01",
                    "--changes-dir", _changes(tmp_path),
                    "--changelog", str(tmp_path / "b.md"),
                    "--docs-branch", "team/docs"]) == 0
    text = (tmp_path / "b.md").read_text()
    assert "`team/docs` branch" in text and "../../tree/team/docs" not in text


def _released(tmp_path, pr, version, date="2026-01-01", **over):
    """Write one already-released fragment, as a rollup would have stamped it."""
    d = tmp_path / ".changes" / "released"
    d.mkdir(parents=True, exist_ok=True)
    frag = {"pr": pr, "type": "feat", "summary": "A", "url": "u", "notes": "",
            "version": version, "date": date}
    frag.update(over)
    p = d / f"{pr}.json"
    p.write_text(json.dumps(frag))
    return p


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


# ---------- degraded trees render rather than crash ----------

def test_render_on_a_tree_with_no_changes_dir(tmp_path):
    assert "## [Preview]" in _render(tmp_path)


def test_validate_rejects_malformed_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{ not json")
    assert cl.validate_fragment(p)


def test_validate_rejects_non_string_notes(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 1, "type": "feat", "summary": "s", "url": "u", "notes": 7}))
    assert cl.validate_fragment(p)


# ---------- an entry must be attributable and, for a revert, explained ----------

def test_a_revert_without_notes_is_invalid(tmp_path):
    _write(tmp_path, 1, "revert", summary="Reverted the thing")
    assert cl.validate_fragment(tmp_path / ".changes" / "preview" / "1.json")


def test_a_revert_with_notes_is_valid(tmp_path):
    _write(tmp_path, 1, "revert", summary="Reverted the thing", notes="It broke downstream.")
    assert not cl.validate_fragment(tmp_path / ".changes" / "preview" / "1.json")


def test_a_placeholder_pr_number_is_invalid(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 0, "type": "feat", "summary": "s", "url": "u", "notes": ""}))
    assert cl.validate_fragment(p)


def test_an_empty_url_is_invalid(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 1, "type": "feat", "summary": "s", "url": "", "notes": ""}))
    assert cl.validate_fragment(p)


def test_seeding_a_revert_drops_the_original_prefix_and_number(tmp_path):
    _seed(tmp_path, 900, 'Revert "feat: add SSO sign-in (#843)"')
    d = json.loads((tmp_path / ".changes" / "preview" / "900.json").read_text())
    assert d["type"] == "revert"
    assert d["summary"] == "Reverted add SSO sign-in"


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


def test_an_author_may_not_stamp_release_fields(tmp_path):
    # impact decides the Possible Breaking Changes section; a pull request that
    # could set it would classify itself.
    for field, value in (("impact", "minor"), ("version", "1.0.0"),
                         ("date", "2026-01-01")):
        _write(tmp_path, 1, "feat", summary="s", **{field: value})
        assert _check(tmp_path, 1, "feat: s") == 1


def test_a_released_fragment_must_carry_its_version(tmp_path):
    # Without the stamp the entry renders nowhere, so a caller that writes a
    # changelog must stop instead of publishing a file that lost it.
    _released(tmp_path, 1, "1.0.0")
    p = tmp_path / ".changes" / "released" / "1.json"
    p.write_text(json.dumps({"pr": 1, "type": "feat", "summary": "A", "url": "u",
                             "notes": "", "date": "2026-01-01"}))
    assert cl.audit_released(tmp_path / ".changes")


def test_an_archive_points_back_at_the_current_changelog(tmp_path):
    # .changes/<line>.md is one level down, so `..` reaches the repo root.
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "1.0.0", "2026-01-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "1.1.0", "2026-02-01")
    assert "(../CHANGELOG.md)" in (tmp_path / ".changes" / "1.0.x.md").read_text()
