from pathlib import Path

from aidycai.infrastructure.scanner import DEFAULT_EXCLUDES, FileSystemScanner


def _tree(root: Path) -> Path:
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("n\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")
    (root / ".venv" / "Lib").mkdir(parents=True)
    (root / ".venv" / "Lib" / "x.py").write_text("v\n", encoding="utf-8")
    (root / "venv" / "Lib" / "site-packages").mkdir(parents=True)
    (root / "venv" / "Lib" / "site-packages" / "x.py").write_text("v\n", encoding="utf-8")
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "node_modules" / "left-pad" / "index.js").write_text("js\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"0")
    (root / "README.md").write_text("r\n", encoding="utf-8")
    return root


def test_scan_missing_path(tmp_path):
    stats = FileSystemScanner().scan(tmp_path / "absent")
    assert stats.exists is False
    assert stats.status == "missing"
    assert stats.file_count == 0


def test_scan_ignores_default_directories(tmp_path):
    root = _tree(tmp_path / "proj")
    stats = FileSystemScanner().scan(root)
    assert stats.exists is True
    assert stats.is_dir is True
    assert stats.file_count == 3
    assert stats.skipped_dir_count == 5
    assert stats.extensions[".py"] == 1
    assert stats.extensions[".md"] == 2
    assert stats.total_bytes > 0
    assert "venv" in DEFAULT_EXCLUDES
    assert ".venv" in DEFAULT_EXCLUDES
    assert "node_modules" in DEFAULT_EXCLUDES
    assert "__pycache__" in DEFAULT_EXCLUDES


def test_scan_extra_excludes(tmp_path):
    root = _tree(tmp_path / "proj")
    stats = FileSystemScanner().scan(root, extra_excludes=["docs"])
    assert stats.file_count == 2
    assert ".md" in stats.extensions
    assert stats.extensions[".md"] == 1


def test_scan_file_is_not_a_directory(tmp_path):
    file_path = tmp_path / "only.txt"
    file_path.write_text("x", encoding="utf-8")
    stats = FileSystemScanner().scan(file_path)
    assert stats.exists is True
    assert stats.is_dir is False
    assert stats.status == "not-a-directory"
