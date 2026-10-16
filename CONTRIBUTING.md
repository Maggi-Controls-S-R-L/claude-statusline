# Contributing

Thanks for helping improve **claude-statusline**. It is a single-module project
(`statusline.py`) with a pytest suite under `tests/`, packaged with hatchling.

## Development setup

Use a per-project virtual environment — do not install the tooling into your
base Python:

```sh
python -m venv .venv
# Windows:  .venv\Scripts\activate     POSIX:  source .venv/bin/activate
python -m pip install -U pip           # pip >= 25.1 for --group
pip install -e . --group dev
```

## Running the checks

These are exactly what CI runs, so run them before pushing:

```sh
ruff check .
ruff format --check .
mypy statusline.py scripts/preview.py
pytest
```

## Previewing your changes locally

`scripts/preview.py` points the status line of Claude Code sessions opened **in
this project** at the working-tree `statusline.py`, so you can see your changes
live in the session you are working in. The global status line used everywhere
else is not touched.

```sh
python scripts/preview.py on [--refresh N] [--force]   # enable / update
python scripts/preview.py off [--force]                # disable
python scripts/preview.py status                       # active, inactive or foreign
```

- `on` writes a complete `statusLine` block into `.claude/settings.local.json`
  (git-ignored, personal to your machine), running `statusline.py` with the
  interpreter that ran `preview.py`. `--refresh N` adds `refreshInterval: N`
  (seconds); running `on` again updates the block.
- `off` removes that block and leaves every other key alone.
- Both refuse to touch a **foreign** `statusLine` (one that does not run this
  checkout's `statusline.py`) unless you pass `--force`.
- The preview follows **whatever is checked out**, uncommitted changes
  included; `status` prints the current branch as a reminder. Changes to the
  command are picked up live, without restarting the session.

Why the script is strict: a project-local `statusLine` **replaces** the global
one entirely — nested keys are not merged, so a block with only
`refreshInterval` is invalid — and Claude Code skips a settings file with
errors **entirely**, permissions included. The script therefore never rewrites
a file that is not a valid JSON object, never writes a partial block, keeps
the other keys in order, and replaces the file atomically.

## Branching & pull requests

We use a lightweight [GitHub Flow](https://docs.github.com/get-started/using-github/github-flow):

- `main` is always releasable and is **protected** — no direct pushes.
- Do every change on a short-lived branch (`feat/...`, `fix/...`, `docs/...`,
  `chore/...`).
- When the work starts from an issue, put the issue number before the slug:
  `feat/2-session-on-line-1`. Changes without an issue keep the plain form
  (`docs/short-description`).
- Open a **pull request** into `main`. CI (lint, typecheck, tests on
  3.10–3.13) must pass before the PR can merge. Reference the issue in the PR
  description (`Closes #2`) so merging closes it.
- Squash-merge into `main` and delete the branch.

```sh
git checkout -b fix/42-short-description
# ...work, commit...
git push -u origin fix/42-short-description
gh pr create --fill
# once CI is green:
gh pr merge --squash --delete-branch
```

## Test-driven development

Code changes (features and bug fixes) are developed test-first:

1. **Red** — write tests for the new behaviour (or a test reproducing the bug)
   and confirm they fail.
2. **Green** — write the minimum code that makes them pass.
3. **Refactor** — clean up with the suite green.

Commit the failing tests before the implementation, so the PR history shows
the red → green order. CI is expected to fail on that intermediate commit if
you push it; only the PR head must be green to merge. Documentation- and
tooling-only changes are exempt.

Tags are not branches, so the release script (which pushes a `vX.Y.Z` tag) is
unaffected by the `main` protection.

## Versioning

We follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

| Bump  | When                                              | Example         |
| ----- | ------------------------------------------------- | --------------- |
| PATCH | backward-compatible bug fix in the code           | `1.0.0 → 1.0.1` |
| MINOR | backward-compatible new feature                   | `1.0.0 → 1.1.0` |
| MAJOR | breaking change / full restructure                | `1.0.0 → 2.0.0` |

The version lives in **one place**: `__version__` in `statusline.py`. The
package metadata reads it from there (`[tool.hatch.version]` in
`pyproject.toml`), so you never edit it twice.

**Commits are not releases.** Documentation- and tooling-only changes (this
file, the release script, CI tweaks) do **not** move the version — they are not
shipped in the wheel and change nothing for users. They simply ride along with
the next real release. The version only advances when code that ships in the
package changes.

## Release process

A release is cut from a green `main`. Steps:

1. Decide the next version per the table above.
2. On a branch, bump `__version__` in `statusline.py` (e.g. commit
   `chore(release): v1.1.0`).
3. Open a PR, let CI pass, and squash-merge it into `main`.
4. Wait for CI to go green on `main`.
5. From the venv, run the release script:

   ```sh
   python scripts/release.py
   ```

   It re-verifies a clean, up-to-date `main`, that the tag does not yet exist,
   and that all checks pass; then it creates and pushes the annotated `vX.Y.Z`
   tag and opens a GitHub release with auto-generated notes.

The script never edits the version — bumping `__version__` (step 2) stays a
deliberate decision.
