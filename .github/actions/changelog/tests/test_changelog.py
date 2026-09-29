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


# ---------- rollup: minor / freeze ----------


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


def test_reverts_render_under_their_own_heading(tmp_path):
    _write(tmp_path, 1, "revert", summary='Revert "feat: a".', notes="Broke X.")
    text = _render(tmp_path)
    assert "### Reverts" in text
    assert "Broke X." in text


# ---------- exactly one fragment, at the right path, added ----------


# ---------- the version decides the bump ----------

def _preview(tmp_path, name, text):
    p = tmp_path / ".changes" / "preview" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


# ---------- a release never silently drops a fragment ----------


# ---------- one hiding policy, one placeholder ----------


# ---------- changed-paths hygiene ----------


# ---------- guards that only a hand-mangled tree can reach ----------


def test_render_subcommand_writes_the_file(tmp_path):
    _seed(tmp_path, 1, "feat: a thing")
    out = tmp_path / "CHANGELOG.md"
    assert cl.main(["render", "--changes-dir", _changes(tmp_path),
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


def test_a_revert_title_is_not_double_prefixed(tmp_path):
    _seed(tmp_path, 2, "revert: Reverted the retry default")
    data = json.loads((tmp_path / ".changes" / "preview" / "2.json").read_text())
    assert data["summary"] == "Reverted the retry default"


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


