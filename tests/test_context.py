from dataclasses import asdict
from pathlib import Path

from aidycai.application.bootstrap import open_app
from aidycai.application.diagnostics import render_diagnosis
from aidycai.application.task_analysis import analyze_task
from aidycai.domain.context_models import ContextBundle, ContextConfig, EvidenceRecord, ROLE_PRIMARY, ROLE_SECONDARY
from typer.testing import CliRunner

from aidycai.cli.main import app

runner = CliRunner()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _billing(root: Path) -> Path:
    project = root / "billing"
    _write(
        project / "invoice.py",
        "TAX_RATE = 19\n\nclass Invoice:\n    def calculate_total(self, amount):\n        return amount\n",
    )
    _write(
        project / "invoice_service.py",
        "from invoice import Invoice\nfrom tax import calculate_tax\n\n"
        "class InvoiceService:\n    def create_invoice(self):\n        return Invoice()\n",
    )
    _write(
        project / "tax.py",
        "class TaxCalculator:\n    def calculate_tax(self, amount, rate):\n        return amount * rate / 100\n",
    )
    _write(project / "notes.md", "comentario suelto sobre factura en prosa\n")
    _write(project / "unrelated.py", "def ping():\n    return 'pong'\n")
    return project


def _chain(root: Path) -> Path:
    project = root / "chain"
    _write(project / "a.py", "from b import B\nclass AlphaRoot:\n    pass\n")
    _write(project / "b.py", "from c import C\nclass B:\n    pass\n")
    _write(project / "c.py", "from d import D\nclass C:\n    pass\n")
    _write(project / "d.py", "class D:\n    pass\n")
    return project


def test_extracts_terms_and_related_glossary():
    analysis = analyze_task("¿Dónde se calcula el IVA de una factura?")
    lowered = {item.lower() for item in analysis.keywords + analysis.related_terms}
    assert "iva" in lowered or "IVA" in analysis.keywords
    assert any(item.lower() == "factura" for item in analysis.keywords)
    assert "calculate_tax" in analysis.related_terms or "tax" in {t.lower() for t in analysis.related_terms}
    assert "Invoice" in analysis.symbol_candidates or "FacturaPDF" in analysis.symbol_candidates


def test_exact_symbol_outranks_partial_prose(tmp_path):
    project_dir = _billing(tmp_path)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Billing", project_dir)
        app_ctx.index_service().index_project("Billing")
        bundle = app_ctx.context_engine().build("Billing", "Invoice.calculate_total")
    paths = [item.path for item in bundle.files]
    assert paths[0] == "invoice.py"
    invoice = bundle.files[0]
    assert any("exact" in reason or "qualified" in reason for reason in invoice.reasons)
    assert "unrelated.py" not in paths


def test_partial_filename_and_graph_expansion(tmp_path):
    project_dir = _billing(tmp_path)
    config = ContextConfig(max_files=6, max_depth=2, max_primary_files=2)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Billing", project_dir)
        app_ctx.index_service().index_project("Billing")
        engine = app_ctx.context_engine()
        engine.config = config
        bundle = engine.build("Billing", "InvoiceService")
    paths = {item.path for item in bundle.files}
    assert "invoice_service.py" in paths
    assert "invoice.py" in paths
    reasons = {item.path: item.reasons for item in bundle.files}
    assert any("import" in " ".join(reasons["invoice.py"]) or "dependency" in " ".join(reasons["invoice.py"]) for _ in [0])
    roles = {item.path: item.role for item in bundle.files}
    assert roles["invoice_service.py"] == ROLE_PRIMARY
    assert roles.get("invoice.py") in {ROLE_SECONDARY, ROLE_PRIMARY}


def test_graph_depth_limit(tmp_path):
    project_dir = _chain(tmp_path)
    config = ContextConfig(max_files=8, max_depth=2, incoming_depth=0, max_primary_files=1)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Chain", project_dir)
        app_ctx.index_service().index_project("Chain")
        engine = app_ctx.context_engine()
        engine.config = config
        bundle = engine.build("Chain", "AlphaRoot")
    paths = {item.path for item in bundle.files}
    assert "a.py" in paths
    assert "d.py" not in paths


def test_fragments_primary_secondary_and_reasons(tmp_path):
    project_dir = _billing(tmp_path)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Billing", project_dir)
        app_ctx.index_service().index_project("Billing")
        bundle = app_ctx.context_engine().build("Billing", "calculate_total")
    primary = next(item for item in bundle.files if item.role == ROLE_PRIMARY)
    assert primary.fragments
    assert not primary.fragments[0].compressed
    assert primary.fragments[0].line_start >= 1
    assert "calculate_total" in primary.fragments[0].content
    assert all(item.reasons for item in bundle.files)
    assert any(item.role in {ROLE_SECONDARY, ROLE_PRIMARY} for item in bundle.files)
    assert any(symbol.qualified_name.endswith("calculate_total") for symbol in bundle.symbols)


def test_json_text_metrics_and_reduction(tmp_path):
    project_dir = _billing(tmp_path)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Billing", project_dir)
        app_ctx.index_service().index_project("Billing")
        bundle = app_ctx.context_engine().build("Billing", "¿Dónde se calcula el total de una factura?")
    payload = bundle.to_dict()
    text = bundle.to_text()
    json_text = bundle.to_json()
    assert payload["project_name"] == "Billing"
    assert payload["task"]
    assert "PROJECT: Billing" in text
    assert "TASK:" in text
    assert "calculate_total" in json_text or "Invoice" in json_text
    stats = bundle.statistics
    assert stats.candidate_files >= 1
    assert stats.selected_files >= 1
    assert stats.selected_lines >= 1
    assert stats.available_chars > stats.selected_chars
    assert 0 < stats.reduction_ratio < 1
    assert stats.estimated_tokens >= 1
    assert stats.total_seconds >= 0


def test_multiple_projects_context_is_isolated(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    _write(one / "alpha.py", "class Alpha:\n    def run(self):\n        return 1\n")
    _write(two / "beta.py", "class Beta:\n    def run(self):\n        return 2\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("One", one)
        app_ctx.registry.add("Two", two)
        app_ctx.index_service().index_project("One")
        app_ctx.index_service().index_project("Two")
        left = app_ctx.context_engine().build("One", "Alpha")
        right = app_ctx.context_engine().build("Two", "Beta")
    assert all(item.path != "beta.py" for item in left.files)
    assert all(item.path != "alpha.py" for item in right.files)



def test_function_call_graph_promotes_called_file(tmp_path):
    project = tmp_path / "calls"
    _write(
        project / "retiros.py",
        "def imprimir_retiro(valor):\n    return str(valor)\n\n"
        "def guardar_retiro(valor):\n    return imprimir_retiro(valor)\n",
    )
    _write(
        project / "impresora.py",
        "def imprimir_ticket(valor):\n    return str(valor)\n",
    )
    # A direct call to a uniquely named helper must be visible to the context.
    _write(
        project / "flujo.py",
        "from impresora import imprimir_ticket\n\n"
        "def procesar_retiro(valor):\n    return imprimir_ticket(valor)\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Calls", project)
        app_ctx.index_service().index_project("Calls")
        bundle = app_ctx.context_engine().build("Calls", "procesar_retiro")
    paths = [item.path for item in bundle.files]
    assert "flujo.py" in paths
    assert "impresora.py" in paths
    reasons = " ".join(next(item.reasons for item in bundle.files if item.path == "impresora.py"))
    assert "function call" in reasons


def test_explicit_filename_outranks_extension_token_and_related_basename(tmp_path):
    project = tmp_path / "web"
    _write(project / "templates" / "sales.html", "<html><link rel=\"stylesheet\" href=\"/static/css/sales.css\"></html>\n")
    _write(project / "templates" / "modules" / "sales.html", "<div>sales</div>\n")
    _write(project / "static" / "css" / "sales.css", ".sales { display: block; }\n")
    _write(project / "venv" / "Lib" / "site-packages" / "weasyprint" / "html.py", "HTML5_UA = {}\n")
    _write(project / "vendor" / "html.py", "HTML5_UA = {}\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Web", project)
        app_ctx.index_service().index_project("Web")
        bundle = app_ctx.context_engine().build("Web", "donde estan los estilos de sales.html?")

        paths = [item.path for item in bundle.files]
        assert paths[0] == "templates/sales.html"
        assert "static/css/sales.css" in paths
        assert "vendor/html.py" not in paths
        assert "venv/Lib/site-packages/weasyprint/html.py" not in paths
    assert not any(path.startswith("venv/") for path in paths)
    sales_css = next(item for item in bundle.files if item.path == "static/css/sales.css")
    assert any("basename" in reason for reason in sales_css.reasons)

def test_cli_context_and_output(tmp_path):
    project = tmp_path / "shop"
    _write(project / "factura.py", "class Factura:\n    def total(self):\n        return 0\n")
    assert runner.invoke(app, ["project", "add", "Shop", str(project)]).exit_code == 0
    assert runner.invoke(app, ["index", "Shop"]).exit_code == 0
    result = runner.invoke(app, ["context", "Shop", "Factura.total"])
    assert result.exit_code == 0, result.output
    assert "Task:" in result.output
    assert "Reduction:" in result.output
    json_path = tmp_path / "context.json"
    txt_path = tmp_path / "context.txt"
    dumped = runner.invoke(app, ["context", "Shop", "Factura", "--output", str(json_path)])
    assert dumped.exit_code == 0, dumped.output
    assert json_path.is_file()
    texted = runner.invoke(app, ["context", "Shop", "Factura", "--output", str(txt_path)])
    assert texted.exit_code == 0
    assert "PROJECT:" in txt_path.read_text(encoding="utf-8")


def test_cli_ask_interactive(tmp_path):
    project = tmp_path / "ask_shop"
    _write(project / "factura.py", "class Factura:\n    def total(self):\n        return 0\n")
    assert runner.invoke(app, ["project", "add", "AskShop", str(project)]).exit_code == 0
    assert runner.invoke(app, ["index", "AskShop"]).exit_code == 0
    result = runner.invoke(
        app,
        ["ask", "AskShop"],
        input="¿Dónde se calcula el total?\nexportar\nsalir\n",
    )
    assert result.exit_code == 0, result.output
    assert "Encontré" in result.output
    assert "Archivos principales:" in result.output
    assert "AIDYCAI todavía no responde" in result.output


def test_strict_flow_follows_only_outgoing_calls_to_terminal(tmp_path):
    project = tmp_path / "flow_strict"
    _write(
        project / "retirarefectivo.py",
        "def imprimir_ultimos_retiros():\n"
        "    return imprimir_ticket_retiro()\n\n"
        "def imprimir_ticket_retiro():\n"
        "    return guardar_ticket_txt()\n\n"
        "def guardar_ticket_txt():\n"
        "    return enviar_a_impresora()\n\n"
        "def flujo_irrelevante():\n"
        "    return notificacion()\n",
    )
    _write(
        project / "imprimir.py",
        "def enviar_a_impresora():\n"
        "    return terminal_impresion()\n\n"
        "def terminal_impresion():\n"
        "    return win32print.WritePrinter(b'raw')\n",
    )
    _write(project / "Retiros.py", "def retiro_no_relacionado():\n    return 1\n")
    _write(project / "ventas.py", "def venta():\n    return 2\n")
    _write(project / "notacredito.py", "def nota():\n    return 3\n")
    _write(project / "notificaciones.py", "def notificar():\n    return 4\n")

    query = (
        "Analiza EXCLUSIVAMENTE el flujo de impresión de retiros. "
        "Necesito el código de retirarefectivo.imprimir_ultimos_retiros, "
        "imprimir_ticket_retiro y guardar_ticket_txt. "
        "Sigue esa llamada hasta la función que finalmente ejecuta win32print. "
        "Ignora Retiros.py, notacredito, ventas, notificaciones y cualquier otro flujo."
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowStrict", project)
        app_ctx.index_service().index_project("FlowStrict")
        bundle = app_ctx.context_engine().build("FlowStrict", query)

    paths = [item.path for item in bundle.files]
    assert paths == ["retirarefectivo.py", "imprimir.py"]
    assert not any(path in paths for path in {"Retiros.py", "ventas.py", "notacredito.py", "notificaciones.py"})
    names = {symbol.qualified_name for symbol in bundle.symbols}
    assert {"imprimir_ultimos_retiros", "imprimir_ticket_retiro", "guardar_ticket_txt", "enviar_a_impresora", "terminal_impresion"} <= names
    assert "flujo_irrelevante" not in names
    assert bundle.metadata["flow_only"] is True
    assert bundle.metadata["flow_requested"] is True


def test_strict_flow_keeps_explicit_required_symbol_when_not_reachable(tmp_path):
    project = tmp_path / "flow_required_context"
    _write(
        project / "retirarefectivo.py",
        "def imprimir_ultimos_retiros():\n"
        "    return imprimir_ticket_retiro()\n\n"
        "def imprimir_ticket_retiro():\n"
        "    return 1\n\n"
        "def guardar_ticket_txt():\n"
        "    return 2\n",
    )
    _write(project / "Retiros.py", "def retiro_no_relacionado():\n    return 1\n")
    query = (
        "EXCLUSIVAMENTE seguir el flujo de retirarefectivo.imprimir_ultimos_retiros. "
        "Necesito el código de imprimir_ticket_retiro y guardar_ticket_txt. "
        "Ignora Retiros.py."
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowRequiredContext", project)
        app_ctx.index_service().index_project("FlowRequiredContext")
        bundle = app_ctx.context_engine().build("FlowRequiredContext", query)

    names = {symbol.qualified_name for symbol in bundle.symbols}
    assert {"imprimir_ultimos_retiros", "imprimir_ticket_retiro", "guardar_ticket_txt"} <= names
    assert bundle.metadata["flow_path"] == ["imprimir_ultimos_retiros", "imprimir_ticket_retiro"]
    assert bundle.metadata["flow_required_symbols"] == ["guardar_ticket_txt"]
    assert any("guardar_ticket_txt" in item for item in bundle.metadata["flow_unresolved"])
    assert [item.path for item in bundle.files] == ["retirarefectivo.py"]


def test_strict_flow_does_not_fill_max_files_with_unrelated_candidates(tmp_path):
    project = tmp_path / "flow_minimal"
    _write(project / "a.py", "def start():\n    return finish()\n\ndef finish():\n    return 1\n")
    for name in ("b.py", "c.py", "d.py", "e.py"):
        _write(project / name, f"def unrelated():\n    return '{name}'\n")
    query = "EXCLUSIVAMENTE seguir el flujo de a.start hasta finish; ignorar b.py, c.py, d.py, e.py."
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowMinimal", project)
        app_ctx.index_service().index_project("FlowMinimal")
        bundle = app_ctx.context_engine().build("FlowMinimal", query)
    assert [item.path for item in bundle.files] == ["a.py"]
    assert {symbol.qualified_name for symbol in bundle.symbols} == {"start", "finish"}


def test_task_analysis_extracts_flow_constraints():
    query = (
        "EXCLUSIVAMENTE seguir el flujo de A.start hasta la función terminal. "
        "Ignora Retiros.py, notacredito, ventas y notificaciones."
    )
    analysis = analyze_task(query)
    assert analysis.flow_requested is True
    assert analysis.flow_only is True
    assert analysis.follow_calls is True
    assert analysis.flow_start_candidates == ["A.start"]
    assert "Retiros.py" in analysis.exclude_terms
    assert "notacredito" in analysis.exclude_terms
    assert "ventas" in analysis.exclude_terms
    assert "notificaciones" in analysis.exclude_terms
    assert analysis.terminal_requested is True


def test_strict_flow_is_inferred_from_exclusive_explicit_symbols_and_terminal(tmp_path):
    project = tmp_path / "flow_inferred"
    _write(project / "retirarefectivo.py", "def imprimir_ultimos_retiros():\n    return imprimir_ticket_retiro()\n\ndef imprimir_ticket_retiro():\n    return guardar_ticket_txt()\n\ndef guardar_ticket_txt():\n    return enviar()\n")
    _write(project / "imprimir.py", "def enviar():\n    return win32print.WritePrinter(b'x')\n")
    _write(project / "Retiros.py", "def imprimir_ultimos_retiros():\n    return 999\n")
    query = "EXCLUSIVAMENTE IGNORA Retiros.py imprimir_ultimos_retiros imprimir_ticket_retiro guardar_ticket_txt imprimir.py win32print"
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowInferred", project)
        app_ctx.index_service().index_project("FlowInferred")
        bundle = app_ctx.context_engine().build("FlowInferred", query)
    assert bundle.analysis.flow_only is True
    assert bundle.analysis.flow_requested is True
    assert [item.path for item in bundle.files] == ["retirarefectivo.py", "imprimir.py"]
    assert "Retiros.py" not in {item.path for item in bundle.files}
    assert bundle.metadata["terminal_edges"]


def test_exclusion_does_not_treat_prefix_as_same_module(tmp_path):
    project = tmp_path / "exclude_exact"
    _write(project / "retirosefectivo.py", "def start():\n    return finish()\n\ndef finish():\n    return 1\n")
    _write(project / "Retiros.py", "def start():\n    return 999\n")
    engine_project = project
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("ExcludeExact", engine_project)
        app_ctx.index_service().index_project("ExcludeExact")
        bundle = app_ctx.context_engine().build(
            "ExcludeExact",
            "EXCLUSIVAMENTE seguir el flujo de retirosefectivo.start hasta finish; IGNORA Retiros.py.",
        )
    assert [item.path for item in bundle.files] == ["retirosefectivo.py"]
    assert "Retiros.py" not in {item.path for item in bundle.files}


def test_exclusion_bare_module_name_is_exact_stem(tmp_path):
    project = tmp_path / "exclude_module"
    _write(project / "ventas.py", "def venta():\n    return 1\n")
    _write(project / "ventas_pendientes.py", "def pendiente():\n    return 2\n")
    _write(project / "retirosefectivo.py", "def start():\n    return 1\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("ExcludeModule", project)
        app_ctx.index_service().index_project("ExcludeModule")
        bundle = app_ctx.context_engine().build(
            "ExcludeModule", "EXCLUSIVAMENTE seguir el flujo de retirosefectivo.start; IGNORA ventas."
        )
    paths = {item.path for item in bundle.files}
    assert "ventas.py" not in paths
    assert "ventas_pendientes.py" not in paths or "ventas_pendientes.py" not in bundle.analysis.exclude_terms
    assert "retirosefectivo.py" in paths


def test_flow_query_treats_list_identifier_as_context_not_target():
    analysis = analyze_task(
        "Analiza EXCLUSIVAMENTE el flujo. Necesito el código completo de "
        "retirarefectivo.imprimir_ultimos_retiros, imprimir_ticket_retiro y guardar_ticket_txt, "
        "incluyendo cómo se construye lista_retiros y sigue hasta win32print."
    )
    assert analysis.flow_start_candidates == ["retirarefectivo.imprimir_ultimos_retiros"]
    assert analysis.flow_target_candidates == ["imprimir_ticket_retiro", "guardar_ticket_txt"]
    assert "lista_retiros" not in analysis.flow_target_candidates


def test_strict_flow_resolves_import_alias_into_imprimir_module(tmp_path):
    project = tmp_path / "flow_import_alias"
    _write(
        project / "retirarefectivo.py",
        "import imprimir as printer\n\n"
        "def imprimir_ultimos_retiros():\n"
        "    return imprimir_ticket_retiro()\n\n"
        "def imprimir_ticket_retiro():\n"
        "    return printer.enviar_ticket()\n\n"
        "def guardar_ticket_txt():\n"
        "    return 1\n",
    )
    _write(
        project / "imprimir.py",
        "def enviar_ticket():\n"
        "    return terminal_impresion()\n\n"
        "def terminal_impresion():\n"
        "    return win32print.WritePrinter(b'raw')\n",
    )
    query = (
        "EXCLUSIVAMENTE seguir el flujo de retirarefectivo.imprimir_ultimos_retiros. "
        "Necesito imprimir_ticket_retiro y guardar_ticket_txt. "
        "En imprimir.py sigue hasta win32print."
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowImportAlias", project)
        app_ctx.index_service().index_project("FlowImportAlias")
        bundle = app_ctx.context_engine().build("FlowImportAlias", query)

    paths = [item.path for item in bundle.files]
    assert paths == ["retirarefectivo.py", "imprimir.py"]
    names = {symbol.qualified_name for symbol in bundle.symbols}
    assert {"imprimir_ultimos_retiros", "imprimir_ticket_retiro", "guardar_ticket_txt", "enviar_ticket", "terminal_impresion"} <= names
    assert bundle.metadata["terminal_edges"]


def test_terminal_is_followed_even_when_required_symbol_is_not_reachable(tmp_path):
    project = tmp_path / "flow_terminal_after_unreachable_requirement"
    _write(
        project / "retirarefectivo.py",
        "import imprimir\n\n"
        "def imprimir_ultimos_retiros():\n"
        "    return imprimir_ticket_retiro()\n\n"
        "def imprimir_ticket_retiro():\n"
        "    return imprimir.enviar_ticket()\n\n"
        "def guardar_ticket_txt():\n"
        "    return 2\n",
    )
    _write(
        project / "imprimir.py",
        "def enviar_ticket():\n"
        "    return terminal_impresion()\n\n"
        "def terminal_impresion():\n"
        "    return win32print.WritePrinter(b'raw')\n",
    )
    query = (
        "EXCLUSIVAMENTE seguir el flujo de retirarefectivo.imprimir_ultimos_retiros. "
        "Necesito imprimir_ticket_retiro y guardar_ticket_txt. "
        "Sigue hasta win32print."
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowTerminalUnresolved", project)
        app_ctx.index_service().index_project("FlowTerminalUnresolved")
        bundle = app_ctx.context_engine().build("FlowTerminalUnresolved", query)

    names = {symbol.qualified_name for symbol in bundle.symbols}
    assert {"imprimir_ticket_retiro", "guardar_ticket_txt", "enviar_ticket", "terminal_impresion"} <= names
    assert bundle.metadata["terminal_edges"]
    assert any("guardar_ticket_txt" in item for item in bundle.metadata["flow_unresolved"])


def test_terminal_does_not_stop_at_openprinter_and_follows_to_writeprinter(tmp_path):
    project = tmp_path / "flow_printer_lifecycle"
    _write(
        project / "retirarefectivo.py",
        "import imprimir\n\n"
        "def imprimir_ultimos_retiros():\n"
        "    return imprimir_ticket_retiro()\n\n"
        "def imprimir_ticket_retiro():\n"
        "    return imprimir.enviar_ticket()\n\n"
        "def guardar_ticket_txt():\n"
        "    return 2\n",
    )
    _write(
        project / "imprimir.py",
        "def enviar_ticket():\n"
        "    return abrir_impresora()\n\n"
        "def abrir_impresora():\n"
        "    return OpenPrinter()\n\n"
        "def OpenPrinter():\n"
        "    return escribir_bytes()\n\n"
        "def escribir_bytes():\n"
        "    return win32print.WritePrinter(b'raw')\n",
    )
    query = (
        "EXCLUSIVAMENTE seguir el flujo de retirarefectivo.imprimir_ultimos_retiros. "
        "Necesito imprimir_ticket_retiro y guardar_ticket_txt. "
        "En imprimir.py sigue hasta win32print."
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowPrinterLifecycle", project)
        app_ctx.index_service().index_project("FlowPrinterLifecycle")
        bundle = app_ctx.context_engine().build("FlowPrinterLifecycle", query)

    path = bundle.metadata["flow_path"]
    assert path[:2] == ["imprimir_ultimos_retiros", "imprimir_ticket_retiro"]
    assert "enviar_ticket" in path
    assert "abrir_impresora" in path
    assert "OpenPrinter" in path
    assert "escribir_bytes" in path
    assert bundle.metadata["terminal_edges"]
    assert bundle.metadata["terminal_edges"][0][1].lower().endswith("writeprinter")


def test_strict_flow_does_not_treat_openprinter_as_terminal(tmp_path):
    project = tmp_path / "flow_openprinter_only"
    _write(project / "a.py", "def start():\n    return OpenPrinter()\n\ndef OpenPrinter():\n    return finish()\n\ndef finish():\n    return win32print.WritePrinter(b'x')\n")
    query = "EXCLUSIVAMENTE seguir el flujo de a.start hasta win32print."
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowOpenPrinterOnly", project)
        app_ctx.index_service().index_project("FlowOpenPrinterOnly")
        bundle = app_ctx.context_engine().build("FlowOpenPrinterOnly", query)
    assert bundle.metadata["flow_path"] == ["start", "OpenPrinter", "finish"]
    assert bundle.metadata["terminal_edges"] == [["finish", "win32print.WritePrinter"]]


def test_open_behavior_question_auto_directs_print_flow(tmp_path):
    project = tmp_path / "auto_print"
    _write(
        project / "retirosefectivo.py",
        "def imprimir_ultimos_retiros():\n"
        "    return imprimir_ticket_retiro()\n\n"
        "def imprimir_ticket_retiro():\n"
        "    return enviar_ticket()\n",
    )
    _write(
        project / "imprimir.py",
        "def enviar_ticket():\n"
        "    return win32print.WritePrinter(b'raw')\n",
    )
    _write(project / "Retiros.py", "def imprimir_otra_cosa():\n    return 1\n")

    query = "¿Por qué los retiros históricos no se imprimen?"
    analysis = analyze_task(query)
    assert analysis.auto_flow is True
    assert analysis.flow_requested is True
    assert analysis.follow_calls is True
    assert "print" in analysis.action_terms
    assert analysis.terminal_requested is True

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("AutoPrint", project)
        app_ctx.index_service().index_project("AutoPrint")
        bundle = app_ctx.context_engine().build("AutoPrint", query)

    assert bundle.metadata["auto_flow"] is True
    assert bundle.metadata["flow_path"]
    assert bundle.metadata["terminal_edges"]
    assert bundle.metadata["flow_start_candidates"]
    assert "retirosefectivo.py" in {item.path for item in bundle.files}
    assert "imprimir.py" in {item.path for item in bundle.files}


def test_open_save_question_auto_directs_to_save_symbol(tmp_path):
    project = tmp_path / "retiros"
    _write(
        project / "retiresefectivo.py",
        "def guardar_backup_general(data):\n    return _write_json_file(data)\n\n"
        "def guardar_backup_retiro(retiro):\n    return _write_json_file(retiro)\n\n"
        "def _write_json_file(data):\n    return open('retiros.json', 'w')\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("Retiros", project)
        app_ctx.index_service().index_project("Retiros")
        bundle = app_ctx.context_engine().build("Retiros", "¿Dónde se guardan los retiros históricos?")
    assert bundle.analysis.auto_flow
    assert "save" in bundle.analysis.action_terms
    assert bundle.analysis.flow_start_candidates
    assert any("guardar_backup_retiro" in item for item in bundle.metadata.get("flow_path", []))


def test_open_send_question_auto_directs_and_follows_calls(tmp_path):
    project = tmp_path / "retiros"
    _write(
        project / "retiresefectivo.py",
        "def enviar_efectivo_consignado(retiro):\n    return enviar_al_servidor(retiro)\n\n"
        "def enviar_al_servidor(data):\n    return requests.post('/retiros', json=data)\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("RetirosSend", project)
        app_ctx.index_service().index_project("RetirosSend")
        bundle = app_ctx.context_engine().build("RetirosSend", "¿Por qué no se envían los retiros al servidor?")
    assert bundle.analysis.auto_flow
    assert "send" in bundle.analysis.action_terms
    assert bundle.metadata.get("flow_path")
    assert any("enviar_efectivo_consignado" in item for item in bundle.metadata["flow_path"])


def test_open_show_question_does_not_use_unrelated_download_flow(tmp_path):
    project = tmp_path / "retiros"
    _write(
        project / "retiresefectivo.py",
        "def obtener_retiros_historicos():\n    return consultar_retiros()\n\n"
        "def consultar_retiros():\n    return []\n",
    )
    _write(project / "general.py", "def descargar_data():\n    return descargar_tablas_especificas()\n\ndef descargar_tablas_especificas():\n    return []\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("RetirosShow", project)
        app_ctx.index_service().index_project("RetirosShow")
        bundle = app_ctx.context_engine().build("RetirosShow", "¿Por qué no aparecen los retiros históricos?")
    assert bundle.analysis.auto_flow
    assert "show" in bundle.analysis.action_terms
    assert bundle.metadata.get("flow_path")
    assert any("obtener_retiros_historicos" in item for item in bundle.metadata["flow_path"])
    assert not any("descargar_data" in item for item in bundle.metadata["flow_path"])



def test_auto_send_prefers_requested_object_over_destination_helper(tmp_path):
    project = tmp_path / "send_object_priority"
    _write(
        project / "EnviarCompras.py",
        "def enviar_compras():\n    return 1\n",
    )
    _write(
        project / "EnviarNotas.py",
        "def enviar_notas():\n    return 1\n",
    )
    _write(
        project / "retirosefectivo.py",
        "def enviar_efectivo_consignado(retiro):\n    return enviar_al_servidor(retiro)\n\n"
        "def enviar_al_servidor(data):\n    return requests.post('/retiros', json=data)\n",
    )
    query = "¿Por qué no se envían los retiros al servidor?"
    analysis = analyze_task(query)
    assert analysis.subject_terms[:2] == ["retiros", "retiro"]
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("SendObjectPriority", project)
        app_ctx.index_service().index_project("SendObjectPriority")
        bundle = app_ctx.context_engine().build("SendObjectPriority", query)
    assert bundle.metadata["flow_start_candidates"]
    assert any("enviar_efectivo_consignado" in item for item in bundle.metadata["flow_path"])
    assert not bundle.metadata["flow_path"][0].endswith("enviar_al_servidor")
    assert bundle.files[0].path == "retirosefectivo.py"


def test_auto_save_subject_excludes_destination_terms(tmp_path):
    analysis = analyze_task("¿Dónde se guardan los retiros históricos en el servidor?")
    assert "retiros" in analysis.subject_terms
    assert "servidor" not in analysis.subject_terms


def test_ai_handoff_is_structured_and_provider_neutral(tmp_path):
    from aidycai.application.ai_handoff import build_ai_handoff

    project = tmp_path / "shop"
    _write(project / "sales.py", "def print_sale():\n    return 'ok'\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("ShopAI", project)
        app_ctx.index_service().index_project("ShopAI")
        bundle = app_ctx.context_engine().build("ShopAI", "¿Dónde se imprime una venta?")
    handoff = build_ai_handoff(bundle)
    payload = handoff.to_dict()
    assert payload["protocol"] == "aidycai-ai-handoff-v1"
    assert payload["project"] == {"id": bundle.project_id, "name": "ShopAI"}
    assert payload["task"] == bundle.task
    assert payload["strategy"] == bundle.analysis.research_strategy
    assert payload["intent"] == asdict(bundle.analysis)
    assert payload["intent"]["flow_spec"] == bundle.analysis.flow_spec.__dict__
    assert payload["selected_files"] == [asdict(item) for item in bundle.files]
    assert payload["selected_symbols"] == [asdict(item) for item in bundle.symbols]
    assert payload["relationships"] == [asdict(item) for item in bundle.relations]
    assert payload["statistics"] == bundle.statistics.__dict__
    assert payload["limitations"] == bundle.limitations
    assert payload["confidence"] == bundle.analysis.intent_confidence


def test_directed_flow_resolves_self_method_without_global_name_guess(tmp_path):
    project = tmp_path / "flow_self_method"
    _write(
        project / "retirosefectivo.py",
        "class RetiroService:\n"
        "    def enviar_retiro_servidor(self):\n"
        "        return self.preparar_retiro()\n\n"
        "    def preparar_retiro(self):\n"
        "        return requests.post('https://example.test')\n\n"
        "class OtroService:\n"
        "    def preparar_retiro(self):\n"
        "        return 2\n",
    )
    query = "¿Por qué no se envían los retiros?"
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowSelfMethod", project)
        app_ctx.index_service().index_project("FlowSelfMethod")
        bundle = app_ctx.context_engine().build("FlowSelfMethod", query)

    assert bundle.metadata["flow_path"] == [
        "RetiroService.enviar_retiro_servidor",
        "RetiroService.preparar_retiro",
    ]
    assert bundle.metadata["terminal_edges"]
    assert bundle.metadata["terminal_edges"][0][1] == "requests.post"


def test_directed_flow_reports_unresolved_outgoing_call_without_inventing_edge(tmp_path):
    project = tmp_path / "flow_unresolved_call"
    _write(
        project / "retirosefectivo.py",
        "def enviar_retiro_servidor():\n"
        "    return helper_externo()\n",
    )
    query = "¿Por qué no se envían los retiros?"
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FlowUnresolvedCall", project)
        app_ctx.index_service().index_project("FlowUnresolvedCall")
        bundle = app_ctx.context_engine().build("FlowUnresolvedCall", query)

    assert bundle.metadata["flow_path"] == ["enviar_retiro_servidor"]
    assert any("helper_externo" in item and "no resuelta" in item for item in bundle.metadata["flow_unresolved"])


def test_research_intent_frontend_responsive_does_not_auto_direct_backend_flow(tmp_path):
    project = tmp_path / "frontend_responsive"
    _write(
        project / "templates" / "sales.html",
        '{% extends "layout.html" %}\n<div class="sales-list">ventas</div>\n',
    )
    _write(
        project / "templates" / "modules" / "sales.html",
        '<div class="sales-list">ventas</div>\n',
    )
    _write(
        project / "templates" / "layout.html",
        '<html><body>{% block content %}{% endblock %}</body></html>\n',
    )
    _write(
        project / "static" / "css" / "sales.css",
        '@media (max-width: 700px) { .sales-list { overflow: auto; height: 100vh; } }\n',
    )
    _write(
        project / "static" / "js" / "sales.js",
        "function resizeSales() { document.querySelector('.sales-list').style.height = '100vh'; }\n",
    )
    _write(project / "blueprints" / "ventas.py", "def obtener_usuariosventas():\n    return []\n")

    query = (
        "¿por qué sales.html tiene los estilos raros para mostrar las ventas "
        "cuando se está en móvil? queda como pegada la parte de arriba y el "
        "scroll no deja ver bien las ventas"
    )
    analysis = analyze_task(query)
    assert analysis.research_intent == "FRONTEND_RESPONSIVE"
    assert analysis.research_strategy == "FRONTEND_RESPONSIVE"
    assert analysis.auto_flow is False
    assert analysis.flow_requested is False

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FrontendResponsive", project)
        app_ctx.index_service().index_project("FrontendResponsive")
        bundle = app_ctx.context_engine().build("FrontendResponsive", query)

    paths = [item.path for item in bundle.files]
    assert "templates/sales.html" in paths
    assert "static/css/sales.css" in paths
    assert "templates/modules/sales.html" in paths
    assert "blueprints/ventas.py" not in [item.path for item in bundle.files[:3]]
    assert bundle.metadata["research_intent"] == "FRONTEND_RESPONSIVE"


def test_research_intent_file_location_is_shallow(tmp_path):
    project = tmp_path / "frontend_location"
    _write(project / "templates" / "sales.html", "<link rel='stylesheet' href='/static/css/sales.css'>\n")
    _write(project / "static" / "css" / "sales.css", ".sales { color: red; }\n")
    _write(project / "blueprints" / "ventas.py", "def obtener_usuariosventas():\n    return []\n")
    analysis = analyze_task("¿Dónde están los estilos de sales.html?")
    assert analysis.research_intent == "FILE_LOCATION"
    assert analysis.research_strategy == "DIRECT_FILE_LOOKUP"

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FrontendLocation", project)
        app_ctx.index_service().index_project("FrontendLocation")
        bundle = app_ctx.context_engine().build("FrontendLocation", "¿Dónde están los estilos de sales.html?")
    paths = [item.path for item in bundle.files]
    assert paths[:2] == ["templates/sales.html", "static/css/sales.css"]


def test_research_intent_backend_send_preserves_flow(tmp_path):
    project = tmp_path / "send"
    _write(
        project / "retiros.py",
        "def enviar_retiro_servidor(retiro):\n    return requests.post('/retiros', json=retiro)\n"
    )
    analysis = analyze_task("¿Por qué no se envían los retiros?")
    assert analysis.research_intent == "BACKEND_FLOW"
    assert analysis.auto_flow is True

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("IntentSend", project)
        app_ctx.index_service().index_project("IntentSend")
        bundle = app_ctx.context_engine().build("IntentSend", "¿Por qué no se envían los retiros?")
    assert bundle.metadata["research_intent"] == "BACKEND_FLOW"
    assert any("enviar_retiro_servidor" in item for item in bundle.metadata["flow_path"])
    assert "retiros.py" in [item.path for item in bundle.files]


def test_research_intent_persistence_and_data_flow(tmp_path):
    project = tmp_path / "persistence"
    _write(
        project / "retiros.py",
        "def guardar_backup_retiro(retiro):\n    return guardar_backup_general(retiro)\n\n"
        "def guardar_backup_general(data):\n    return open('retiros.json', 'w').write(str(data))\n",
    )
    analysis = analyze_task("¿Dónde se guardan los retiros históricos?")
    assert analysis.research_intent == "PERSISTENCE"

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("IntentPersistence", project)
        app_ctx.index_service().index_project("IntentPersistence")
        bundle = app_ctx.context_engine().build("IntentPersistence", "¿Dónde se guardan los retiros históricos?")
    assert bundle.metadata["research_intent"] == "PERSISTENCE"
    assert any("guardar_backup_retiro" in item for item in bundle.metadata["flow_path"])


def test_research_intent_data_flow_for_missing_historical_records(tmp_path):
    project = tmp_path / "data_flow"
    _write(project / "retiros.py", "def guardar_backup_retiro(data):\n    return guardar_backup_general(data)\n\ndef guardar_backup_general(data):\n    return 1\n")
    _write(project / "ventas.py", "def verderetiro():\n    return []\n")
    analysis = analyze_task("¿Por qué no aparecen los retiros históricos?")
    assert analysis.research_intent == "DATA_FLOW"
    assert analysis.auto_flow is True


def test_file_location_policy_discards_fts_and_path_noise(tmp_path):
    project = tmp_path / "location_noise"
    _write(
        project / "templates" / "sales.html",
        "{% extends 'layout.html' %}\n<link rel='stylesheet' href='/static/css/sales.css'>\n",
    )
    _write(project / "templates" / "layout.html", "<main>{% block content %}{% endblock %}</main>\n")
    _write(project / "templates" / "modules" / "sales.html", "<section class='sales'></section>\n")
    _write(project / "static" / "css" / "sales.css", ".sales { color: red; }\n")
    _write(project / "appsaidyc" / "prestamos" / "models.py", "sales html estilos ventas\n" * 8)
    _write(project / "vendor" / "myappedido.py", "def sales_html_estilos():\n    return 'ventas estilos'\n")

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("LocationNoise", project)
        app_ctx.index_service().index_project("LocationNoise")
        bundle = app_ctx.context_engine().build("LocationNoise", "¿Dónde están los estilos de sales.html?")

    paths = {item.path for item in bundle.files}
    assert {"templates/sales.html", "templates/modules/sales.html", "static/css/sales.css"} <= paths
    assert "appsaidyc/prestamos/models.py" not in paths
    assert "vendor/myappedido.py" not in paths


def test_frontend_policy_keeps_presentation_context_over_backend_keyword_noise(tmp_path):
    project = tmp_path / "frontend_noise"
    _write(
        project / "templates" / "sales.html",
        "{% extends 'layout.html' %}\n<link rel='stylesheet' href='/static/css/sales.css'>\n<script src='/static/js/sales.js'></script>\n",
    )
    _write(project / "templates" / "layout.html", "<main>{% block content %}{% endblock %}</main>\n")
    _write(project / "static" / "css" / "sales.css", "@media (max-width: 700px) { .sales { overflow: auto; height: 100vh; } }\n")
    _write(project / "static" / "js" / "sales.js", "function resizeSales() { window.scrollTo(0, 0); }\n")
    _write(project / "blueprints" / "ventas.py", "def sales_mobile_scroll():\n    return 'ventas mobile scroll'\n")
    _write(project / "services" / "sales.py", "def sales_layout_backend():\n    return 'overflow grid mobile'\n")

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("FrontendNoise", project)
        app_ctx.index_service().index_project("FrontendNoise")
        bundle = app_ctx.context_engine().build("FrontendNoise", "¿Por qué sales.html se ve mal en móvil con scroll?")

    paths = {item.path for item in bundle.files}
    assert {"templates/sales.html", "templates/layout.html", "static/css/sales.css", "static/js/sales.js"} <= paths
    assert "blueprints/ventas.py" not in paths
    assert "services/sales.py" not in paths


def test_directed_backend_flow_policy_does_not_fill_with_lateral_candidates(tmp_path):
    project = tmp_path / "send_noise"
    _write(
        project / "retiros.py",
        "def enviar_retiro_servidor(retiro):\n    return requests.post('/retiros', json=retiro)\n",
    )
    _write(project / "EnviarCompras.py", "def enviar_compras():\n    return requests.post('/compras')\n")
    _write(project / "vendor" / "retiros.py", "def retries_post():\n    return 'retiros enviados'\n")

    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("SendNoise", project)
        app_ctx.index_service().index_project("SendNoise")
        bundle = app_ctx.context_engine().build("SendNoise", "¿Por qué no se envían los retiros?")

    assert bundle.metadata["flow_path"] == ["enviar_retiro_servidor"]
    assert bundle.metadata["terminal_edges"] == [["enviar_retiro_servidor", "requests.post"]]
    assert [item.path for item in bundle.files] == ["retiros.py"]


def test_data_flow_policy_remains_deep_for_historical_records(tmp_path):
    project = tmp_path / "data_flow_depth"
    _write(
        project / "retiros.py",
        "def mostrar_retiros_historicos():\n    return cargar_retiros_historicos()\n\n"
        "def cargar_retiros_historicos():\n    return visualizar_retiros()\n\n"
        "def visualizar_retiros():\n    return guardar_backup_retiro()\n\n"
        "def guardar_backup_retiro():\n    return 'ok'\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("DataFlowDepth", project)
        app_ctx.index_service().index_project("DataFlowDepth")
        bundle = app_ctx.context_engine().build("DataFlowDepth", "¿Por qué no aparecen los retiros históricos?")

    assert bundle.analysis.research_intent == "DATA_FLOW"
    assert bundle.metadata["flow_path"][:3] == [
        "mostrar_retiros_historicos",
        "cargar_retiros_historicos",
        "visualizar_retiros",
    ]


def test_send_terminal_is_route_evidence_not_a_proven_cause(tmp_path):
    project = tmp_path / "send_evidence"
    _write(
        project / "retiros.py",
        "def enviar_retiro_servidor(retiro):\n    return requests.post('/retiros', json=retiro)\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("SendEvidence", project)
        app_ctx.index_service().index_project("SendEvidence")
        bundle = app_ctx.context_engine().build("SendEvidence", "¿Por qué no se envían los retiros?")

    diagnosis = render_diagnosis(bundle)
    assert bundle.metadata["terminal_edges"] == [["enviar_retiro_servidor", "requests.post"]]
    assert "Todavía no afirma cuál es la causa del problema" in diagnosis


def test_file_location_evidence_is_direct_or_literal_reference_only(tmp_path):
    project = tmp_path / "evidence_location"
    _write(
        project / "templates" / "sales.html",
        "{% extends 'layout.html' %}<link rel='stylesheet' href='/static/css/sales.css'>\n",
    )
    _write(project / "templates" / "layout.html", "<main></main>\n")
    _write(project / "templates" / "modules" / "sales.html", "<section></section>\n")
    _write(project / "static" / "css" / "sales.css", ".sales {}\n")
    _write(project / "blueprints" / "ventas.py", "sales estilos ventas\n" * 4)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("EvidenceLocation", project)
        app_ctx.index_service().index_project("EvidenceLocation")
        bundle = app_ctx.context_engine().build("EvidenceLocation", "¿Dónde están los estilos de sales.html?")

    records = {(item.source, item.target, item.kind) for item in bundle.evidence}
    assert ("templates/sales.html", None, "DIRECT") in records
    assert ("templates/sales.html", "static/css/sales.css", "REFERENCE") in records
    assert ("templates/sales.html", "templates/layout.html", "REFERENCE") in records
    assert all(item.source != "blueprints/ventas.py" for item in bundle.evidence)


def test_backend_flow_evidence_marks_terminal_without_claiming_cause(tmp_path):
    project = tmp_path / "evidence_send"
    _write(
        project / "retiros.py",
        "def enviar_retiro_servidor(retiro):\n    return requests.post('/retiros', json=retiro)\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("EvidenceSend", project)
        app_ctx.index_service().index_project("EvidenceSend")
        bundle = app_ctx.context_engine().build("EvidenceSend", "¿Por qué no se envían los retiros?")

    records = {(item.kind, item.target, item.demonstrated) for item in bundle.evidence}
    assert ("FLOW", None, True) in records
    assert ("FLOW_TERMINAL", "requests.post", True) in records
    assert "Todavía no afirma cuál es la causa del problema" in render_diagnosis(bundle)


def test_persistence_evidence_preserves_symbol_and_flow(tmp_path):
    project = tmp_path / "evidence_persistence"
    _write(
        project / "retiros.py",
        "def guardar_backup_retiro(data):\n    return guardar_backup_general(data)\n\n"
        "def guardar_backup_general(data):\n    return backup.append(data)\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("EvidencePersistence", project)
        app_ctx.index_service().index_project("EvidencePersistence")
        bundle = app_ctx.context_engine().build("EvidencePersistence", "¿Dónde se guardan los retiros históricos?")

    kinds = {item.kind for item in bundle.evidence if item.source == "retiros.py"}
    assert {"FLOW", "SYMBOL"} <= kinds


def test_unresolved_evidence_coexists_with_demonstrated_flow(tmp_path):
    project = tmp_path / "evidence_unresolved"
    _write(
        project / "retiros.py",
        "def verderetiros():\n    return VisualizacionValores()\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("EvidenceUnresolved", project)
        app_ctx.index_service().index_project("EvidenceUnresolved")
        bundle = app_ctx.context_engine().build("EvidenceUnresolved", "¿Por qué no aparecen los retiros históricos?")

    records = [item for item in bundle.evidence if item.source == "retiros.py"]
    assert any(item.kind == "FLOW" and item.demonstrated for item in records)
    assert any(item.kind == "UNRESOLVED" and not item.demonstrated for item in records)


def test_v16_expands_unique_constructor_flow_to_cargar_datos(tmp_path):
    project = tmp_path / "v16_retiros"
    _write(
        project / "retirosefectivo.py",
        "def verretiros():\n"
        "    return VisualizacionValores()\n",
    )
    _write(
        project / "visualizacion.py",
        "class VisualizacionValores:\n"
        "    def __init__(self):\n"
        "        self.cargar_datos()\n\n"
        "    def cargar_datos(self):\n"
        "        return consultar_historicos()\n\n"
        "def consultar_historicos():\n"
        "    return 'historial'\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("V16Retiros", project)
        app_ctx.index_service().index_project("V16Retiros")
        bundle = app_ctx.context_engine().build("V16Retiros", "¿Por qué no aparecen los retiros históricos?")

    assert bundle.metadata["flow_path"] == [
        "verretiros",
        "VisualizacionValores",
        "VisualizacionValores.__init__",
        "VisualizacionValores.cargar_datos",
        "consultar_historicos",
    ]
    assert "visualizacion.py" in [item.path for item in bundle.files]
    assert any(item.qualified_name == "VisualizacionValores.cargar_datos" for item in bundle.symbols)
    assert any(item.kind == "FLOW" and item.demonstrated for item in bundle.evidence)


def test_v16_continues_second_resolvable_call_within_limit(tmp_path):
    project = tmp_path / "v16_second_call"
    _write(project / "retiros.py", "def verretiros():\n    return Vista()\n")
    _write(
        project / "vista.py",
        "class Vista:\n"
        "    def __init__(self):\n"
        "        self.cargar_datos()\n\n"
        "    def cargar_datos(self):\n"
        "        return consultar_historicos()\n\n"
        "def consultar_historicos():\n"
        "    return 1\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("V16Second", project)
        app_ctx.index_service().index_project("V16Second")
        bundle = app_ctx.context_engine().build("V16Second", "¿Por qué no aparecen los retiros históricos?")

    assert bundle.metadata["flow_path"][-1] == "consultar_historicos"


def test_v16_keeps_ambiguous_constructor_unresolved(tmp_path):
    project = tmp_path / "v16_ambiguous"
    _write(project / "retiros.py", "def verretiros():\n    return Vista()\n")
    _write(project / "uno.py", "class Vista:\n    def __init__(self):\n        pass\n")
    _write(project / "dos.py", "class Vista:\n    def __init__(self):\n        pass\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("V16Ambiguous", project)
        app_ctx.index_service().index_project("V16Ambiguous")
        bundle = app_ctx.context_engine().build("V16Ambiguous", "¿Por qué no aparecen los retiros históricos?")

    assert bundle.metadata["flow_path"] == ["verretiros"]
    assert any("Vista" in item and "no resuelta" in item for item in bundle.metadata["flow_unresolved"])
    assert {"uno.py", "dos.py"}.isdisjoint({item.path for item in bundle.files})


def test_v16_keeps_missing_constructor_unresolved(tmp_path):
    project = tmp_path / "v16_missing"
    _write(project / "retiros.py", "def verretiros():\n    return NoExiste()\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("V16Missing", project)
        app_ctx.index_service().index_project("V16Missing")
        bundle = app_ctx.context_engine().build("V16Missing", "¿Por qué no aparecen los retiros históricos?")

    assert bundle.metadata["flow_path"] == ["verretiros"]
    assert any("NoExiste" in item and "no resuelta" in item for item in bundle.metadata["flow_unresolved"])


def test_v16_stops_at_directed_expansion_depth(tmp_path):
    project = tmp_path / "v16_depth"
    _write(project / "retiros.py", "def verretiros():\n    return Vista()\n")
    _write(
        project / "vista.py",
        "class Vista:\n"
        "    def __init__(self):\n        self.uno()\n\n"
        "    def uno(self):\n        return self.dos()\n\n"
        "    def dos(self):\n        return self.tres()\n\n"
        "    def tres(self):\n        return 1\n",
    )
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("V16Depth", project)
        app_ctx.index_service().index_project("V16Depth")
        engine = app_ctx.context_engine()
        engine.config = ContextConfig(directed_expansion_depth=2, directed_expansion_max_symbols=4)
        bundle = engine.build("V16Depth", "¿Por qué no aparecen los retiros históricos?")

    assert bundle.metadata["flow_path"] == ["verretiros", "Vista", "Vista.__init__", "Vista.uno"]
    assert "Vista.dos" not in bundle.metadata["flow_path"]


def test_v16_expansion_respects_symbol_limit_and_avoids_fts_noise(tmp_path):
    project = tmp_path / "v16_limits"
    _write(project / "retiros.py", "def verretiros():\n    return Vista()\n")
    _write(
        project / "vista.py",
        "class Vista:\n"
        "    def __init__(self):\n        self.cargar_datos()\n\n"
        "    def cargar_datos(self):\n        return self.terminal()\n\n"
        "    def terminal(self):\n        return 1\n",
    )
    _write(project / "ruido.py", "# Vista cargar_datos retiros históricos\n" * 20)
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("V16Limits", project)
        app_ctx.index_service().index_project("V16Limits")
        engine = app_ctx.context_engine()
        engine.config = ContextConfig(max_files=2, directed_expansion_depth=3, directed_expansion_max_symbols=2)
        bundle = engine.build("V16Limits", "¿Por qué no aparecen los retiros históricos?")

    assert len(bundle.files) <= 2
    assert "Vista.terminal" not in bundle.metadata["flow_path"]
    assert "ruido.py" not in [item.path for item in bundle.files]


def test_context_bundle_evidence_defaults_are_compatible_and_independent(tmp_path):
    project = tmp_path / "evidence_compatibility"
    _write(project / "sales.py", "def sales():\n    return 1\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("EvidenceCompatibility", project)
        app_ctx.index_service().index_project("EvidenceCompatibility")
        bundle = app_ctx.context_engine().build("EvidenceCompatibility", "¿Dónde está sales.py?")

    legacy_one = ContextBundle(
        bundle.project_id, bundle.project_name, bundle.task, bundle.analysis,
        bundle.files, bundle.symbols, bundle.relations, bundle.statistics, bundle.limitations,
        metadata=dict(bundle.metadata),
    )
    legacy_two = ContextBundle(
        bundle.project_id, bundle.project_name, bundle.task, bundle.analysis,
        bundle.files, bundle.symbols, bundle.relations, bundle.statistics, bundle.limitations,
    )
    legacy_one.evidence.append(EvidenceRecord("sales.py", None, "DIRECT", "HIGH", "test evidence"))
    assert legacy_two.evidence == []
    payload = bundle.to_dict()
    assert "evidence" in payload and "evidence_summary" in payload
    assert "evidence" in bundle.to_json()


def test_handoff_uses_engine_evidence_without_recalculation(tmp_path):
    from aidycai.application.ai_handoff import build_ai_handoff

    project = tmp_path / "evidence_handoff"
    _write(project / "sales.html", "<link rel='stylesheet' href='sales.css'>\n")
    _write(project / "sales.css", ".sales {}\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("EvidenceHandoff", project)
        app_ctx.index_service().index_project("EvidenceHandoff")
        bundle = app_ctx.context_engine().build("EvidenceHandoff", "¿Dónde están los estilos de sales.html?")

    handoff = build_ai_handoff(bundle)
    payload = handoff.to_dict()
    assert payload["evidence"]["records"] == [item.__dict__ for item in bundle.evidence]
    assert payload["evidence"]["summary"] == bundle.evidence_summary.__dict__


def test_handoff_preserves_flow_unresolved_relations_and_stable_serialization(tmp_path):
    from aidycai.application.ai_handoff import build_ai_handoff

    project = tmp_path / "handoff_flow"
    _write(project / "retiros.py", "def verderetiros():\n    return VisualizacionValores()\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("HandoffFlow", project)
        app_ctx.index_service().index_project("HandoffFlow")
        bundle = app_ctx.context_engine().build("HandoffFlow", "¿Por qué no aparecen los retiros históricos?")

    handoff = build_ai_handoff(bundle)
    payload = handoff.to_dict()
    assert payload["flow"]["path"] == bundle.metadata["flow_path"]
    assert payload["flow"]["unresolved_relations"] == bundle.metadata["flow_unresolved"]
    assert payload["unresolved_relations"] == bundle.metadata["flow_unresolved"]
    assert any(item["kind"] == "UNRESOLVED" for item in payload["evidence"]["records"])
    assert handoff.to_json() == build_ai_handoff(bundle).to_json()


def test_handoff_is_compatible_with_legacy_bundle_without_evidence_and_keeps_human_export(tmp_path):
    from aidycai.application.ai_handoff import build_ai_handoff

    project = tmp_path / "handoff_legacy"
    _write(project / "sales.py", "def sales():\n    return 1\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("HandoffLegacy", project)
        app_ctx.index_service().index_project("HandoffLegacy")
        bundle = app_ctx.context_engine().build("HandoffLegacy", "¿Dónde está sales.py?")

    legacy = ContextBundle(
        bundle.project_id, bundle.project_name, bundle.task, bundle.analysis,
        bundle.files, bundle.symbols, bundle.relations, bundle.statistics, bundle.limitations,
        metadata=dict(bundle.metadata),
    )
    handoff = build_ai_handoff(legacy).to_dict()
    assert handoff["evidence"]["records"] == []
    assert handoff["evidence"]["summary"] == {
        "strong_evidence": 0, "medium_evidence": 0, "weak_evidence": 0, "unresolved": 0,
    }
    assert "PROJECT: HandoffLegacy" in legacy.to_text()


def test_handoff_has_no_index_or_search_side_effects(tmp_path, monkeypatch):
    from aidycai.application.ai_handoff import build_ai_handoff
    from aidycai.infrastructure.index_store import SqliteIndexStore

    project = tmp_path / "handoff_pure"
    _write(project / "sales.py", "def sales():\n    return 1\n")
    with open_app(seed=False) as app_ctx:
        registered = app_ctx.registry.add("HandoffPure", project)
        app_ctx.index_service().index_project("HandoffPure")
        bundle = app_ctx.context_engine().build("HandoffPure", "¿Dónde está sales.py?")
        index_path = app_ctx.layout.project_index_path(registered.id)
        before = index_path.read_bytes()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("build_ai_handoff must not access the index")

    monkeypatch.setattr(SqliteIndexStore, "search", fail_if_called)
    monkeypatch.setattr(SqliteIndexStore, "replace_analysis", fail_if_called)
    handoff = build_ai_handoff(bundle)
    assert handoff.protocol == "aidycai-ai-handoff-v1"
    assert index_path.read_bytes() == before


def test_handoff_cli_writes_the_structured_json(tmp_path):
    import json

    project = tmp_path / "handoff_cli"
    output = tmp_path / "handoff.json"
    _write(project / "sales.py", "def print_sale():\n    return 'ok'\n")
    with open_app(seed=False) as app_ctx:
        app_ctx.registry.add("HandoffCLI", project)
        app_ctx.index_service().index_project("HandoffCLI")

    result = runner.invoke(
        app,
        ["handoff", "HandoffCLI", "Where is print_sale?", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["protocol"] == "aidycai-ai-handoff-v1"
    assert payload["project"]["name"] == "HandoffCLI"
