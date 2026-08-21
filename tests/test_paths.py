from pathlib import Path

from aidycai.infrastructure.paths import DataLayout, get_data_dir


def test_get_data_dir_uses_override(isolate_aidycai_data):
    assert get_data_dir() == isolate_aidycai_data.resolve()


def test_get_data_dir_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("AIDYCAI_DATA_DIR", raising=False)
    local = tmp_path / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert get_data_dir() == (local / "AIDYCAI").resolve()


def test_layout_creates_expected_folders(isolate_aidycai_data):
    layout = DataLayout()
    layout.ensure()
    assert layout.database_dir.is_dir()
    assert layout.projects_dir.is_dir()
    assert layout.logs_dir.is_dir()
    assert layout.cache_dir.is_dir()
    assert layout.database_path.parent == layout.database_dir
    assert isolate_aidycai_data.resolve() == layout.root
    assert "OneDrive" not in layout.root.parts


def test_data_dir_is_not_inside_source_tree():
    source = Path(__file__).resolve().parents[1]
    layout = DataLayout()
    assert layout.root != source
    try:
        inside_source = layout.root.is_relative_to(source)
    except ValueError:
        inside_source = False
    assert not inside_source
