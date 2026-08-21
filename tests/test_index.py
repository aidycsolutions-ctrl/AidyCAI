from pathlib import Path

from aidycai.application.bootstrap import open_app
from aidycai.infrastructure.import_graph import resolve_python_import


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sample(root: Path) -> Path:
    project = root / "billing"
    _write(
        project / "invoice.py",
        "TAX_RATE = 19\n\nclass Invoice:\n    def calculate_total(self):\n        return 1\n",
    )
    _write(
        project / "invoice_service.py",
        "from invoice import Invoice\nfrom tax import calculate_tax\n\n"
        "class InvoiceService:\n    def create_invoice(self):\n        return Invoice()\n",
    )
    _write(project / "tax.py", "def calculate_tax(amount):\n    return amount\n")
    _write(project / "notes.md", "La factura del cliente se calcula aquí.\n")
    _write(project / ".venv" / "ignored.py", "SHOULD_NOT_INDEX = True\n")
    _write(project / "__pycache__" / "invoice.cpython-312.pyc", "x")
    (project / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    _write(project / "broken.py", "def (\n")
    (project / "skipme").mkdir()
    _write(project / "skipme" / "secret.py", "SECRET = 1\n")
    return project


def test_initial_index_and_reindex_without_changes(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        first = app.index_service().index_project("Billing")
        second = app.index_service().index_project("Billing")
        stats = app.index_service().stats("Billing")

    assert first.files_created >= 5
    assert first.files_unchanged == 0
    assert first.files_code >= 3
    assert first.errors == 1
    assert second.files_unchanged == first.files_found
    assert second.files_created == 0
    assert second.files_modified == 0
    assert stats.files_indexed == first.files_found
    assert stats.symbols > 0
    assert stats.imports > 0
    assert stats.errors >= 1


def test_modified_new_and_deleted_files(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        app.index_service().index_project("Billing")
        (project_dir / "invoice.py").write_text(
            "TAX_RATE = 21\n\nclass Invoice:\n    def calculate_total(self):\n        return 2\n",
            encoding="utf-8",
        )
        (project_dir / "extra.py").write_text("def extra():\n    return 0\n", encoding="utf-8")
        changed = app.index_service().index_project("Billing")
        (project_dir / "extra.py").unlink()
        removed = app.index_service().index_project("Billing")

    assert changed.files_modified == 1
    assert changed.files_created == 1
    assert removed.files_deleted == 1


def test_rename_detected_by_hash(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        app.index_service().index_project("Billing")
        (project_dir / "tax.py").rename(project_dir / "taxes.py")
        result = app.index_service().index_project("Billing")
        hits = app.index_service().search("Billing", "calculate_tax")

    assert result.files_renamed == 1
    assert result.files_created == 0
    assert result.files_deleted == 0
    assert any(hit.rel_path == "taxes.py" for hit in hits)


def test_exclusions_and_binaries_not_treated_as_code(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        app.index_service().index_project("Billing")
        store_path = app.layout.project_index_path("billing")
        stats = app.index_service().stats("Billing")
        hits_secret = app.index_service().search("Billing", "SECRET")
        hits_ignored = app.index_service().search("Billing", "SHOULD_NOT_INDEX")

    assert store_path.is_file()
    assert stats.files_binary >= 1
    assert not any("skipme" in (hit.rel_path or "") for hit in hits_secret)
    assert hits_ignored == [] or all("venv" not in hit.rel_path for hit in hits_ignored)
    assert all("skipme" not in hit.rel_path for hit in hits_secret)


def test_syntax_error_does_not_stop_indexing(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        summary = app.index_service().index_project("Billing")
        hits = app.index_service().search("Billing", "Invoice")
        stats = app.index_service().stats("Billing")

    assert summary.errors == 1
    assert any(hit.qualified_name == "Invoice" for hit in hits if hit.kind == "symbol")
    assert stats.last_error and "broken.py" in stats.last_error


def test_import_graph_resolves_local_modules(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        app.index_service().index_project("Billing")
        store = app.index_service()
        from aidycai.infrastructure.index_store import SqliteIndexStore

        raw = SqliteIndexStore(app.layout.project_index_path("billing"), "billing", "Billing")
        try:
            edges = raw.list_edges()
        finally:
            raw.close()

    pairs = {(src, dst) for src, dst, _module in edges if dst}
    assert ("invoice_service.py", "invoice.py") in pairs
    assert ("invoice_service.py", "tax.py") in pairs
    known = {"invoice.py", "tax.py", "invoice_service.py"}
    assert resolve_python_import("invoice_service.py", "invoice", 0, known) == "invoice.py"


def test_search_fts_finds_file_content_and_symbols(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        app.index_service().index_project("Billing")
        factura = app.index_service().search("Billing", "factura")
        totals = app.index_service().search("Billing", "calculate_total")

    assert any(hit.rel_path == "notes.md" for hit in factura)
    assert any(hit.qualified_name == "Invoice.calculate_total" for hit in totals)


def test_multiple_projects_have_isolated_indexes(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    _write(one / "a.py", "class Alpha:\n    pass\n")
    _write(two / "b.py", "class Beta:\n    pass\n")
    with open_app(seed=False) as app:
        app.registry.add("One", one)
        app.registry.add("Two", two)
        summaries = app.index_service().index_all_active()
        alpha = app.index_service().search("One", "Alpha")
        beta_in_one = app.index_service().search("One", "Beta")
        beta = app.index_service().search("Two", "Beta")

    assert len(summaries) == 2
    assert any(hit.qualified_name == "Alpha" for hit in alpha)
    assert not any(hit.qualified_name == "Beta" for hit in beta_in_one)
    assert any(hit.qualified_name == "Beta" for hit in beta)


def test_index_progress_callback_reports_stages(tmp_path):
    from aidycai.application.indexer import IndexService
    from aidycai.application.registry import ProjectRegistry
    from aidycai.infrastructure.paths import DataLayout
    from aidycai.infrastructure.project_repository import SqliteProjectRepository
    from aidycai.infrastructure.database import connect, migrate
    from aidycai.infrastructure.scanner import FileSystemScanner

    project = tmp_path / "progress_project"
    project.mkdir()
    for i in range(3):
        (project / f"module_{i}.py").write_text(f"def fn_{i}():\n    return {i}\n", encoding="utf-8")

    layout = DataLayout(tmp_path / "data")
    layout.ensure()
    connection = connect(layout.database_path)
    migrate(connection)
    registry = ProjectRegistry(SqliteProjectRepository(connection), FileSystemScanner())
    added = registry.add("Progress", project)
    events = []
    try:
        service = IndexService(layout, registry, FileSystemScanner())
        summary = service.index_project(added.id, progress=lambda *event: events.append(event))
    finally:
        connection.close()

    assert summary.files_found == 3
    assert any(event[0] == "scan" for event in events)
    assert any(event[0] == "analyze" for event in events)
    assert any(event[0] == "graph" for event in events)
    assert events[-1][0] == "done"


def test_explicit_rebuild_recreates_index_from_scratch(tmp_path):
    project_dir = _sample(tmp_path)
    with open_app(seed=False) as app:
        app.registry.add("Billing", project_dir, extra_excludes=["skipme"])
        service = app.index_service()
        first = service.index_project("Billing")
        assert first.files_created >= 5

        (project_dir / "invoice.py").unlink()
        incremental = service.index_project("Billing")
        assert incremental.files_deleted == 1
        assert service.search("Billing", "Invoice")

        rebuilt = service.index_project("Billing", rebuild=True)
        stats = service.stats("Billing")
        invoice_hits = service.search("Billing", "Invoice")

    assert rebuilt.files_created == rebuilt.files_found
    assert rebuilt.files_unchanged == 0
    assert not any(hit.rel_path == "invoice.py" for hit in invoice_hits)
    assert stats.last_run_status == "ok"
