import subprocess
from pathlib import Path

from aidycai.services import python_environment
from aidycai.services.python_environment import PythonEnvironmentManager


def _fake_processes(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            env_path = Path(command[-1])
            python_path = PythonEnvironmentManager.python_path(env_path)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(python_environment.subprocess, "run", fake_run)
    return commands


def test_prepare_creates_local_environment_and_installs_requirements(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    requirements = project / "requirements.txt"
    requirements.write_text("flask>=3\n", encoding="utf-8")
    manager = PythonEnvironmentManager(data_dir=tmp_path / "local-data")
    commands = _fake_processes(monkeypatch)

    prepared = manager.prepare(project, "sample-project")

    assert prepared.path == (tmp_path / "local-data" / "environments" / "sample-project").resolve()
    assert not prepared.path.is_relative_to(project)
    assert prepared.created is True
    assert prepared.dependencies_installed is True
    assert prepared.dependency_source == "requirements.txt"
    assert commands[1][-2:] == ["-r", str(requirements)]
    assert not (project / ".venv").exists()


def test_prepare_reuses_environment_when_dependency_manifest_is_unchanged(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "requirements.txt").write_text("rich>=13\n", encoding="utf-8")
    manager = PythonEnvironmentManager(data_dir=tmp_path / "local-data")
    commands = _fake_processes(monkeypatch)

    first = manager.prepare(project, "project")
    second = manager.prepare(project, "project")

    assert first.created is True
    assert second.created is False
    assert second.dependencies_installed is False
    assert len(commands) == 2


def test_prepare_reads_pep621_dependencies_and_rebuilds_after_change(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    pyproject = project / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["typer>=0.12"]\n', encoding="utf-8")
    manager = PythonEnvironmentManager(data_dir=tmp_path / "local-data")
    commands = _fake_processes(monkeypatch)

    first = manager.prepare(project, "project")
    pyproject.write_text('[project]\ndependencies = ["typer>=0.12", "rich>=13"]\n', encoding="utf-8")
    second = manager.prepare(project, "project")

    installs = [command for command in commands if command[1:3] == ["-m", "pip"]]
    assert first.dependency_source == "pyproject.toml"
    assert second.created is True
    assert len(installs) == 2
    assert installs[0][-1] == "typer>=0.12"
    assert installs[1][-2:] == ["typer>=0.12", "rich>=13"]


def test_prepare_creates_empty_environment_without_project_manifest(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    manager = PythonEnvironmentManager(data_dir=tmp_path / "local-data")
    commands = _fake_processes(monkeypatch)

    prepared = manager.prepare(project, "project")

    assert prepared.created is True
    assert prepared.dependencies_installed is False
    assert prepared.dependency_source is None
    assert len(commands) == 1
