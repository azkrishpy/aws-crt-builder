# changelog action

Automated changelog with a **two-branch model**:

- `main` carries source code, the fragment JSON files
  (`.changes/preview/<PR>.json`) authors add with their PR, and the
  released `CHANGELOG.md`. Between releases no bot commits land on
  `main`; at release time the rollup rides along in the existing
  `chore(release):` commit that bumps the version file.
- `docs` mirrors `main` and additionally carries the rolling
  `CHANGELOG.md` with a `[Preview]` block. Every merge to `main`
  produces one bot commit on `docs` that replays the change and
  re-renders `CHANGELOG.md`.

The only difference between the two `CHANGELOG.md` files is the
`[Preview]` block: `docs` has it, `main` does not.

Fragments are the human-editable source of truth. `CHANGELOG.md` is
derived and always regenerated end-to-end from the fragments.

## Modes

| Mode              | Trigger                | What it does                                                                       |
|-------------------|------------------------|------------------------------------------------------------------------------------|
| `check`           | PR CI                  | Fail the PR if `.changes/preview/<PR>.json` is missing or invalid.                 |
| `validate`        | ad-hoc                 | Validate every fragment under `.changes/preview/`.                                 |
| `render`          | on `docs`, after merge | Regenerate `CHANGELOG.md` from `.changes/`; `--no-preview` for the `main` shape.   |
| `rollup`          | on `main`, on release  | Open `.changes/<version>/`; on minor/major, freeze the outgoing line first.        |
| `revert`          | revert PR opens        | Write a revert fragment; the original stays. Both entries appear in the log.       |
| `snapshot`        | recovery only          | Re-render a closed line's frozen `CHANGELOG.md` if it went missing.                |
| `list`            | ad-hoc                 | Print preview fragments and every released line for debugging.                     |

The docs-branch workflow serializes on a single concurrency group so
concurrent merges never race on `CHANGELOG.md`:

```yaml
concurrency:
  group: changelog-docs
  cancel-in-progress: false
```

## Directory layout (identical on both branches)

```
.changes/
├── preview/                        in-flight fragments awaiting the next release
│   └── <pr>.json
├── <version>/                      one dir per release, e.g. 0.29.0/
│   ├── _meta.json                  { version, date, highlights }
│   ├── <pr>.json                   the fragments that shipped in it
│   └── CHANGELOG.md                only in a closed line's *final* release:
│                                   that line's frozen snapshot
└── …
CHANGELOG.md                        current minor line (+ [Preview] on docs)
```

There is no `latest/` directory and nothing is ever renamed. Releases
are grouped into minor lines by parsing semver off the directory names,
so `0.29.0/` and `0.29.1/` are recognised as the `0.29.x` line. That
makes every operation idempotent and safe to re-run.

Root `CHANGELOG.md` shows every release in the **current** minor line,
newest first. Closed lines are intentionally excluded — the snapshot in
the line's final release dir (e.g. `.changes/0.29.1/CHANGELOG.md`) is
the canonical, immutable record for that line. That is what keeps the
root file openable in a browser indefinitely.

Directory sort caveat: filesystem lex sort orders `0.10.0/` before
`0.2.0/`. This does not affect any customer-facing surface — the
renderer sorts semver correctly. Only `ls .changes/` looks wrong.

## Contributor flow

1. Open a PR against `main`.
2. Create `.changes/preview/<PR>.json` on your PR branch. The JSON is
   five fields — copy the template from the PR body, or generate it:

   ```
   python3 <path-to>/changelog.py seed \
     --pr <N> --title "<PR title>" --url "<PR URL>"
   # → JSON on stdout; paste into .changes/preview/<N>.json
   ```

3. Commit and push. CI runs `check` and fails if the fragment is
   missing or invalid. Apply the `skip-changelog` label only for
   CI-only / pure-infra PRs.

You never touch `CHANGELOG.md` or the `docs` branch.

## What happens after merge

The `changelog-render` workflow fires on merge to `main`:

1. Checks out `docs` (creates it from `main` on first run).
2. Cherry-picks the merge commit onto `docs` (with `-Xno-renames` so
   post-rollup path changes don't confuse git).
3. Runs `render` and folds any `CHANGELOG.md` change into the same
   commit (`git commit --amend`). The render is unconditional — cheaper
   than deciding whether the commit touched fragments, and it self-heals
   drift. A no-op render amends nothing.
4. Pushes `docs`.

A cherry-pick conflict confined to `CHANGELOG.md` is auto-resolved by
taking the incoming side, because that file is fully derived and step 3
rewrites it regardless. This is the expected case when replaying a
release commit, whose `CHANGELOG.md` lacks the `[Preview]` block that
`docs` has. A conflict in any other path stops the job.

Result: one commit on `docs` per merge on `main`, with the original PR
title as the subject. Between releases `main` is never touched by the bot.

## What happens on release

There is no rollup workflow. `cut-release.sh` in the `auto-release`
action runs `rollup` on `main` between writing the version file and
committing, so `VERSION` and `CHANGELOG.md` land in one
`chore(release):` commit and can never disagree about what shipped.

- **Patch bump**: fragments in `preview/` move into
  `.changes/<version>/` and root `CHANGELOG.md` gains a dated section.
  The line stays open; no snapshot is written.
- **Minor / major bump**: the outgoing line's frozen `CHANGELOG.md`
  snapshot is written into its final release dir, then
  `.changes/<version>/` opens the new line and root `CHANGELOG.md`
  resets to just that release.

The `preview` fragments become the versioned section — no ceremony, no
separate promotion step.

Repos without a `.changes/` directory skip the step entirely, so the
release action stays safe to share. A release with no fragments is
allowed: the version bump proceeds on its own.

## PR conventions

The seed helper reads Conventional-Commit-style PR titles:

```
<type>: <customer-facing summary>
  type ∈ { feat | fix | doc | chore | revert }
```

Titles without a recognised prefix are treated as `chore`.

## Local testing

```
python3 -m pip install --user pytest
python3 -m pytest .github/actions/changelog/tests -v
```

Ad-hoc CLI (operates on the current working tree):

```
python3 .github/actions/changelog/scripts/changelog.py seed \
  --pr 843 --title "feat: Add SSO sign-in." --url https://x/pr/843
python3 .github/actions/changelog/scripts/changelog.py render              # docs shape
python3 .github/actions/changelog/scripts/changelog.py render --no-preview # main shape
python3 .github/actions/changelog/scripts/changelog.py rollup \
  --version 0.29.0 --date 2026-08-19 --bump minor --highlights "SSO sign-in"
python3 .github/actions/changelog/scripts/changelog.py list
python3 .github/actions/changelog/scripts/changelog.py snapshot --line 0.29.x
```

## Example workflows

`examples/changelog-check.yml` and `examples/changelog-render.yml`.
Copy into a consumer repo's `.github/workflows/`. There is no rollup
workflow — see "What happens on release".

`check` runs through the composite action (`uses:`). `render` needs raw
git access to the `docs` branch, so it runs inline and checks this repo
out to `.crt-builder/` to reach `changelog.py`. Pin that `ref:` to a
tag or SHA in production.

## Reverts

Revert PRs write a new fragment referencing both PRs; the original
fragment is never deleted. Both entries appear in the changelog — the
original change and its revert — so history is truthful.

## Operational notes

- **Signed-commits repos:** the bot identity used by the render
  workflow and by `cut-release.sh` must have a signing key configured,
  otherwise its pushes will be rejected.
- **Bootstrap:** on first run the render workflow creates `docs` from
  the parent of the triggering commit, so the first replay is
  meaningful.
- **Recovery:** if a closed line's snapshot goes missing, the next
  rollup refuses to run and names the `snapshot --line` command to fix
  it. Nothing is lost — the snapshot regenerates from the fragments.

## Fragment schema

```json
{
  "pr": 843,
  "type": "feat",
  "summary": "Add SSO sign-in for enterprise accounts.",
  "url": "https://github.com/awslabs/aws-c-io/pull/843",
  "notes": ""
}
```

- `type`: `feat | fix | doc | chore | revert`
- `notes`: optional free-form multi-line addendum, indented under the entry on render
