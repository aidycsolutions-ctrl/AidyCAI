from pathlib import Path

from aidycai.services.workspace_service import is_probably_text, visible_children


def test_visible_children_ignores_runtime_directories(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")

    names = [p.name for p in visible_children(tmp_path)]
    assert names == ["src", "main.py"]


def test_text_detection():
    assert is_probably_text(Path("main.py"))
    assert is_probably_text(Path("config.json"))
    assert not is_probably_text(Path("photo.png"))
