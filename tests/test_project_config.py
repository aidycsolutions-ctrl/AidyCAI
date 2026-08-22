from pathlib import Path

from aidycai.application.project_config import load_project_configs


def test_editable_project_config_contains_three_projects():
    configs = load_project_configs()
    names = {item.name for item in configs}
    assert {"AIDYC", "AIDYCWeb", "deunacolombia"} <= names


def test_web_projects_define_browser_and_venv():
    configs = {item.name: item for item in load_project_configs()}
    assert configs["AIDYCWeb"].venv == "venv"
    assert configs["AIDYCWeb"].open_browser is True
    assert configs["AIDYCWeb"].url == "http://127.0.0.1:5000"
