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


# ---------- rollup: patch ----------


# ---------- rollup: minor / freeze ----------


# ---------- resilience ----------


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


def test_a_revert_title_is_not_double_prefixed(tmp_path):
    _seed(tmp_path, 2, "revert: Reverted the retry default")
    data = json.loads((tmp_path / ".changes" / "preview" / "2.json").read_text())
    assert data["summary"] == "Reverted the retry default"


# ---------- degraded trees render rather than crash ----------


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


