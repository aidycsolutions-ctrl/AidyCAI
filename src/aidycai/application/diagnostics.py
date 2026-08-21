from __future__ import annotations

from aidycai.domain.context_models import ContextBundle, ROLE_PRIMARY


def human_reason(reason: str) -> str:
    mapping = {
        "qualified symbol match": "coincide exactamente con un símbolo",
        "symbol text match": "el símbolo está relacionado con la pregunta",
        "file content match": "el contenido coincide con la pregunta",
        "path match": "el nombre o ruta coincide",
        "import graph relation": "está conectado por imports",
        "dependency of selected symbol": "es una dependencia del código encontrado",
        "imported by selected file": "es importado por otro archivo relevante",
        "same module": "pertenece al mismo módulo",
    }
    return mapping.get(reason, reason)


def _first_reason(item) -> str:
    return human_reason(item.reasons[0]) if item.reasons else "coincidencia relevante"


def render_diagnosis(bundle: ContextBundle) -> str:
    """Renderiza un resumen humano del ContextBundle, sin intentar diagnosticar semánticamente."""
    stats = bundle.statistics
    lines = [
        "DIAGNÓSTICO AIDYCAI",
        "=" * 60,
        "",
        f"Proyecto: {bundle.project_name}",
        f"Pregunta: {bundle.task}",
        "",
        f"AIDYCAI encontró {stats.candidate_files} archivos candidatos y seleccionó "
        f"{stats.selected_files} para investigar.",
        "",
        "ARCHIVOS PRIORITARIOS",
        "-" * 60,
    ]

    primary = [item for item in bundle.files if item.role == ROLE_PRIMARY]
    for index, item in enumerate(primary, 1):
        lines.append(f"{index}. {item.path}")
        lines.append(f"   Motivo: {_first_reason(item)}")
        for fragment in item.fragments[:4]:
            location = f"L{fragment.line_start}-{fragment.line_end}"
            if fragment.symbol_name:
                lines.append(f"   → {fragment.symbol_name} ({location})")
            else:
                lines.append(f"   → {location}")

    secondary = [item for item in bundle.files if item.role != ROLE_PRIMARY]
    if secondary:
        lines.extend(["", "ARCHIVOS DE APOYO", "-" * 60])
        for item in secondary:
            lines.append(f"• {item.path} [{item.role}] — {_first_reason(item)}")

    call_relations = [item for item in bundle.relations if item.kind == "call"]
    import_relations = [item for item in bundle.relations if item.kind == "import"]

    if call_relations:
        lines.extend(["", "FLUJO DE LLAMADAS DETECTADO", "-" * 60])
        for relation in call_relations[:10]:
            lines.append(f"• {relation.reason}")
        if len(call_relations) > 10:
            lines.append(f"• ... y {len(call_relations) - 10} llamadas más")

    if import_relations:
        lines.extend(["", "RELACIONES DE IMPORTACIÓN", "-" * 60])
        for relation in import_relations[:8]:
            lines.append(f"• {relation.source} → {relation.target}")
        if len(import_relations) > 8:
            lines.append(f"• ... y {len(import_relations) - 8} relaciones más")

    if bundle.symbols:
        lines.extend(["", "FUNCIONES / SÍMBOLOS PARA REVISAR", "-" * 60])
        seen: set[str] = set()
        count = 0
        for symbol in bundle.symbols:
            name = symbol.qualified_name or symbol.name
            if not name or name in seen:
                continue
            seen.add(name)
            location = ""
            if symbol.line_start:
                location = f" L{symbol.line_start}"
            lines.append(f"• {name} — {symbol.rel_path}{location}")
            count += 1
            if count >= 12:
                break

    analysis = getattr(bundle, "analysis", None)
    if analysis is not None:
        lines.extend(["", "INTENCIÓN DE INVESTIGACIÓN", "-" * 60])
        lines.append(f"Tipo: {analysis.research_intent}")
        lines.append(f"Estrategia: {analysis.research_strategy}")
        lines.append(f"Confianza: {analysis.intent_confidence:.2f}")
        if analysis.intent_signals:
            lines.append("Señales: " + ", ".join(analysis.intent_signals))
    if analysis is not None and analysis.flow_requested:
        lines.extend(["", "INVESTIGACIÓN DE FLUJO", "-" * 60])
        lines.append(f"Modo: {'EXCLUSIVO' if bundle.analysis.flow_only else 'DIRIGIDO'}")
        lines.append(f"Dirección: {bundle.analysis.flow_direction}")
        if bundle.analysis.flow_start_candidates:
            lines.append("Inicio: " + ", ".join(bundle.analysis.flow_start_candidates))
        if bundle.analysis.flow_target_candidates:
            lines.append("Objetivos: " + ", ".join(bundle.analysis.flow_target_candidates))
        if bundle.analysis.terminal_requested:
            lines.append("Terminal solicitado: win32print / salida de bytes")
        if bundle.analysis.exclude_terms:
            lines.append("Excluidos: " + ", ".join(bundle.analysis.exclude_terms))
        flow_path = bundle.metadata.get("flow_path", [])
        if flow_path:
            lines.append("Camino resuelto:")
            for index, symbol in enumerate(flow_path, 1):
                lines.append(f"  {index}. {symbol}")
        unresolved = bundle.metadata.get("flow_unresolved", [])
        if unresolved:
            lines.append("Tramos no resueltos:")
            lines.extend(f"  - {item}" for item in unresolved)
        terminal_edges = bundle.metadata.get("terminal_edges", [])
        for source, terminal in terminal_edges:
            lines.append(f"Terminal: {source} → {terminal}")

    # Keep the presentation helper compatible with the lightweight legacy
    # bundles used by callers that predate V15 evidence.
    evidence = getattr(bundle, "evidence", [])
    if evidence:
        lines.extend(["", "EVIDENCIA DEL CONTEXTO", "-" * 60])
        for item in evidence[:20]:
            target = f" → {item.target}" if item.target else ""
            state = "DEMONSTRATED" if item.demonstrated else "UNRESOLVED"
            lines.append(f"• {item.source}{target} [{item.kind} / {item.confidence} / {state}]")
            lines.append(f"  {item.reason}")
        if len(evidence) > 20:
            lines.append(f"• ... y {len(evidence) - 20} evidencias más")
        summary = bundle.evidence_summary
        lines.append(
            "Calidad: "
            f"{summary.strong_evidence} fuerte(s), {summary.medium_evidence} media(s), "
            f"{summary.weak_evidence} débil(es), {summary.unresolved} sin resolver."
        )

    lines.extend([
        "",
        "QUÉ SIGNIFICA ESTE RESULTADO",
        "-" * 60,
        "AIDYCAI ha reducido el proyecto a las zonas que considera más relevantes.",
        "En una investigación de flujo, el camino dirigido tiene prioridad sobre el ranking textual y no se rellena con contexto lateral.",
        "Todavía no afirma cuál es la causa del problema: ese análisis requiere revisar el código.",
        "",
        f"Contexto seleccionado: {stats.selected_chars:,} caracteres (~{stats.estimated_tokens:,} tokens).",
    ])
    return "\n".join(lines)


def render_human_answer(bundle: ContextBundle) -> str:
    """Render a short user-facing answer from deterministic evidence.

    This is deliberately not presented as a semantic diagnosis: it summarizes
    what the local index actually found and, when available, the directed path.
    """
    stats = bundle.statistics
    primary = [item for item in bundle.files if item.role == ROLE_PRIMARY]
    files = [item.path for item in primary[:4]]
    analysis = bundle.analysis

    if analysis.flow_requested and bundle.metadata.get("flow_path"):
        path = list(bundle.metadata.get("flow_path", []))
        if len(path) >= 2:
            shown = " → ".join(path[:5])
            if len(path) > 5:
                shown += " → …"
            if bundle.metadata.get("terminal_edges"):
                terminal = bundle.metadata["terminal_edges"][-1][1]
                return (
                    f"Seguí el flujo relacionado con tu pregunta. La ruta encontrada pasa por "
                    f"{shown} y llega hasta {terminal}. "
                    f"Los archivos principales que sustentan el recorrido son: {', '.join(files)}."
                )
            return (
                f"Seguí el flujo relacionado con tu pregunta. La ruta encontrada pasa por {shown}. "
                f"Los archivos principales son: {', '.join(files)}."
            )

    if files:
        if len(files) == 1:
            location = files[0]
        elif len(files) == 2:
            location = f"{files[0]} y {files[1]}"
        else:
            location = ", ".join(files[:-1]) + f" y {files[-1]}"
        return (
            f"La parte más relevante que encontré está en {location}. "
            f"Revisé {stats.selected_files} archivos y seleccioné {stats.selected_lines} líneas "
            "para investigar la pregunta. El detalle técnico queda disponible en el diagnóstico."
        )

    return (
        "No encontré suficiente código relevante para responder todavía. "
        "Puedes revisar el diagnóstico técnico para ver qué candidatos fueron descartados."
    )
