"""The CI gate: assert a pull request's title and its fragment agree."""

from fragments import BREAKING_SECTION, CATEGORY, STAMPED, VALID_TYPES, parse_title, validate_fragment
from pathlib import Path
import json
import sys


def parse_changed_paths(path, prefix):
    """Read `status<TAB>path` lines, keeping only entries under `prefix`."""
    out = []
    for line in Path(path).read_text().splitlines():
        status, _, p = line.strip().partition("\t")
        if p.startswith(f"{prefix}/"):
            out.append((status, p))
    return out


def check_fragment_changes(args, pr_type, reason):
    """Assert the PR's changes under `prefix` are exactly one new fragment.

    Returns an exit code to stop on, or None to carry on with the usual checks.
    """
    prefix = args.changes_prefix.rstrip("/")
    expected = f"{prefix}/preview/{args.pr}.json"
    entries = parse_changed_paths(args.changed_paths_file, prefix)

    if not entries:
        # Nothing under .changes/ at all -- the normal "author forgot" case,
        # which the fragment check below reports and which earns a template.
        return None

    wrong = [(st, p) for st, p in entries if p != expected]
    if wrong:
        listed = "\n".join(f"         {st:<10} {p}" for st, p in wrong)
        print(
            f"ERROR: a `{pr_type}` change may only add its own changelog fragment.\n"
            f"       expected exactly one new file:\n"
            f"         added      {expected}\n"
            f"       but this pull request also changes:\n{listed}\n"
            f"       A fragment named for another pull request renders under that\n"
            f"       number; one at another path renders nowhere, and a released\n"
            f"       entry is already published.",
            file=sys.stderr,
        )
        reason("stray-fragment")
        return 1

    status = entries[0][0]
    if status != "added":
        print(
            f"ERROR: {expected} is `{status}` in this pull request, not `added`.\n"
            f"       That path already exists on the base branch, so this pull\n"
            f"       request is rewriting a released or in-flight entry rather than\n"
            f"       contributing its own. Move the change to a new fragment.",
            file=sys.stderr,
        )
        reason("modified-fragment")
        return 1

    return None


def cmd_check(args):
    """CI gate. Exit 0 pass, 1 author-fixable, 2 caller error.

    Two independent assertions:
      * the PR title follows the convention, so a type can be derived at all;
      * a fragment exists and agrees with that type -- unless the type is
        exempt (chore), or the author is a bot we waive.
    """
    title = (args.title or "").strip()
    frag = Path(args.changes_dir) / "preview" / f"{args.pr}.json"

    # A single machine-readable reason on stdout, so a caller can tell an
    # author who does not know the convention (missing-fragment -> show them a
    # template) from one who does (everything else -> just the diagnostic).
    def reason(tag):
        print(f"CHANGELOG_CHECK_REASON::{tag}")

    if args.bot_author:
        print(f"OK: #{args.pr} is authored by a bot ({args.bot_author}); "
              "title convention and changelog fragment both waived")
        reason("waived-bot")
        return 0

    if not title:
        print("ERROR: --title is required to derive the change type", file=sys.stderr)
        return 2

    pr_type, _summary = parse_title(title)
    if pr_type is None:
        print(
            f'ERROR: PR title does not follow the convention: "{title}"\n'
            f"       expected `<type>: <summary>` with type one of "
            f"{sorted(VALID_TYPES)}, an optional scope such as `chore(ci):`,\n"
            f'       or the Revert button\'s `Revert "<original title>"`.',
            file=sys.stderr,
        )
        reason("bad-title")
        return 1

    if pr_type not in CATEGORY:
        print(f"OK: #{args.pr} is a `{pr_type}` change; no changelog fragment required")
        reason("exempt-type")
        return 0

    if args.changed_paths_file:
        rc = check_fragment_changes(args, pr_type, reason)
        if rc is not None:
            return rc

    if not frag.exists():
        print(
            f"ERROR: no changelog fragment for PR #{args.pr}.\n"
            f"       expected: {frag}\n"
            f"       a `{pr_type}` change is customer-visible, so it needs an entry.\n"
            f"       commit that file with this pull request -- the bot comments a\n"
            f"       ready-to-paste template.",
            file=sys.stderr,
        )
        reason("missing-fragment")
        return 1

    errs = validate_fragment(frag)
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        reason("invalid-fragment")
        return 1

    data = json.loads(frag.read_text())
    stamped = [k for k in STAMPED if k in data]
    if stamped:
        print(
            f"ERROR: {frag} sets {', '.join(stamped)}, which the release stamps in.\n"
            f"       `impact` decides whether the entry renders under "
            f"\"{BREAKING_SECTION}\"; the ABI check settles that, not the\n"
            f"       pull request. Remove {'them' if len(stamped) > 1 else 'it'}.",
            file=sys.stderr,
        )
        reason("stamped-field")
        return 1

    declared_pr = data.get("pr")
    if declared_pr != args.pr:
        print(
            f"ERROR: {frag} declares pr={declared_pr} but this PR is #{args.pr}",
            file=sys.stderr,
        )
        reason("pr-mismatch")
        return 1

    if data.get("type") != pr_type:
        print(
            f'ERROR: type mismatch. The PR title says `{pr_type}` but {frag} says '
            f'`{data.get("type")}`.\n'
            f"       Fix whichever is wrong -- they must agree.",
            file=sys.stderr,
        )
        reason("type-mismatch")
        return 1

    print(f"OK: #{args.pr} title is `{pr_type}` and its fragment is present and valid")
    reason("ok")
    return 0
