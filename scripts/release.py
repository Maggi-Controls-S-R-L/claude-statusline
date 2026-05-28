#!/usr/bin/env python3
"""Cut a release: verify, tag, push, and open a GitHub release.

Run this from the repo root (inside the project venv) *after* you have bumped
``__version__`` in ``statusline.py`` and pushed that commit to ``main``. The
script never edits the version itself — choosing the next version is a
deliberate human decision (see CONTRIBUTING.md).

What it does, aborting on the first problem:

1. reads the version from ``statusline.py``;
2. checks the working tree is clean and you are on an up-to-date ``main``;
3. checks the ``vX.Y.Z`` tag does not already exist;
4. runs the full check suite (ruff, mypy, pytest);
5. creates and pushes the annotated tag, then opens a GitHub release.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "statusline.py"


def fail(message: str) -> None:
    sys.exit(f"error: {message}")


def run(*args: str, capture: bool = False) -> str:
    """Run a command from the repo root, aborting the release if it fails."""
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=capture)
    if result.returncode != 0:
        if capture and result.stderr:
            sys.stderr.write(result.stderr)
        fail(f"command failed: {' '.join(args)}")
    return (result.stdout or "").strip() if capture else ""


def read_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        fail("could not find __version__ in statusline.py")
    return match.group(1)  # type: ignore[union-attr]


def preflight(tag: str) -> None:
    if run("git", "status", "--porcelain", capture=True):
        fail("working tree is not clean; commit or stash first")

    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True)
    if branch != "main":
        fail(f"not on main (on {branch!r}); release from main")

    if run("git", "tag", "--list", tag, capture=True):
        fail(f"tag {tag} already exists; bump __version__ before releasing")

    run("git", "fetch", "--quiet", "origin", "main")
    local = run("git", "rev-parse", "HEAD", capture=True)
    remote = run("git", "rev-parse", "origin/main", capture=True)
    if local != remote:
        fail("local main differs from origin/main; push or pull first")


def verify() -> None:
    print("Running checks (ruff, mypy, pytest) ...")
    py = sys.executable
    run(py, "-m", "ruff", "check", ".")
    run(py, "-m", "ruff", "format", "--check", ".")
    run(py, "-m", "mypy", "statusline.py")
    run(py, "-m", "pytest", "-q")


def main() -> None:
    version = read_version()
    tag = f"v{version}"

    preflight(tag)
    verify()

    print(f"Releasing {tag} ...")
    run("git", "tag", "-a", tag, "-m", f"claude-statusline {version}")
    run("git", "push", "origin", tag)
    run("gh", "release", "create", tag, "--title", tag, "--generate-notes")
    print(f"Done: released {tag}")


if __name__ == "__main__":
    main()
