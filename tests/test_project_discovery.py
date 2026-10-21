from pathlib import Path

from typer.testing import CliRunner

from aidycai.application.bootstrap import open_app
from aidycai.application.project_discovery import default_search_root, discover_projects, looks_like_project
from aidycai.cli.main import app


runner = CliRunner()


def _project(root: Path, name: str, *markers: str) -> Path:
    path = root / name
    path.mkdir(parents=True)
    for marker in markers:
        target = path / marker
        if marker == ".git":
            target.mkdir()
            (target / "config").write_text("git\n", encoding="utf-8")
        else:
            target.write_text("x\n", encoding="utf-8")
    return path


def test_looks_like_project_detects_markers(tmp_path):
    project = _project(tmp_path, "Aidyc", ".git", "pyproject.toml")
    ok, markers = looks_like_project(project)
    assert ok is True
    assert ".git" in markers
    assert "pyproject.toml" in markers


def test_discover_projects_skips_registered_and_noise(tmp_path):
    keep = _project(tmp_path, "Aidyc", ".git")
    _project(tmp_path, "web", "package.json")
    noise = tmp_path / "node_modules"
    noise.mkdir()
    (noise / "pkg").mkdir()
    plain = tmp_path / "notas"
    plain.mkdir()
    (plain / "readme.txt").write_text("x\n", encoding="utf-8")

    with open_app(seed=False) as context:
        context.registry.add("Aidyc", keep)
        found = discover_projects(tmp_path, depth=1, registered=context.registry.list_projects())

    names = {item.name: item for item in found}
    assert set(names) == {"Aidyc", "web"}
    assert names["Aidyc"].already_registered is True
    assert names["web"].already_registered is False


def test_discover_depth_two_finds_nested(tmp_path):
    nested_root = tmp_path / "Deuna"
    nested_root.mkdir()
    _project(nested_root, "deunacolombia", "requirements.txt")
    found = discover_projects(tmp_path, depth=2, registered=[])
    assert [item.name for item in found] == ["deunacolombia"]


def test_default_search_root_prefers_existing_workspace(monkeypatch, tmp_path):
    preferred = tmp_path / "Documentos" / "Proyectos_AidyC"
    preferred.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert default_search_root() == preferred.resolve()


def test_cli_discover_and_add(tmp_path):
    _project(tmp_path, "jugoo", ".git")
    result = runner.invoke(app, ["project", "discover", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "jugoo" in result.output
    assert "nuevo" in result.output

    add = runner.invoke(app, ["project", "discover", str(tmp_path), "--add"])
    assert add.exit_code == 0, add.output
    assert "Registrado" in add.output

    listed = runner.invoke(app, ["project", "list"])
    assert listed.exit_code == 0, listed.output
    assert "jugoo" in listed.output
