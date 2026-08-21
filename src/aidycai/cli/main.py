from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import typer
from rich.console import Console
from rich.table import Table

from aidycai.application.bootstrap import AppContext, open_app
from aidycai.application.ai_handoff import build_ai_handoff
from aidycai.application.diagnostics import render_diagnosis
from aidycai.domain.exceptions import RegistryError
from aidycai.domain.index_models import IndexSummary
from aidycai.domain.models import Project

app = typer.Typer(
    no_args_is_help=True,
    help="AIDYCAI — capa local de inteligencia para desarrollo de software.",
)
project_app = typer.Typer(no_args_is_help=True, help="Registro de proyectos externos.")
system_app = typer.Typer(no_args_is_help=True, help="Información del sistema AIDYCAI.")
app.add_typer(project_app, name="project")
app.add_typer(system_app, name="system")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(soft_wrap=True)
T = TypeVar("T")


def _with_app(action: Callable[[AppContext], T]) -> T:
    try:
        with open_app() as context:
            return action(context)
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


def _format_bytes(total_bytes: int) -> str:
    value = float(total_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{total_bytes} B"


def _status_for(project: Project) -> str:
    if not project.active:
        return "inactive"
    if not project.path.exists():
        return "missing"
    if not project.path.is_dir():
        return "not-a-directory"
    return "ok"


@project_app.command("list")
def project_list() -> None:
    """Lista los proyectos registrados y su estado."""

    def run(context: AppContext) -> None:
        projects = context.registry.list_projects()
        if not projects:
            console.print("No hay proyectos registrados.")
            return
        table = Table(title="Proyectos")
        table.add_column("Nombre")
        table.add_column("Id")
        table.add_column("Estado")
        table.add_column("Ruta")
        for project in projects:
            table.add_row(project.name, project.id, _status_for(project), str(project.path))
        console.print(table)

    _with_app(run)


@project_app.command("add")
def project_add(
    name: str = typer.Argument(help="Nombre visible del proyecto, por ejemplo AIDYC."),
    path: str = typer.Argument(help="Ruta absoluta original. No se copia."),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        help="Nombre extra de carpeta o archivo a ignorar en el scanner.",
    ),
) -> None:
    """Registra un proyecto externo por su ruta. No copia archivos."""

    def run(context: AppContext) -> None:
        project = context.registry.add(name, path, extra_excludes=exclude or None)
        context.ensure_project_data(project.id)
        console.print(f"Registrado [bold]{project.name}[/bold] -> {project.path}")

    _with_app(run)


@project_app.command("remove")
def project_remove(
    name: str = typer.Argument(help="Nombre o id del proyecto en el registro."),
) -> None:
    """Elimina el registro. No borra la carpeta original del proyecto."""

    def run(context: AppContext) -> None:
        project = context.registry.remove(name)
        console.print(
            f"Eliminado del registro [bold]{project.name}[/bold]. "
            f"La carpeta original no se tocó: {project.path}"
        )

    _with_app(run)


@project_app.command("info")
def project_info(
    name: str = typer.Argument(help="Nombre o id, por ejemplo AIDYC."),
) -> None:
    """Muestra metadatos y estadísticas básicas del proyecto."""

    def run(context: AppContext) -> None:
        info = context.registry.info(name)
        project = info.project
        scan = info.scan
        console.print(f"[bold]{project.name}[/bold] ({project.id})")
        console.print(f"Ruta: {project.path}")
        console.print(f"Activo: {'sí' if project.active else 'no'}")
        console.print(f"Estado: {info.status}")
        console.print(f"Existe: {'sí' if scan.exists else 'no'}")
        if scan.exists and scan.is_dir:
            console.print(f"Archivos: {scan.file_count}")
            console.print(f"Carpetas: {scan.dir_count}")
            console.print(f"Tamaño: {_format_bytes(scan.total_bytes)}")
            console.print(f"Carpetas ignoradas: {scan.skipped_dir_count}")
            extras = info.settings.get("excludes")
            if extras:
                console.print(f"Exclusiones extra: {extras}")
            if scan.extensions:
                top = list(scan.extensions.items())[:8]
                rendered = ", ".join(f"{ext}={count}" for ext, count in top)
                console.print(f"Extensiones: {rendered}")

    _with_app(run)


@project_app.command("enable")
def project_enable(name: str = typer.Argument(help="Nombre o id.")) -> None:
    """Marca un proyecto como activo."""

    def run(context: AppContext) -> None:
        project = context.registry.set_active(name, True)
        console.print(f"[bold]{project.name}[/bold] quedó activo.")

    _with_app(run)


@project_app.command("disable")
def project_disable(name: str = typer.Argument(help="Nombre o id.")) -> None:
    """Marca un proyecto como inactivo. No borra archivos."""

    def run(context: AppContext) -> None:
        project = context.registry.set_active(name, False)
        console.print(f"[bold]{project.name}[/bold] quedó inactivo.")

    _with_app(run)


@project_app.command("set-path")
def project_set_path(
    name: str = typer.Argument(help="Nombre o id."),
    path: str = typer.Argument(help="Nueva ruta absoluta original."),
) -> None:
    """Cambia la ruta registrada. No mueve ni copia el proyecto."""

    def run(context: AppContext) -> None:
        project = context.registry.set_path(name, path)
        console.print(f"[bold]{project.name}[/bold] ahora apunta a {project.path}")

    _with_app(run)


@system_app.command("info")
def system_info() -> None:
    """Muestra versión, carpeta de datos y estado del registro."""

    def run(context: AppContext) -> None:
        info = context.system_info()
        console.print(f"AIDYCAI {info.version}")
        console.print(f"Datos: {info.data_dir}")
        console.print(f"Base de datos: {info.database_path}")
        console.print(f"Proyectos (datos): {info.projects_dir}")
        console.print(f"Logs: {info.logs_dir}")
        console.print(f"Caché: {info.cache_dir}")
        console.print(f"Proyectos registrados: {info.project_count}")
        console.print(
            "Ubicación: %LOCALAPPDATA%\\AIDYCAI"
            if info.using_local_app_data
            else f"Ubicación: override ({info.data_dir})"
        )

    _with_app(run)


@app.command("index")
def index_cmd(
    spec: str | None = typer.Argument(None, help="Nombre del proyecto, o 'info'."),
    target: str | None = typer.Argument(None, help="Proyecto cuando spec es 'info'."),
    all_projects: bool = typer.Option(False, "--all", help="Indexar todos los proyectos activos."),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help="Reconstruir el índice completo (útil después de cambiar el analizador).",
    ),
) -> None:
    """Indexa un proyecto. Usa `index info NOMBRE` para ver el estado."""

    def run(context: AppContext) -> None:
        service = context.index_service()
        if all_projects:
            projects = [item for item in context.registry.list_projects() if item.active]
            if not projects:
                console.print("No hay proyectos activos para indexar.")
                return
            for project in projects:
                _print_index_summary(service.index_project(project.id, rebuild=rebuild))
            return
        if spec is None:
            console.print("Indica un proyecto o usa --all. Ejemplo: aidycai index AIDYC")
            raise typer.Exit(code=1)
        if spec.lower() == "info":
            if not target:
                console.print("Uso: aidycai index info AIDYC")
                raise typer.Exit(code=1)
            _print_index_info(service.stats(target))
            return
        _print_index_summary(service.index_project(spec, rebuild=rebuild))

    _with_app(run)


@app.command("search")
def search_cmd(
    project: str = typer.Argument(help="Nombre o id del proyecto."),
    query: str = typer.Argument(help="Texto a buscar."),
    limit: int = typer.Option(25, "--limit", help="Máximo de resultados."),
) -> None:
    """Busca archivos y símbolos en el índice local (FTS5)."""

    def run(context: AppContext) -> None:
        hits = context.index_service().search(project, query, limit=limit)
        if not hits:
            console.print(f"Sin resultados para '{query}' en {project}.")
            console.print("Si el índice está vacío, ejecuta: aidycai index " + project)
            return
        table = Table(title=f"Búsqueda: {query}")
        table.add_column("Tipo")
        table.add_column("Archivo")
        table.add_column("Símbolo")
        table.add_column("Líneas")
        table.add_column("Score")
        table.add_column("Detalle")
        for hit in hits:
            lines = ""
            if hit.line_start:
                lines = str(hit.line_start) if hit.line_end is None else f"{hit.line_start}-{hit.line_end}"
            table.add_row(
                hit.kind if not hit.symbol_type else hit.symbol_type,
                hit.rel_path,
                hit.qualified_name or "",
                lines,
                f"{hit.score:.3f}",
                (hit.snippet or "")[:80],
            )
        console.print(table)

    _with_app(run)


def _human_reason(reason: str) -> str:
    """Convierte señales internas del ranking en una explicación corta para humanos."""
    mapping = {
        "qualified symbol match": "coincide exactamente con un símbolo",
        "symbol text match": "el símbolo aparece relacionado con la pregunta",
        "file content match": "el contenido del archivo coincide",
        "path match": "el nombre o ruta coincide",
        "import graph relation": "está conectado por imports",
        "dependency of selected symbol": "es una dependencia del código encontrado",
        "imported by selected file": "es importado por otro archivo relevante",
        "same module": "pertenece al mismo módulo",
    }
    return mapping.get(reason, reason)


def _print_ask_result(bundle) -> None:
    """Muestra un resumen pequeño del ContextBundle, no el volcado técnico completo."""
    stats = bundle.statistics
    console.print()
    console.print(f"[bold]Encontré {stats.selected_files} archivos relevantes.[/bold]")
    console.print(
        f"Contexto preparado: {stats.selected_chars:,} caracteres "
        f"(~{stats.estimated_tokens:,} tokens)"
    )
    console.print(f"Reducción: {stats.reduction_ratio * 100:.1f}%")
    console.print(
        f"Intención: {bundle.analysis.research_intent} "
        f"(estrategia {bundle.analysis.research_strategy}, "
        f"confianza {bundle.analysis.intent_confidence:.2f})"
    )
    console.print()
    console.print("[bold]Archivos principales:[/bold]")
    shown = 0
    for item in bundle.files:
        if item.role != "PRIMARY":
            continue
        reason = _human_reason(item.reasons[0]) if item.reasons else "coincidencia relevante"
        console.print(f"  • {item.path} — {reason}")
        if item.fragments:
            fragment = item.fragments[0]
            if fragment.symbol_name:
                console.print(f"    símbolo: {fragment.symbol_name} (L{fragment.line_start}-{fragment.line_end})")
            else:
                console.print(f"    líneas: L{fragment.line_start}-{fragment.line_end}")
        shown += 1
        if shown >= 4:
            break

    if stats.selected_symbols:
        console.print()
        console.print("[bold]Símbolos relevantes:[/bold]")
        seen = set()
        shown = 0
        for symbol in bundle.symbols:
            if symbol.qualified_name in seen:
                continue
            seen.add(symbol.qualified_name)
            console.print(f"  • {symbol.qualified_name} ({symbol.rel_path})")
            shown += 1
            if shown >= 6:
                break

    console.print()
    console.print(
        "[dim]AIDYCAI todavía no responde con razonamiento: prepara el contexto para un LLM.[/dim]"
    )


@app.command("ask")
def ask_cmd(
    project: str = typer.Argument(help="Nombre o id del proyecto."),
) -> None:
    """Modo interactivo para investigar un proyecto con el Context Engine local."""
    console.print(f"[bold]AIDYCAI — investigación local: {project}[/bold]")
    console.print("Escribe una pregunta. Comandos: exportar, salir, ayuda.")

    def run(context: AppContext) -> None:
        engine = context.context_engine()
        last_bundle = None

        while True:
            try:
                question = typer.prompt("Pregunta", default="", show_default=False).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nSaliendo.")
                return

            if not question:
                continue

            command = question.lower()
            if command in {"salir", "exit", "quit", "q"}:
                console.print("Saliendo.")
                return

            if command in {"ayuda", "help", "?"}:
                console.print("Pregunta sobre el código del proyecto.")
                console.print("exportar  → guarda el último contexto en context.txt")
                console.print("salir     → termina la sesión")
                continue

            if command in {"exportar", "export"}:
                if last_bundle is None:
                    console.print("Todavía no hay una consulta para exportar.")
                    continue
                output = Path("context.txt")
                output.write_text(last_bundle.to_text() + "\n", encoding="utf-8")
                console.print(f"Contexto guardado en: {output.resolve()}")
                continue

            try:
                last_bundle = engine.build(project, question)
            except Exception as exc:
                console.print(f"[red]No pude analizar la pregunta: {exc}[/red]")
                continue

            _print_ask_result(last_bundle)

    _with_app(run)


@app.command("diagnose")
def diagnose_cmd(
    project: str = typer.Argument(help="Nombre o id del proyecto."),
    task: str = typer.Argument(help="Problema o pregunta que quieres investigar."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Guarda el diagnóstico en un archivo .txt."),
) -> None:
    """Genera un diagnóstico humano a partir del ContextBundle local."""

    def run(context: AppContext) -> None:
        bundle = context.context_engine().build(project, task)
        text = render_diagnosis(bundle)
        console.print(text)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
            console.print(f"\nEscrito: {output}")

    _with_app(run)


@app.command("context")
def context_cmd(
    project: str = typer.Argument(help="Nombre o id del proyecto."),
    task: str = typer.Argument(help="Tarea o pregunta en lenguaje natural."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Escribe context.json o context.txt."),
) -> None:
    """Construye un ContextBundle local (sin LLM)."""

    def run(context: AppContext) -> None:
        bundle = context.context_engine().build(project, task)
        stats = bundle.statistics
        console.print(f"Task:\n{bundle.task}\n")
        console.print(f"Candidates:\n{stats.candidate_files} files, {stats.candidate_symbols} symbols\n")
        console.print(
            f"Selected:\n{stats.selected_files} files\n{stats.selected_lines} lines\n"
            f"{stats.selected_chars} chars (~{stats.estimated_tokens} tokens)\n"
        )
        console.print(f"Reduction:\n{stats.reduction_ratio * 100:.1f}%\n")
        console.print("Primary:")
        for item in bundle.files:
            if item.role != "PRIMARY":
                continue
            console.print(f"  {item.path}  score={item.score:.2f}")
            console.print(f"  reason: {'; '.join(item.reasons)}")
            for fragment in item.fragments:
                loc = f"L{fragment.line_start}-{fragment.line_end}"
                console.print(f"  {loc}{' (compressed)' if fragment.compressed else ''}")
        console.print("\nSecondary:")
        for item in bundle.files:
            if item.role == "PRIMARY":
                continue
            console.print(f"  {item.path} [{item.role}] score={item.score:.2f}")
            console.print(f"  reason: {'; '.join(item.reasons)}")
        console.print("\nReasons:")
        for item in bundle.files:
            console.print(f"  {item.path}: {'; '.join(item.reasons)}")
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.suffix.lower() == ".json":
                output.write_text(bundle.to_json() + "\n", encoding="utf-8")
            else:
                output.write_text(bundle.to_text(), encoding="utf-8")
            console.print(f"\nEscrito: {output}")

    _with_app(run)


@app.command("handoff")
def handoff_cmd(
    project: str = typer.Argument(help="Nombre o id del proyecto."),
    task: str = typer.Argument(help="Tarea o pregunta en lenguaje natural."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Guarda el AI Handoff como JSON."),
) -> None:
    """Construye un AI Handoff estructurado desde el ContextBundle final."""

    def run(context: AppContext) -> None:
        handoff = build_ai_handoff(context.context_engine().build(project, task))
        content = handoff.to_json()
        if output is None:
            console.print(content)
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        console.print(f"AI Handoff escrito: {output}")

    _with_app(run)


def _print_index_summary(summary: IndexSummary) -> None:
    console.print(f"Indexando {summary.project_name}...")
    console.print("")
    console.print(f"Archivos encontrados: {summary.files_found}")
    console.print(f"Archivos de código: {summary.files_code}")
    console.print(f"Archivos de texto: {summary.files_text}")
    console.print(f"Archivos binarios: {summary.files_binary}")
    console.print(f"Archivos modificados: {summary.files_modified}")
    console.print(f"Archivos creados: {summary.files_created}")
    console.print(f"Archivos eliminados: {summary.files_deleted}")
    console.print(f"Archivos renombrados: {summary.files_renamed}")
    console.print(f"Archivos sin cambios: {summary.files_unchanged}")
    console.print("")
    console.print(f"Símbolos encontrados: {summary.symbols}")
    console.print(f"Imports: {summary.imports}")
    console.print(f"Errores: {summary.errors}")
    console.print("")
    console.print("Indexación completada.")


def _print_index_info(stats) -> None:
    console.print(f"Índice de [bold]{stats.project_name}[/bold] ({stats.project_id})")
    console.print(f"Última indexación: {stats.last_indexed_at or 'nunca'}")
    console.print(f"Última ejecución: {stats.last_run_at or 'nunca'} ({stats.last_run_status or '-'})")
    console.print(f"Archivos indexados: {stats.files_indexed}")
    console.print(f"Archivos de código: {stats.files_code}")
    console.print(f"Archivos binarios: {stats.files_binary}")
    console.print(f"Símbolos: {stats.symbols}")
    console.print(f"Imports: {stats.imports}")
    console.print(f"Aristas de import: {stats.import_edges}")
    console.print(f"Tamaño del índice: {_format_bytes(stats.index_bytes)}")
    console.print(f"Errores registrados: {stats.errors}")
    if stats.last_error:
        console.print(f"Último error: {stats.last_error}")


@app.command("gui")
def gui_cmd() -> None:
    """Abre la interfaz gráfica local de AIDYCAI."""
    try:
        from aidycai.gui.app import run_gui
        run_gui()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


def main() -> None:
    app()
