from pathlib import Path

import pytest

from aidycai.application.bootstrap import open_app
from aidycai.domain.exceptions import DuplicateProjectError, InvalidPathError, ProjectNotFoundError
from aidycai.infrastructure.scanner import DEFAULT_EXCLUDES


def _make_project_tree(root: Path) -> Path:
    project = root / "sample"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("git", encoding="utf-8")
    (project / ".venv" / "lib").mkdir(parents=True)
    (project / ".venv" / "lib" / "x.py").write_text("x\n", encoding="utf-8")
    (project / "node_modules" / "pkg").mkdir(parents=True)
    (project / "node_modules" / "pkg" / "index.js").write_text("js\n", encoding="utf-8")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"pyc")
    (project / "README.md").write_text("readme\n", encoding="utf-8")
    return project


def test_add_and_list_project(tmp_path):
    project_dir = _make_project_tree(tmp_path)
    with open_app(seed=False) as app:
        added = app.registry.add("Demo", project_dir)
        names = [item.name for item in app.registry.list_projects()]
    assert added.id == "demo"
    assert names == ["Demo"]


def test_remove_does_not_delete_project_files(tmp_path):
    project_dir = _make_project_tree(tmp_path)
    marker = project_dir / "README.md"
    with open_app(seed=False) as app:
        app.registry.add("KeepFiles", project_dir)
        removed = app.registry.remove("KeepFiles")
        remaining = app.registry.list_projects()
    assert removed.name == "KeepFiles"
    assert remaining == []
    assert marker.is_file()
    assert project_dir.is_dir()


def test_invalid_path_does_not_exist(tmp_path):
    missing = tmp_path / "nope"
    with open_app(seed=False) as app:
        with pytest.raises(InvalidPathError):
            app.registry.add("Missing", missing)


def test_invalid_path_is_file(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with open_app(seed=False) as app:
        with pytest.raises(InvalidPathError):
            app.registry.add("File", file_path)


def test_duplicate_name_is_rejected(tmp_path):
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    with open_app(seed=False) as app:
        app.registry.add("AIDYC", first)
        with pytest.raises(DuplicateProjectError):
            app.registry.add("aidyc", second)


def test_duplicate_path_is_rejected(tmp_path):
    project_dir = tmp_path / "shared"
    project_dir.mkdir()
    with open_app(seed=False) as app:
        app.registry.add("One", project_dir)
        with pytest.raises(DuplicateProjectError):
            app.registry.add("Two", project_dir)


def test_unknown_project_raises(tmp_path):
    with open_app(seed=False) as app:
        with pytest.raises(ProjectNotFoundError):
            app.registry.info("ghost")


def test_enable_disable_and_set_path(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    with open_app(seed=False) as app:
        app.registry.add("MoveMe", first)
        disabled = app.registry.set_active("MoveMe", False)
        moved = app.registry.set_path("moveme", second)
        info = app.registry.info("MoveMe")
        assert app.registry.path_exists("MoveMe") is True
    assert disabled.active is False
    assert moved.path == second.resolve()
    assert info.status == "inactive"


def test_info_uses_scanner_and_extra_excludes(tmp_path):
    project_dir = _make_project_tree(tmp_path)
    (project_dir / "uploads").mkdir()
    (project_dir / "uploads" / "big.bin").write_bytes(b"12345")
    with open_app(seed=False) as app:
        app.registry.add("Web", project_dir, extra_excludes=["uploads"])
        info = app.registry.info("Web")
    assert info.scan.exists is True
    assert info.scan.file_count == 2
    assert info.scan.skipped_dir_count >= 4
    assert ".py" in info.scan.extensions
    assert {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"} <= set(DEFAULT_EXCLUDES)
