#!/usr/bin/env python3
"""Toggle a local preview of the working-tree status line.

Claude Code sessions opened in this project read ``.claude/settings.local.json``
(git-ignored, personal to the machine). This script writes a ``statusLine``
block there that runs *this* checkout's ``statusline.py``, so a contributor
sees their changes live in the session they are working in, while the global
status line stays untouched everywhere else::

    python scripts/preview.py on [--refresh N] [--force]
    python scripts/preview.py off [--force]
    python scripts/preview.py status

How Claude Code treats a project-local ``statusLine``:

* the block **replaces** the global one entirely (nested keys are not merged),
  so it must always be complete — a block with only ``refreshInterval`` is
  invalid;
* a settings file with errors is skipped **entirely**, permissions included;
* a change to ``command`` is picked up live, without restarting the session.

Hence the safety rules: an existing file that is not a valid JSON object is
never rewritten, a partial block is never written, every other key is kept in
its original order, and the file is replaced atomically.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = Path(".claude") / "settings.local.json"
KEY = "statusLine"


class PreviewError(Exception):
    """A condition that aborts the command without touching the file."""


# ── settings file I/O ─────────────────────────────────────────────────────
def _reject_constant(name: str) -> Any:
    """``json.loads`` hook: NaN and the infinities are not valid JSON."""
    raise ValueError(f"non-standard constant {name}")


def load_settings(path: Path) -> dict[str, Any]:
    """Read the settings object; a missing file counts as ``{}``."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PreviewError(f"cannot read {path} ({exc})") from exc
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:  # JSONDecodeError is a ValueError
        raise PreviewError(f"{path} is not valid JSON ({exc}); fix it first") from exc
    if not isinstance(data, dict):
        raise PreviewError(f"{path} does not contain a JSON object; fix it first")
    return data


def check_block(block: Any) -> None:
    """Refuse to write a ``statusLine`` block Claude Code would reject."""
    if not (
        isinstance(block, dict)
        and block.get("type") == "command"
        and isinstance(block.get("command"), str)
        and block["command"]
    ):
        raise PreviewError(f"refusing to write an incomplete {KEY} block: {block!r}")
    refresh = block.get("refreshInterval")
    if refresh is not None and (
        isinstance(refresh, bool) or not isinstance(refresh, int) or refresh < 1
    ):
        raise PreviewError(f"refusing to write refreshInterval={refresh!r}")


def save_settings(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` atomically: temporary file in the same dir, then replace."""
    if KEY in data:
        check_block(data[KEY])
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    tmp: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException as exc:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise PreviewError(
                f"cannot write {path} ({exc}); file left unchanged"
            ) from exc
        raise


# ── the preview block ─────────────────────────────────────────────────────
def script_path(root: Path) -> str:
    return (root / "statusline.py").resolve().as_posix()


def build_block(
    root: Path, refresh: int | None = None, python: str = sys.executable
) -> dict[str, Any]:
    """The complete block pointing at ``root``'s ``statusline.py``."""
    interpreter = Path(python).absolute().as_posix()
    block: dict[str, Any] = {
        "type": "command",
        "command": f'"{interpreter}" "{script_path(root)}"',
    }
    if refresh is not None:
        block["refreshInterval"] = refresh
    return block


def is_own(block: Any, root: Path) -> bool:
    """True when ``block`` runs this repo's ``statusline.py``."""
    if not isinstance(block, dict):
        return False
    command = block.get("command")
    if not isinstance(command, str):
        return False
    # The path must be a whole token: bounded by a quote, whitespace or the
    # ends of the command, so ``statusline.py.bak`` or a longer path that merely
    # ends with ours does not count.
    target = re.escape(os.path.normcase(script_path(root)))
    pattern = r'(?<![^\s"])' + target + r'(?![^\s"])'
    return re.search(pattern, os.path.normcase(command)) is not None


def describe(block: Any) -> str:
    if isinstance(block, dict) and isinstance(block.get("command"), str):
        return str(block["command"])
    return json.dumps(block, ensure_ascii=False)


def current_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch else "unknown"


# ── sub-commands ──────────────────────────────────────────────────────────
def turn_on(root: Path, refresh: int | None = None, force: bool = False) -> str:
    path = root / SETTINGS
    data = load_settings(path)
    present = KEY in data  # an explicit null counts as a (foreign) block
    existing = data.get(KEY)
    if present and not is_own(existing, root) and not force:
        raise PreviewError(
            f"a foreign {KEY} is present in {path} ({describe(existing)}); "
            "use --force to overwrite it"
        )
    data[KEY] = build_block(root, refresh)
    save_settings(path, data)
    verb = "updated" if present else "enabled"
    return f"preview {verb}: {data[KEY]['command']}"


def turn_off(root: Path, force: bool = False) -> str:
    path = root / SETTINGS
    data = load_settings(path)
    if KEY not in data:
        return f"no {KEY} in {path}; nothing to do"
    existing = data[KEY]
    if not is_own(existing, root) and not force:
        raise PreviewError(
            f"a foreign {KEY} is present in {path} ({describe(existing)}); "
            "use --force to remove it"
        )
    del data[KEY]
    save_settings(path, data)
    return "preview disabled; the global status line applies again"


def status(root: Path) -> str:
    data = load_settings(root / SETTINGS)
    block: Any = data.get(KEY)
    if KEY not in data:
        lines = ["preview: inactive"]
    elif is_own(block, root):
        refresh = block.get("refreshInterval")
        lines = [
            "preview: active",
            f"  command: {block['command']}",
            f"  refreshInterval: {refresh if refresh is not None else 'not set'}",
        ]
    else:
        lines = [f"preview: inactive (foreign {KEY} present: {describe(block)})"]
    lines.append(
        f"branch: {current_branch(root)} "
        "(the preview follows the working tree, uncommitted changes included)"
    )
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────
def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value!r}")
    return number


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Toggle a local preview of the working-tree status line."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on", help="point this project's status line here")
    on.add_argument(
        "--refresh", type=positive_int, metavar="N", help="refreshInterval (s)"
    )
    on.add_argument("--force", action="store_true", help="overwrite a foreign block")
    off = sub.add_parser("off", help="remove the preview block")
    off.add_argument("--force", action="store_true", help="remove a foreign block")
    sub.add_parser("status", help="show whether the preview is active")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    args = parse_args(argv)
    try:
        if args.command == "on":
            message = turn_on(root, args.refresh, args.force)
        elif args.command == "off":
            message = turn_off(root, args.force)
        else:
            message = status(root)
    except PreviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
