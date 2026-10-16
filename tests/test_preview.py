"""Tests for scripts/preview.py.

Every test works on a temporary repo root (``tmp_path``); none of them touches
the repository's real ``.claude/settings.local.json``.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "preview.py"
FOREIGN = {"type": "command", "command": "python /somewhere/else/statusline.py"}


@pytest.fixture
def preview() -> ModuleType:
    spec = importlib.util.spec_from_file_location("preview", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "repo"


def settings_file(root: Path) -> Path:
    return root / ".claude" / "settings.local.json"


def write(root: Path, content: str) -> Path:
    path = settings_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(root: Path, data: Any) -> Path:
    return write(root, json.dumps(data, indent=2) + "\n")


def read_json(root: Path) -> Any:
    return json.loads(settings_file(root).read_text(encoding="utf-8"))


def script_path(root: Path) -> str:
    return (root / "statusline.py").resolve().as_posix()


# ── on ────────────────────────────────────────────────────────────────────
class TestOn:
    def test_creates_directory_and_file(self, preview, root):
        assert preview.main(["on"], root=root) == 0
        block = read_json(root)["statusLine"]
        assert block["type"] == "command"
        assert script_path(root) in block["command"]
        assert "refreshInterval" not in block

    def test_command_uses_running_interpreter_quoted(self, preview, root):
        preview.main(["on"], root=root)
        command = read_json(root)["statusLine"]["command"]
        python = Path(sys.executable).absolute().as_posix()
        assert command == f'"{python}" "{script_path(root)}"'

    def test_refresh_interval(self, preview, root):
        preview.main(["on", "--refresh", "5"], root=root)
        assert read_json(root)["statusLine"]["refreshInterval"] == 5

    @pytest.mark.parametrize("value", ["0", "-3", "abc", "1.5"])
    def test_refresh_must_be_positive_integer(self, preview, root, value):
        with pytest.raises(SystemExit) as exc:
            preview.main(["on", "--refresh", value], root=root)
        assert exc.value.code != 0
        assert not settings_file(root).exists()

    def test_preserves_other_keys_and_order(self, preview, root):
        write_json(root, {"permissions": {"allow": ["x"]}, "env": {"A": "1"}})
        preview.main(["on"], root=root)
        data = read_json(root)
        assert list(data) == ["permissions", "env", "statusLine"]
        assert data["permissions"] == {"allow": ["x"]}
        assert data["env"] == {"A": "1"}

    def test_updates_own_block_in_place(self, preview, root):
        write_json(root, {"permissions": {}, "env": {}})
        preview.main(["on", "--refresh", "5"], root=root)
        assert preview.main(["on", "--refresh", "10"], root=root) == 0
        data = read_json(root)
        assert data["statusLine"]["refreshInterval"] == 10
        assert list(data) == ["permissions", "env", "statusLine"]
        preview.main(["on"], root=root)
        assert "refreshInterval" not in read_json(root)["statusLine"]

    def test_own_block_keeps_its_position(self, preview, root):
        preview.main(["on"], root=root)
        data = read_json(root)
        data["env"] = {"A": "1"}
        write_json(root, data)
        preview.main(["on", "--refresh", "3"], root=root)
        assert list(read_json(root)) == ["statusLine", "env"]

    def test_foreign_block_aborts(self, preview, root, capsys):
        path = write_json(root, {"statusLine": FOREIGN})
        before = path.read_bytes()
        assert preview.main(["on"], root=root) != 0
        assert path.read_bytes() == before
        assert "foreign" in capsys.readouterr().err.lower()

    def test_foreign_block_overwritten_with_force(self, preview, root):
        write_json(root, {"permissions": {}, "statusLine": FOREIGN})
        assert preview.main(["on", "--force"], root=root) == 0
        assert script_path(root) in read_json(root)["statusLine"]["command"]

    def test_output_format(self, preview, root):
        write_json(root, {"permissions": {"allow": ["é"]}})
        preview.main(["on"], root=root)
        text = settings_file(root).read_bytes().decode("utf-8")
        assert text.endswith("}\n")
        assert '\n  "permissions": {' in text
        assert "é" in text
        assert "\r\n" not in text


# ── off ───────────────────────────────────────────────────────────────────
class TestOff:
    def test_removes_own_block_only(self, preview, root):
        write_json(root, {"permissions": {"allow": ["x"]}})
        preview.main(["on"], root=root)
        assert preview.main(["off"], root=root) == 0
        assert read_json(root) == {"permissions": {"allow": ["x"]}}

    def test_leaves_empty_object(self, preview, root):
        preview.main(["on"], root=root)
        preview.main(["off"], root=root)
        assert settings_file(root).exists()
        assert read_json(root) == {}

    def test_no_block_is_noop(self, preview, root, capsys):
        path = write_json(root, {"permissions": {}})
        before = path.read_bytes()
        assert preview.main(["off"], root=root) == 0
        assert path.read_bytes() == before
        assert capsys.readouterr().out.strip()

    def test_no_file_is_noop(self, preview, root):
        assert preview.main(["off"], root=root) == 0
        assert not settings_file(root).exists()

    def test_foreign_block_aborts(self, preview, root, capsys):
        path = write_json(root, {"statusLine": FOREIGN})
        before = path.read_bytes()
        assert preview.main(["off"], root=root) != 0
        assert path.read_bytes() == before
        assert "foreign" in capsys.readouterr().err.lower()

    def test_foreign_block_removed_with_force(self, preview, root):
        write_json(root, {"permissions": {}, "statusLine": FOREIGN})
        assert preview.main(["off", "--force"], root=root) == 0
        assert read_json(root) == {"permissions": {}}


# ── invalid input files ───────────────────────────────────────────────────
class TestInvalidFile:
    @pytest.mark.parametrize("command", [["on"], ["on", "--force"], ["off"]])
    @pytest.mark.parametrize(
        "content",
        ['{"permissions": ', "", "[1, 2]", '"text"', "null"]
        + ['{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}'],
    )
    def test_aborts_without_writing(self, preview, root, command, content):
        path = write(root, content)
        before = path.read_bytes()
        assert preview.main(command, root=root) != 0
        assert path.read_bytes() == before
        assert [p.name for p in path.parent.iterdir()] == [path.name]

    def test_status_reports_error(self, preview, root):
        write(root, "{not json")
        assert preview.main(["status"], root=root) != 0

    @pytest.mark.parametrize("command", [["on"], ["off"], ["status"]])
    def test_non_utf8_file_is_a_clean_error(self, preview, root, command, capsys):
        path = write(root, "")
        path.write_bytes(b'{"x": "\xff\xfe"}')
        assert preview.main(command, root=root) == 1
        assert capsys.readouterr().err.startswith("error:")

    @pytest.mark.parametrize("command", [["on"], ["off"], ["status"]])
    def test_unreadable_path_is_a_clean_error(self, preview, root, command, capsys):
        settings_file(root).mkdir(parents=True)
        assert preview.main(command, root=root) == 1
        assert capsys.readouterr().err.startswith("error:")


# ── "statusLine": null is a foreign value everywhere ─────────────────────
class TestNullBlock:
    def test_on_aborts(self, preview, root, capsys):
        path = write_json(root, {"statusLine": None})
        before = path.read_bytes()
        assert preview.main(["on"], root=root) == 1
        assert path.read_bytes() == before
        assert "foreign" in capsys.readouterr().err.lower()

    def test_on_force_overwrites(self, preview, root):
        write_json(root, {"statusLine": None})
        assert preview.main(["on", "--force"], root=root) == 0
        assert script_path(root) in read_json(root)["statusLine"]["command"]

    def test_off_aborts(self, preview, root):
        path = write_json(root, {"statusLine": None})
        before = path.read_bytes()
        assert preview.main(["off"], root=root) == 1
        assert path.read_bytes() == before

    def test_off_force_removes(self, preview, root):
        write_json(root, {"permissions": {}, "statusLine": None})
        assert preview.main(["off", "--force"], root=root) == 0
        assert read_json(root) == {"permissions": {}}

    def test_status_reports_foreign(self, preview, root, capsys):
        write_json(root, {"statusLine": None})
        assert preview.main(["status"], root=root) == 0
        out = capsys.readouterr().out.lower()
        assert "foreign" in out
        assert "null" in out


# ── ownership is an exact path match ──────────────────────────────────────
class TestOwnership:
    def foreign_commands(self, root: Path) -> list[str]:
        path = script_path(root)
        return [
            f'python "{path}.bak"',
            f'python "{path}x"',
            f'python "/other{path}"',
            f'python "{path}/extra"',
        ]

    def test_lookalike_commands_are_foreign(self, preview, root):
        for command in self.foreign_commands(root):
            block = {"type": "command", "command": command}
            assert not preview.is_own(block, root), command

    def test_lookalike_block_needs_force(self, preview, root):
        for command in self.foreign_commands(root):
            block = {"type": "command", "command": command}
            path = write_json(root, {"statusLine": block})
            before = path.read_bytes()
            assert preview.main(["on"], root=root) == 1
            assert preview.main(["off"], root=root) == 1
            assert path.read_bytes() == before

    def test_own_quoted_and_unquoted(self, preview, root):
        path = script_path(root)
        for command in (f'python "{path}"', f"python {path}", f'"{path}" --x'):
            block = {"type": "command", "command": command}
            assert preview.is_own(block, root), command


# ── safety: never a partial block, atomic write ───────────────────────────
class TestSafety:
    def test_never_writes_partial_block(self, preview, root, monkeypatch):
        write_json(root, {"permissions": {}})

        def broken_block(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"refreshInterval": 5}

        monkeypatch.setattr(preview, "build_block", broken_block)
        before = settings_file(root).read_bytes()
        assert preview.main(["on"], root=root) != 0
        assert settings_file(root).read_bytes() == before

    def test_interrupted_write_keeps_original(self, preview, root, monkeypatch, capsys):
        path = write_json(root, {"permissions": {"allow": ["x"]}})
        before = path.read_bytes()

        def boom(src: Any, dst: Any) -> None:
            raise OSError("simulated crash")

        monkeypatch.setattr(os, "replace", boom)
        assert preview.main(["on"], root=root) == 1
        assert "simulated crash" in capsys.readouterr().err
        assert path.read_bytes() == before
        assert [p.name for p in path.parent.iterdir()] == [path.name]

    def test_unencodable_content_is_a_clean_error(self, preview, root, capsys):
        path = root / ".claude" / "settings.local.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"env": {"A": "\\ud800"}}', encoding="utf-8")
        before = path.read_bytes()
        assert preview.main(["on"], root=root) == 1
        assert capsys.readouterr().err.startswith("error:")
        assert path.read_bytes() == before
        assert [p.name for p in path.parent.iterdir()] == [path.name]


# ── status ────────────────────────────────────────────────────────────────
class TestStatus:
    def test_inactive_without_file(self, preview, root, capsys):
        assert preview.main(["status"], root=root) == 0
        out = capsys.readouterr().out.lower()
        assert "inactive" in out
        assert "branch" in out

    def test_inactive_without_block(self, preview, root, capsys):
        write_json(root, {"permissions": {}})
        assert preview.main(["status"], root=root) == 0
        assert "inactive" in capsys.readouterr().out.lower()

    def test_active_with_refresh(self, preview, root, capsys):
        preview.main(["on", "--refresh", "7"], root=root)
        capsys.readouterr()
        assert preview.main(["status"], root=root) == 0
        out = capsys.readouterr().out
        assert "active" in out.lower()
        assert "inactive" not in out.lower()
        assert script_path(root) in out
        assert "7" in out

    def test_foreign(self, preview, root, capsys):
        write_json(root, {"statusLine": FOREIGN})
        assert preview.main(["status"], root=root) == 0
        out = capsys.readouterr().out
        assert "foreign" in out.lower()
        assert FOREIGN["command"] in out

    def test_reports_git_branch(self, preview, root, capsys, monkeypatch):
        monkeypatch.setattr(preview, "current_branch", lambda _root: "feat/x")
        preview.main(["status"], root=root)
        assert "feat/x" in capsys.readouterr().out
