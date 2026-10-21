from aidycai.application.bootstrap import open_app
from aidycai.application.defaults import DEFAULT_PROJECTS, DefaultProject
from aidycai.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_cli_add_list_info_remove(tmp_path):
    project_dir = tmp_path / "AIDYC"
    (project_dir / "src").mkdir(parents=True)
    (project_dir / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")

    added = runner.invoke(app, ["project", "add", "AIDYC", str(project_dir)])
    assert added.exit_code == 0, added.output
    assert "Registrado" in added.output

    listed = runner.invoke(app, ["project", "list"])
    assert listed.exit_code == 0, listed.output
    assert "AIDYC" in listed.output
    assert "ok" in listed.output

    info = runner.invoke(app, ["project", "info", "AIDYC"])
    assert info.exit_code == 0, info.output
    assert "AIDYC" in info.output
    assert "Archivos:" in info.output

    removed = runner.invoke(app, ["project", "remove", "AIDYC"])
    assert removed.exit_code == 0, removed.output
    assert project_dir.is_dir()
    assert (project_dir / "src" / "app.py").is_file()

    listed_after = runner.invoke(app, ["project", "list"])
    assert "No hay proyectos registrados" in listed_after.output


def test_cli_rejects_duplicate(tmp_path):
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    first = runner.invoke(app, ["project", "add", "AIDYCWeb", str(project_dir)])
    second = runner.invoke(app, ["project", "add", "AIDYCWeb", str(project_dir)])
    assert first.exit_code == 0
    assert second.exit_code == 1
    assert "Ya existe" in second.output


def test_cli_system_info(isolate_aidycai_data):
    result = runner.invoke(app, ["system", "info"])
    assert result.exit_code == 0, result.output
    collapsed = result.output.replace("\n", "")
    assert "AIDYCAI 0.1.0" in collapsed
    assert "aidycai.sqlite" in collapsed
    assert str(isolate_aidycai_data.resolve()) in collapsed


def test_seed_registers_default_projects_when_paths_exist():
    available = [spec.name for spec in DEFAULT_PROJECTS if spec.path.is_dir()]
    assert available == ["AIDYC", "AIDYCWeb", "deunacolombia"]
    with open_app(seed=True) as context:
        names = [project.name for project in context.registry.list_projects()]
    assert names == available


def test_seed_can_use_temporary_defaults(tmp_path, monkeypatch):
    one = tmp_path / "AIDYC"
    two = tmp_path / "web"
    one.mkdir()
    two.mkdir()
    monkeypatch.setattr(
        "aidycai.application.bootstrap.DEFAULT_PROJECTS",
        (
            DefaultProject(name="AIDYC", path=one),
            DefaultProject(name="AIDYCWeb", path=two),
        ),
    )
    with open_app(seed=True) as context:
        names = [project.name for project in context.registry.list_projects()]
    assert names == ["AIDYC", "AIDYCWeb"]
