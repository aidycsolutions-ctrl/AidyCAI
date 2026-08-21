from pathlib import Path

from typer.testing import CliRunner

from aidycai.cli.main import app

runner = CliRunner()


def test_cli_index_search_and_info(tmp_path):
    project = tmp_path / "shop"
    project.mkdir()
    (project / "factura.py").write_text(
        "class Factura:\n    def total(self):\n        return 0\n",
        encoding="utf-8",
    )
    added = runner.invoke(app, ["project", "add", "Shop", str(project)])
    assert added.exit_code == 0, added.output

    indexed = runner.invoke(app, ["index", "Shop"])
    assert indexed.exit_code == 0, indexed.output
    assert "Archivos de código" in indexed.output
    assert "Indexación completada" in indexed.output

    again = runner.invoke(app, ["index", "Shop"])
    assert again.exit_code == 0, again.output
    assert "Archivos sin cambios" in again.output

    info = runner.invoke(app, ["index", "info", "Shop"])
    assert info.exit_code == 0, info.output
    assert "Símbolos" in info.output
    assert "Archivos indexados" in info.output

    search = runner.invoke(app, ["search", "Shop", "Factura"])
    assert search.exit_code == 0, search.output
    assert "Factura" in search.output
