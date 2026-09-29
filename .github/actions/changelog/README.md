# changelog action

Release notes are assembled from per-pull-request fragments, not hand-edited.

- An author commits `.changes/preview/<PR>.json` with their own pull request.
- `CHANGELOG.md` is generated from those fragments and regenerated end to end at
  every release. Nothing appends to it by hand, and no bot commits on a branch an
  author owns.

This action only ever reads and writes files under `.changes/`; it never
touches git. Whether the generated `CHANGELOG.md` lands on the working branch or
on a separate docs branch is the consumer's choice -- `changelog-render.yml` in
aws-c-common replays each merge onto `docs` so the working branch stays free of
bot commits.

## Modes

The composite action exposes three:

| Mode     | Runs                  | What it does                                                                       |
|----------|-----------------------|------------------------------------------------------------------------------------|
| `check`  | pull request          | Assert the title convention and the fragment. Sets `rc` and `reason`; never fails the step itself. |
| `seed`   | pull request          | Write a template fragment, for the bot to paste into a comment.                    |
| `rollup` | release               | Move `preview/` into the new version and regenerate `CHANGELOG.md`.                |

`check` exit codes: `0` pass, `1` the author must fix something, `2` the caller
passed bad arguments. `reason` is one of `ok`, `exempt-type`, `waived-bot`,
`missing-fragment`, `invalid-fragment`, `pr-mismatch`, `type-mismatch`,
`bad-title`, `stray-fragment`, `modified-fragment`. Only `missing-fragment`
earns a comment — every other failure means the author already knows the
convention and just needs the diagnostic.

## What the checks require

- The title follows `<type>: <summary>`, where type is `feat`, `fix`, `chore` or
  `revert`. An optional scope (`fix(io):`) is accepted, as is the Revert
  button's `Revert "<original title>"`.
- A `feat`, `fix` or `revert` needs exactly one fragment, added at exactly
  `.changes/preview/<PR>.json`. A fragment named for another pull request would
  render under that number; one at another path renders nowhere.
- A `chore` needs no fragment: it renders nowhere, so an entry would be
  invisible. A CI-only or pure-infra change is a `chore`, so nothing waives the
  check -- the type already exempts it.
- A bot author waives both the title convention and the fragment.

## Directory layout

```
.changes/
├── preview/<pr>.json               awaiting release; written by the author
├── released/<pr>.json              shipped; stamped with its version and date
├── <M>.<N>.x.md                    archive of a closed minor line
└── …
CHANGELOG.md                        [Preview] + every release in released/
```

A fragment is the only state. `version` and `date` are stamped onto it when it
is released, so a release needs no side file of its own — the releases in
`released/` are just its fragments grouped by the version they carry.

Root `CHANGELOG.md` covers `[Preview]` and the active minor line, newest first,
and links the archives. Each `.changes/<M>.<N>.x.md` is the immutable record for
a line that will take no further releases; nothing regenerates it.

Archiving a line deletes its fragments and keeps only that file. Nothing reads an
archived fragment, and keeping them would add one checked-out file per merged
pull request forever — `git log -- .changes` still has every one.

## Contributor flow

Commit `.changes/preview/<PR>.json` with your pull request. Write `summary` so it
reads as a release note, and use `notes` for detail — for a revert, say why. You
never touch `CHANGELOG.md`.

Forgetting is fine: the check comments a ready-to-paste template with the type
and summary already derived from your title.

In a clone of this repository, `scripts/new-change` writes the fragment
interactively. Consumer repos do not vendor it, so the template comment is the
path there.

## Release flow

`rollup --version` decides the shape of the release:

- **Same minor line as the last release** — a patch. Its fragments join the
  others in `released/`.
- **A new minor or major** — the outgoing line is rendered to
  `.changes/<M>.<N>.x.md` and its fragments are deleted.

Sections render in a fixed order and only when non-empty: **Possible Breaking
Changes**, Features, Fixes, Reverts, Notes. A pull request the ABI check
labelled `minor` renders under Possible Breaking Changes instead of its own type
section — taking that release may require a consumer to change something. The
caller passes those numbers as `minor-prs`; rollup stamps `"impact": "minor"`
into each fragment as it is released, so later renders need no label lookup.

`notes` render as their own section at the end of the release, each led by the
pull request it explains. The release branch's file carries no `[Preview]`
block — only a release rewrites it there, so the block would sit permanently
stale; it points at the docs branch instead, where a merge regenerates it.

A release refuses to proceed if any fragment in `preview/` is invalid, if the
version is not newer than everything released so far, if it belongs to a line
already archived, if `preview/` holds a second fragment for a pull request that
already shipped, or if the version predates 1.0.0 — everything earlier shipped
without fragments, so rolling it up would publish entries that do not exist.

A release that shipped nothing customer-facing renders no section. Its fragments
are kept and stamped; a header with nothing under it would read as a broken file.

Interrupting a release between writing an archive and deleting the fragments it
covers is safe: the archive is a pure function of those fragments, so the next
rollup rewrites it and finishes the delete.

## Adoption

Nothing before 1.0.0 is in the changelog, so a repo adopting this starts at its
first 1.x release with an empty `.changes/released/`. Hand-written history stays
where it is: keep it as `.changes/<M>.<N>.x.md` and the root file links it under
Earlier releases.

## Local testing

```
python3 -m pytest .github/actions/changelog/tests -v
```

## Fragment schema

```json
{
  "pr": 843,
  "type": "feat",
  "summary": "Add SSO sign-in for enterprise accounts.",
  "url": "https://github.com/<org>/<repo>/pull/<PR>",
  "notes": ""
}
```

`pr` must match the filename. `type` is one of `feat | fix | chore | revert` and
decides the section. `notes` is optional free-form multi-line text, rendered as
its own entry under Notes.

`version`, `date` and `impact` are stamped in at release and rejected from an
author's fragment: `impact` decides whether the entry renders under Possible
Breaking Changes, and the ABI check settles that, not the pull request.
