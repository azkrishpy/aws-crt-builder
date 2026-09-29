"""The fragment schema, and reading a tree of fragments."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import changelog
import fragments  # noqa: E402
from helpers import _seed, _write  # noqa: E402


def test_seed_refuses_a_placeholder_pr(tmp_path):
    assert changelog.main(["seed", "--pr", "0", "--title", "feat: x",
                    "--out", str(tmp_path / "t.json")]) == 2
    assert not (tmp_path / "t.json").exists()


def test_seed_writes_fragment(tmp_path):
    _seed(tmp_path, 843, "feat: Add SSO sign-in for enterprise accounts.")
    p = tmp_path / ".changes" / "preview" / "843.json"
    data = json.loads(p.read_text())
    assert data == {
        "pr": 843,
        "type": "feat",
        "summary": "Add SSO sign-in for enterprise accounts.",
        "notes": "",
    }


def test_seed_no_prefix_becomes_chore(tmp_path):
    _seed(tmp_path, 500, "Just some cleanup")
    d = json.loads((tmp_path / ".changes" / "preview" / "500.json").read_text())
    assert d["type"] == "chore"
    assert d["summary"] == "Just some cleanup"


def test_validate_rejects_missing_fields(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"pr": 1, "type": "feat"}))
    assert fragments.validate_fragment(bad)


def test_validate_rejects_bad_type(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 1, "type": "bogus", "summary": "x"}))
    assert fragments.validate_fragment(p)


def test_a_revert_title_is_not_double_prefixed(tmp_path):
    _seed(tmp_path, 2, "revert: Reverted the retry default")
    data = json.loads((tmp_path / ".changes" / "preview" / "2.json").read_text())
    assert data["summary"] == "Reverted the retry default"


def test_validate_rejects_malformed_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{ not json")
    assert fragments.validate_fragment(p)


def test_validate_rejects_non_string_notes(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 1, "type": "feat", "summary": "s", "notes": 7}))
    assert fragments.validate_fragment(p)


def test_a_revert_without_notes_is_invalid(tmp_path):
    _write(tmp_path, 1, "revert", summary="Reverted the thing")
    assert fragments.validate_fragment(tmp_path / ".changes" / "preview" / "1.json")


def test_a_revert_with_notes_is_valid(tmp_path):
    _write(tmp_path, 1, "revert", summary="Reverted the thing", notes="It broke downstream.")
    assert not fragments.validate_fragment(tmp_path / ".changes" / "preview" / "1.json")


def test_a_placeholder_pr_number_is_invalid(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 0, "type": "feat", "summary": "s", "notes": ""}))
    assert fragments.validate_fragment(p)


def test_seeding_a_revert_drops_the_original_prefix_and_number(tmp_path):
    _seed(tmp_path, 900, 'Revert "feat: add SSO sign-in (#843)"')
    d = json.loads((tmp_path / ".changes" / "preview" / "900.json").read_text())
    assert d["type"] == "revert"
    assert d["summary"] == "Reverted add SSO sign-in"
