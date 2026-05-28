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
mypy statusline.py
pytest
```

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
2. Bump `__version__` in `statusline.py`.
3. Commit it, e.g. `chore(release): v1.1.0`, and push to `main`.
4. Wait for CI to go green on that commit.
5. From the venv, run the release script:

   ```sh
   python scripts/release.py
   ```

   It re-verifies a clean, up-to-date `main`, that the tag does not yet exist,
   and that all checks pass; then it creates and pushes the annotated `vX.Y.Z`
   tag and opens a GitHub release with auto-generated notes.

The script never edits the version — bumping `__version__` (step 2) stays a
deliberate decision.
