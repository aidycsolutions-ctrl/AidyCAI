from pathlib import Path

from aidycai.application.bootstrap import open_app
from aidycai.infrastructure.database import connect


def test_sqlite_persists_projects_between_sessions(tmp_path, isolate_aidycai_data):
    project_dir = tmp_path / "persisted"
    project_dir.mkdir()
    with open_app(seed=False) as app:
        app.registry.add("AIDYC", project_dir)
        app.ensure_project_data("aidyc")
        db_path = app.layout.database_path
        project_data = app.layout.project_data_dir("aidyc")

    assert db_path.is_file()
    assert project_data.is_dir()
    assert isolate_aidycai_data in db_path.parents or db_path.is_relative_to(isolate_aidycai_data)

    with open_app(seed=False) as app:
        found = app.registry.find("AIDYC")
        settings = app.registry.info("AIDYC").settings
    assert found is not None
    assert found.path == project_dir.resolve()
    assert settings == {}


def test_settings_persist_and_cascade_on_remove(tmp_path):
    project_dir = tmp_path / "with-settings"
    project_dir.mkdir()
    with open_app(seed=False) as app:
        app.registry.add("Studio", project_dir, extra_excludes=["dist"])
        db_path = app.layout.database_path

    connection = connect(db_path)
    try:
        count = connection.execute("SELECT COUNT(*) AS n FROM project_settings").fetchone()["n"]
        assert count == 1
    finally:
        connection.close()

    with open_app(seed=False) as app:
        app.registry.remove("Studio")

    connection = connect(db_path)
    try:
        leftover = connection.execute("SELECT COUNT(*) AS n FROM project_settings").fetchone()["n"]
        projects = connection.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"]
    finally:
        connection.close()
    assert leftover == 0
    assert projects == 0
