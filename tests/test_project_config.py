from pathlib import Path

from aidycai.application.project_config import _expand_path, load_project_configs


def test_editable_project_config_contains_three_projects():
    configs = load_project_configs()
    names = {item.name for item in configs}
    assert {"AIDYC", "AIDYCWeb", "deunacolombia"} <= names


def test_web_projects_define_browser_and_venv():
    configs = {item.name: item for item in load_project_configs()}
    assert configs["AIDYCWeb"].venv == "auto"
    assert configs["AIDYCWeb"].open_browser is True
    assert configs["AIDYCWeb"].url == "http://127.0.0.1:5000"


def test_expand_path_resolves_home_and_userprofile(monkeypatch, tmp_path):
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    home_path = _expand_path("~/Documentos/Proyectos_AidyC/Aidyc")
    assert home_path == (tmp_path / "Documentos" / "Proyectos_AidyC" / "Aidyc").resolve()

    win_style = _expand_path("%USERPROFILE%/Documentos/Proyectos_AidyC/Aidyc")
    assert win_style == (tmp_path / "Documentos" / "Proyectos_AidyC" / "Aidyc").resolve()
