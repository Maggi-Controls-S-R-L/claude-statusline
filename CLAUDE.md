# claude-statusline

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for all changes. In particular:

- **GitHub Flow** — `main` is protected; work on a branch and open a PR.
  Branches that start from an issue carry its number before the slug
  (`feat/2-session-on-line-1`).
- **Test-driven development** — for code changes, commit failing tests first,
  then the implementation.
- **Checks** — run `ruff`, `mypy` and `pytest` from the project `.venv`.
- **Preview** — `python scripts/preview.py on|off|status` toggles this
  project's status line to the working-tree `statusline.py` (see
  CONTRIBUTING.md).
- Repository artifacts (code, comments, docs, commits, issues) are in English.
