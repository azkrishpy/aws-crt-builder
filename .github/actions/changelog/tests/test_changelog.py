"""Local tests: python3 -m pytest .github/actions/changelog/tests -v"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import changelog as cl  # noqa: E402


def _seed(tmp_path, pr, title, capsys=None):
    """Run seed (prints JSON to stdout) and materialise the fragment on disk
    where the rest of the tooling expects it."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cl.main([
            "seed", "--pr", str(pr), "--title", title, "--url", f"https://x/pr/{pr}",
        ])
    frag_dir = tmp_path / ".changes" / "preview"
    frag_dir.mkdir(parents=True, exist_ok=True)
    (frag_dir / f"{pr}.json").write_text(buf.getvalue().rstrip() + "\n")
    return rc


def _render(tmp_path):
    cl.main([
        "render",
        "--changes-dir", str(tmp_path / ".changes"),
        "--changelog", str(tmp_path / "CHANGELOG.md"),
    ])
    return (tmp_path / "CHANGELOG.md").read_text()


def _rollup(tmp_path, version, date, bump=None, highlights="", preview=True):
    argv = [
        "rollup", "--version", version, "--date", date,
        "--changes-dir", str(tmp_path / ".changes"),
        "--changelog", str(tmp_path / "CHANGELOG.md"),
    ]
    if bump:
        argv += ["--bump", bump]
    if highlights:
        argv += ["--highlights", highlights]
    if preview:
        argv += ["--preview"]
    return cl.main(argv)


# ---------- seed / validate ----------

def test_seed_no_prefix_becomes_chore(tmp_path, capsys):
    rc = cl.main([
        "seed", "--pr", "500", "--title", "Just some cleanup",
        "--url", "https://x/pr/500",
    ])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert d["type"] == "chore"
    assert d["summary"] == "Just some cleanup"


def test_seed_prints_json_to_stdout(tmp_path, capsys):
    rc = cl.main([
        "seed", "--pr", "843",
        "--title", "feat: Add SSO sign-in.",
        "--url", "https://x/pr/843",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data == {
        "pr": 843,
        "type": "feat",
        "summary": "Add SSO sign-in.",
        "url": "https://x/pr/843",
        "notes": "",
    }


def test_seed_accepts_placeholder_pr_zero(tmp_path):
    assert _seed(tmp_path, 0, "feat: something") == 0
    assert (tmp_path / ".changes" / "preview" / "0.json").exists()


def test_validate_rejects_missing_fields(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"pr": 1, "type": "feat"}))
    assert cl.main(["validate", str(bad)]) == 1


def test_validate_rejects_bad_type(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"pr": 1, "type": "bogus", "summary": "x", "url": "u"}))
    assert cl.main(["validate", str(p)]) == 1


def test_validate_accepts_good_dir(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert cl.main(["validate", str(tmp_path / ".changes" / "preview")]) == 0


# ---------- check ----------

def test_check_missing_fragment_fails(tmp_path):
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    assert cl.main([
        "check", "--pr", "5", "--changes-dir", str(tmp_path / ".changes")
    ]) == 1


def test_check_passes_when_fragment_present(tmp_path):
    _seed(tmp_path, 5, "feat: hello")
    assert cl.main([
        "check", "--pr", "5", "--changes-dir", str(tmp_path / ".changes")
    ]) == 0


def test_check_fails_on_pr_mismatch(tmp_path):
    _seed(tmp_path, 5, "feat: hello")
    src = tmp_path / ".changes" / "preview" / "5.json"
    dst = tmp_path / ".changes" / "preview" / "7.json"
    src.rename(dst)
    assert cl.main([
        "check", "--pr", "7", "--changes-dir", str(tmp_path / ".changes")
    ]) == 1


# ---------- render ----------

def test_render_only_preview_when_no_releases(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    text = _render(tmp_path)
    assert text.startswith("# Changelog")
    assert cl.PREVIEW_START in text and cl.PREVIEW_END in text
    assert "### Features" in text
    assert "## [" not in text.split(cl.PREVIEW_END, 1)[1]


def test_render_groups_by_category_and_hides_chore(tmp_path):
    _seed(tmp_path, 843, "feat: Add SSO sign-in")
    _seed(tmp_path, 850, "fix: retry token drop")
    _seed(tmp_path, 855, "doc: retry defaults")
    _seed(tmp_path, 858, "chore: bump aws-lc to 1.34")
    text = _render(tmp_path)

    assert "### Features" in text
    assert "### Fixes" in text
    assert "### Docs" in text
    assert "### Maintenance" not in text  # chore hidden from customer view
    # Order: Features → Fixes → Docs
    assert text.index("### Features") < text.index("### Fixes") < text.index("### Docs")


def test_render_is_idempotent(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    a = _render(tmp_path)
    b = _render(tmp_path)
    assert a == b


def test_render_preserves_summary_punctuation(tmp_path):
    _seed(tmp_path, 1, "fix: Retries no longer drop 429?")
    _seed(tmp_path, 2, "fix: Handle overflow!")
    _seed(tmp_path, 3, "feat: Add SSO")
    text = _render(tmp_path)
    assert "429? (#1)" in text
    assert "overflow! (#2)" in text
    assert "SSO. (#3)" in text
    assert "429?." not in text and "overflow!." not in text


# ---------- rollup: patch ----------

def test_rollup_patch_moves_fragments_and_creates_meta(tmp_path):
    _seed(tmp_path, 1, "feat: initial")
    _seed(tmp_path, 2, "chore: bump")
    assert _rollup(tmp_path, "0.29.0", "2026-08-01") == 0
    assert list((tmp_path / ".changes" / "preview").glob("*.json")) == []
    rel = tmp_path / ".changes" / "latest" / "0.29.0"
    meta = json.loads((rel / "_meta.json").read_text())
    assert meta["version"] == "0.29.0" and meta["date"] == "2026-08-01"
    assert {p.name for p in rel.glob("*.json") if p.name != "_meta.json"} == {"1.json", "2.json"}


def test_rollup_patch_accretes_into_same_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    _rollup(tmp_path, "0.29.1", "2026-08-15")
    latest = tmp_path / ".changes" / "latest"
    assert (latest / "0.29.0").is_dir() and (latest / "0.29.1").is_dir()
    assert not (tmp_path / ".changes" / "0.29.x").exists()
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.29.1] — 2026-08-15" in text
    assert "## [0.29.0] — 2026-08-01" in text
    assert text.index("[0.29.1]") < text.index("[0.29.0]")


def test_rollup_root_hides_chore_only_release(tmp_path):
    _seed(tmp_path, 1, "chore: internal cleanup")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.29.0]" in text
    assert "### Maintenance" not in text


def test_rollup_empty_preview_fails(tmp_path):
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    assert _rollup(tmp_path, "0.1.0", "2026-01-01") == 1


# ---------- rollup: minor / freeze ----------

def test_rollup_minor_freezes_previous_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    _rollup(tmp_path, "0.29.1", "2026-08-15")
    _seed(tmp_path, 3, "feat: tcp_nodelay")
    _rollup(tmp_path, "0.30.0", "2026-08-19")

    changes = tmp_path / ".changes"
    assert (changes / "latest" / "0.30.0").is_dir()
    assert not (changes / "latest" / "0.29.0").exists()
    assert (changes / "0.29.x" / "0.29.0").is_dir()
    assert (changes / "0.29.x" / "0.29.1").is_dir()
    frozen = (changes / "0.29.x" / "CHANGELOG.md").read_text()
    assert cl.PREVIEW_START not in frozen
    assert frozen.startswith("# Changelog — 0.29.x")
    assert "## [0.29.1]" in frozen and "## [0.29.0]" in frozen
    assert "## [0.30.0]" not in frozen

    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.30.0]" in root
    assert "## [0.29.0]" not in root and "## [0.29.1]" not in root
    assert cl.PREVIEW_START in root


def test_rollup_minor_from_empty_latest(tmp_path):
    _seed(tmp_path, 1, "feat: initial")
    assert _rollup(tmp_path, "0.1.0", "2026-01-01") == 0
    assert (tmp_path / ".changes" / "latest" / "0.1.0").is_dir()
    assert [p for p in (tmp_path / ".changes").iterdir()
            if p.is_dir() and p.name.endswith(".x")] == []


def test_rollup_major_freezes_current_minor_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "feat: big change")
    _rollup(tmp_path, "1.0.0", "2027-01-01")
    changes = tmp_path / ".changes"
    assert (changes / "0.29.x" / "0.29.0").is_dir()
    assert (changes / "latest" / "1.0.0").is_dir()


def test_rollup_rejects_duplicate_version(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    assert _rollup(tmp_path, "0.29.0", "2026-08-02") == 2


def test_rollup_bad_semver_rejected(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "notaversion", "2026-01-01") == 2


def test_rollup_bad_date_rejected(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "0.1.0", "not-a-date") == 2


def test_rollup_rejects_downgrade_in_latest(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.1", "2026-08-15")
    _seed(tmp_path, 2, "fix: b")
    assert _rollup(tmp_path, "0.29.0", "2026-08-20") == 2


def test_rollup_rejects_downgrade_vs_frozen_line(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "0.30.0", "2026-08-19")
    _seed(tmp_path, 3, "fix: c")
    assert _rollup(tmp_path, "0.29.1", "2026-08-20") == 2


def test_rollup_patch_requires_matching_minor(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: b")
    argv = [
        "rollup", "--version", "0.30.0", "--date", "2026-08-19",
        "--bump", "patch",
        "--changes-dir", str(tmp_path / ".changes"),
        "--changelog", str(tmp_path / "CHANGELOG.md"),
    ]
    assert cl.main(argv) == 2


# ---------- revert ----------

def test_revert_creates_fragment_keeps_original(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    cl.main([
        "revert", "--original-pr", "843", "--revert-pr", "900",
        "--url", "https://x/pr/900",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    unrel = tmp_path / ".changes" / "preview"
    assert (unrel / "843.json").exists()
    r = json.loads((unrel / "900.json").read_text())
    assert r["type"] == "revert"
    assert "SSO sign-in" in r["summary"]
    text = _render(tmp_path)
    assert "#843" in text and "#900" in text


def test_revert_looks_up_original_in_latest(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    cl.main([
        "revert", "--original-pr", "843", "--revert-pr", "900",
        "--url", "https://x/pr/900",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    r = json.loads((tmp_path / ".changes" / "preview" / "900.json").read_text())
    assert "SSO sign-in" in r["summary"]


def test_revert_looks_up_original_in_frozen_line(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 999, "feat: bump")
    _rollup(tmp_path, "0.30.0", "2026-08-19")
    cl.main([
        "revert", "--original-pr", "843", "--revert-pr", "900",
        "--url", "https://x/pr/900",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    r = json.loads((tmp_path / ".changes" / "preview" / "900.json").read_text())
    assert "SSO sign-in" in r["summary"]


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


def test_render_skips_release_with_malformed_meta(tmp_path, capsys):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    (tmp_path / ".changes" / "latest" / "0.29.0" / "_meta.json").write_text(
        '{"version": "0.29.0"}'
    )
    text = _render(tmp_path)
    assert "## [0.29.0]" not in text
    err = capsys.readouterr().err
    assert "WARN" in err


def test_render_excludes_frozen_lines(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "feat: b")
    _rollup(tmp_path, "0.30.0", "2026-08-19")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.30.0]" in root and "## [0.29.0]" not in root
    frozen = (tmp_path / ".changes" / "0.29.x" / "CHANGELOG.md").read_text()
    assert "## [0.29.0]" in frozen and "## [0.30.0]" not in frozen


def test_rollup_recovers_from_half_freeze(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    latest = tmp_path / ".changes" / "latest"
    frozen = tmp_path / ".changes" / "0.29.x"
    latest.rename(frozen)
    latest.mkdir()
    _seed(tmp_path, 2, "feat: b")
    assert _rollup(tmp_path, "0.30.0", "2026-08-19") == 2

    rc = cl.main([
        "freeze-snapshot", "--line", "0.29.x",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    assert rc == 0
    assert (frozen / "CHANGELOG.md").exists()
    assert _rollup(tmp_path, "0.30.0", "2026-08-19") == 0


def test_freeze_snapshot_rejects_non_frozen_dir(tmp_path):
    (tmp_path / ".changes" / "not-a-line").mkdir(parents=True)
    rc = cl.main([
        "freeze-snapshot", "--line", "not-a-line",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    assert rc == 2


# ---------- list smoke ----------

def test_list_smoke(tmp_path, capsys):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.1.0", "2026-01-01")
    _seed(tmp_path, 2, "fix: b")
    assert cl.main(["list", "--changes-dir", str(tmp_path / ".changes")]) == 0
    out = capsys.readouterr().out
    assert "preview" in out and "latest" in out


# ---------- full lifecycle ----------

def test_full_lifecycle_end_to_end(tmp_path):
    _seed(tmp_path, 843, "feat: SSO sign-in")
    _seed(tmp_path, 850, "fix: idempotency token drop on 429")
    _seed(tmp_path, 858, "chore: bump aws-lc")
    _rollup(tmp_path, "0.29.0", "2026-08-01", highlights="SSO sign-in")

    _seed(tmp_path, 867, "fix: leaking fd on socket teardown")
    _seed(tmp_path, 870, "doc: clarify retry defaults")
    _seed(tmp_path, 872, "fix: null-deref in event loop")
    _render(tmp_path)

    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [Preview]" in root
    assert "#867" in root and "#870" in root and "#872" in root

    _rollup(tmp_path, "0.29.1", "2026-08-15")
    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.29.1] — 2026-08-15" in root
    assert "## [0.29.0] — 2026-08-01" in root
    assert not (tmp_path / ".changes" / "0.29.x").exists()

    _seed(tmp_path, 875, "fix: retry backoff off-by-one")
    _seed(tmp_path, 878, "feat: add tcp_nodelay to socket options")
    _rollup(tmp_path, "0.30.0", "2026-08-19")

    frozen = (tmp_path / ".changes" / "0.29.x" / "CHANGELOG.md").read_text()
    assert frozen.startswith("# Changelog — 0.29.x")
    assert "## [0.29.1]" in frozen and "## [0.29.0]" in frozen
    assert cl.PREVIEW_START not in frozen

    root = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.30.0] — 2026-08-19" in root
    assert "## [0.29.1]" not in root and "## [0.29.0]" not in root
    assert cl.PREVIEW_START in root


# ---------- main-branch shape (--no-preview) ----------

def test_render_no_preview_omits_block(tmp_path):
    _seed(tmp_path, 1, "feat: a")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 2, "fix: in flight")
    cl.main([
        "render", "--no-preview",
        "--changes-dir", str(tmp_path / ".changes"),
        "--changelog", str(tmp_path / "CHANGELOG.md"),
    ])
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert cl.PREVIEW_START not in text
    assert "## [Preview]" not in text
    assert "## [0.29.0]" in text
    assert "#2" not in text  # unreleased work is not on main


def test_rollup_defaults_to_no_preview(tmp_path):
    """rollup runs on the default branch, so it must not emit a Preview block."""
    _seed(tmp_path, 1, "feat: a")
    assert _rollup(tmp_path, "0.29.0", "2026-08-01", preview=False) == 0
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert cl.PREVIEW_START not in text
    assert "## [0.29.0]" in text


def test_frozen_snapshot_hides_chore_like_root(tmp_path):
    """chore is hidden consistently on both surfaces."""
    _seed(tmp_path, 1, "feat: visible")
    _seed(tmp_path, 2, "chore: internal only")
    _rollup(tmp_path, "0.29.0", "2026-08-01")
    _seed(tmp_path, 3, "feat: next line")
    _rollup(tmp_path, "0.30.0", "2026-08-19")
    frozen = (tmp_path / ".changes" / "0.29.x" / "CHANGELOG.md").read_text()
    assert "#1" in frozen
    assert "#2" not in frozen
    assert "### Maintenance" not in frozen


# ---------- PR title convention ----------

import pytest  # noqa: E402


@pytest.mark.parametrize("title", [
    "feat: Add SSO sign-in.",
    "fix: Handle EINTR.",
    "doc: Clarify retry defaults.",
    "docs: Clarify retry defaults.",
    "chore: Bump aws-lc.",
    "revert: Undo #843.",
    "fix(io): Handle EINTR in the pipe loop.",
    "FEAT: Uppercase is tolerated.",
])
def test_check_title_accepts_valid_prefixes(title):
    assert cl.check_title(title) is None


@pytest.mark.parametrize("title", [
    "Add SSO sign-in",
    "wip: half done",
    "feature: wrong word",
    "fix Handle EINTR",
    "fix:",
    "",
    "   ",
    ": no type",
])
def test_check_title_rejects_bad_prefixes(title):
    err = cl.check_title(title)
    assert err is not None
    assert "does not start with a recognised type" in err


def test_check_fails_on_bad_title_even_with_valid_fragment(tmp_path):
    _seed(tmp_path, 5, "fix: Something.")
    rc = cl.main([
        "check", "--pr", "5", "--title", "no prefix at all",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    assert rc == 1


def test_check_passes_with_good_title_and_fragment(tmp_path):
    _seed(tmp_path, 5, "fix: Something.")
    rc = cl.main([
        "check", "--pr", "5", "--title", "fix: Something.",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    assert rc == 0


def test_check_title_only_skips_fragment_requirement(tmp_path):
    """Infra-only PRs: title still enforced, fragment not required."""
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    assert cl.main([
        "check", "--pr", "99", "--title", "chore: CI tweak.", "--no-fragment",
        "--changes-dir", str(tmp_path / ".changes"),
    ]) == 0


def test_check_title_still_enforced_when_fragment_waived(tmp_path):
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    assert cl.main([
        "check", "--pr", "99", "--title", "nope", "--no-fragment",
        "--changes-dir", str(tmp_path / ".changes"),
    ]) == 1


def test_check_without_title_arg_skips_title_check(tmp_path):
    """Backwards compatible: omitting --title checks the fragment only."""
    _seed(tmp_path, 5, "fix: Something.")
    assert cl.main([
        "check", "--pr", "5",
        "--changes-dir", str(tmp_path / ".changes"),
    ]) == 0


def test_check_title_error_names_valid_types(tmp_path):
    err = cl.check_title("nope")
    for t in ("feat", "fix", "doc", "chore", "revert"):
        assert t in err


# ---------- breaking-change marker (`!`) ----------

@pytest.mark.parametrize("title,typ", [
    ("feat!: Drop the v1 API.", "feat"),
    ("fix!: Rename aws_foo_new.", "fix"),
    ("feat(io)!: Drop the legacy socket path.", "feat"),
    ("chore(deps)!: Require CMake 3.20.", "chore"),
    ("revert!: Undo #843.", "revert"),
])
def test_breaking_marker_accepted_and_maps_to_bare_type(title, typ):
    """`!` is Conventional Commits' breaking flag. It is accepted and does not
    change the changelog section -- the ABI label carries severity."""
    assert cl.check_title(title) is None
    assert cl.parse_title(title)[0] == typ


def test_breaking_marker_does_not_leak_into_summary():
    assert cl.parse_title("feat(io)!: Drop X.") == ("feat", "Drop X.")


@pytest.mark.parametrize("title", [
    "feat!x: Drop the v1 API.",
    "feat(io)! Drop the v1 API.",
    "!: Drop the v1 API.",
])
def test_malformed_breaking_marker_still_rejected(title):
    assert cl.check_title(title) is not None


# ---------- revert leniency (D7: titles we do not control) ----------

@pytest.mark.parametrize("title", [
    # GitHub's Revert button / `git revert` output, verbatim from the repos.
    'Revert "Fix CI issues"',                                        # aws-c-http#542
    'Revert "Skip test on Apple"',                                   # aws-c-s3#611
    'Revert "[s3_meta_request]: Retry on ExpiredToken"',              # aws-c-s3#518
    'Revert "add compiler flag `-msse2` for aws-lc on x86 (#291)"',   # builder#298
    # Unbalanced quotes from a nested revert: aws-c-cal#195, as merged.
    'Revert "Revert "Implement runtime check on libcrypto linkage (#186)"',
    # git >= 2.42 renames a revert-of-a-revert to Reapply (git-revert(1)).
    'Reapply "feat: Add SSO sign-in. (#843)"',
    # Case tolerance, and a maintainer-appended PR number.
    'revert "Fix CI issues"',
    'Revert "Fix CI issues" (#543)',
])
def test_generated_revert_titles_accepted(title):
    assert cl.check_title(title) is None
    assert cl.parse_title(title)[0] == "revert"


def test_revert_title_summary_is_normalised_for_render():
    """Strip the quote wrapper so render_entry does not append a period after
    the closing quote."""
    typ, summary = cl.parse_title('Revert "Fix CI issues"')
    assert (typ, summary) == ("revert", "Revert: Fix CI issues")
    assert cl.render_entry({"pr": 42, "type": "revert", "summary": summary}) \
        == "- Revert: Fix CI issues. (#42)"


def test_revert_fragment_lands_in_maintenance():
    assert cl.categorize({"type": "revert"}) == "Maintenance"


@pytest.mark.parametrize("title", [
    # Hand-written reverts ARE in the author's control: use `revert:`.
    "Revert to commit 4c48e60",          # aws-c-io#787, as merged
    "Revert error code ordering",        # aws-c-io#723, as merged
    "Revert win TLS 1.3",                # aws-c-io#712, as merged
    "revert lc pin",                     # aws-c-cal#190, as merged
    "Revert",
    'Revert "',
])
def test_freeform_revert_titles_still_rejected(title):
    err = cl.check_title(title)
    assert err is not None
    assert 'Revert "<original title>"' in err


def test_conventional_revert_prefix_still_accepted():
    assert cl.parse_title("revert: Undo #843.") == ("revert", "Undo #843.")


# ---------- the wider Conventional Commits type set stays out ----------

@pytest.mark.parametrize("title", [
    "build: Bump the CMake floor.",
    "ci: Add an OpenBSD job.",
    "perf: Halve the hash cost.",
    "refactor: Split the channel loop.",
    "test: Deflake the TLS suite.",
    "style: Run clang-format.",
])
def test_extra_conventional_types_rejected(title):
    """Every accepted type must map to a CHANGELOG section; these six have no
    mapping, so they are rejected with the valid set spelled out."""
    err = cl.check_title(title)
    assert err is not None
    assert "chore | doc | feat | fix | revert" in err


# ---------- title and fragment fail independently, in one run ----------

def test_both_failures_reported_in_one_run(tmp_path, capsys):
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    rc = cl.main([
        "check", "--pr", "42", "--title", "Fix wrong libdir on some platforms",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    err = capsys.readouterr().err
    assert rc == 1
    assert "PR title does not start with a recognised type" in err
    assert "no changelog fragment for PR #42" in err


def test_title_failure_alone_names_only_the_title(tmp_path, capsys):
    _seed(tmp_path, 42, "fix: Something.")
    rc = cl.main([
        "check", "--pr", "42", "--title", "Fix wrong libdir",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    cap = capsys.readouterr()
    assert rc == 1
    assert "PR title does not start with a recognised type" in cap.err
    assert "no changelog fragment" not in cap.err
    assert "OK: fragment for #42 is present and valid" in cap.out


def test_fragment_failure_alone_names_only_the_fragment(tmp_path, capsys):
    (tmp_path / ".changes" / "preview").mkdir(parents=True)
    rc = cl.main([
        "check", "--pr", "42", "--title", "fix(io): Handle EINTR.",
        "--changes-dir", str(tmp_path / ".changes"),
    ])
    cap = capsys.readouterr()
    assert rc == 1
    assert "no changelog fragment for PR #42" in cap.err
    assert "does not start with a recognised type" not in cap.err
    assert "OK: PR title follows" in cap.out


def test_check_fragment_helper_returns_none_when_valid(tmp_path):
    _seed(tmp_path, 7, "fix: Something.")
    assert cl.check_fragment(str(tmp_path / ".changes"), 7) is None


def test_check_fragment_helper_flags_pr_mismatch(tmp_path):
    _seed(tmp_path, 7, "fix: Something.")
    (tmp_path / ".changes" / "preview" / "7.json").write_text(
        json.dumps({"pr": 8, "type": "fix", "summary": "s",
                    "url": "u", "notes": ""})
    )
    err = cl.check_fragment(str(tmp_path / ".changes"), 7)
    assert err is not None and "declares pr=8" in err


# ---------- dependabot: exempt by prefixing its commits, not by title shape ----------

def test_dependabot_prefixed_title_passes():
    """`.github/dependabot.yml` with commit-message.prefix: chore and
    include: scope makes dependabot emit a passing title with no code change
    here, typed `chore`, which is hidden from the customer changelog."""
    typ, summary = cl.parse_title(
        "chore(deps): bump @actions/core from 1.10.1 to 1.11.0"
    )
    assert typ == "chore"
    assert summary == "bump @actions/core from 1.10.1 to 1.11.0"
    assert typ in cl.HIDDEN_TYPES_CUSTOMER


def test_bare_bump_title_is_rejected_for_humans_too():
    """A `^Bump ` exemption would also exempt human PRs like
    awslabs/aws-c-common#1139 'Bump the minimum stack size to at least 1MB',
    which is a real behaviour change. So there is no title-shape exemption."""
    assert cl.check_title("Bump the minimum stack size to at least 1MB") is not None
    assert cl.check_title("Bump actions/checkout from 4 to 7") is not None
