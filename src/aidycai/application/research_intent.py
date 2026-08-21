from __future__ import annotations

from dataclasses import dataclass
import re

from aidycai.domain.context_models import TaskAnalysis


@dataclass(frozen=True)
class ResearchIntent:
    """Deterministic classification of what kind of investigation a task needs."""

    kind: str
    strategy: str
    confidence: float
    signals: tuple[str, ...] = ()


_FRONTEND_RESPONSIVE = re.compile(
    r"\b(?:frontend|front-end|interfaz|ui|html|css|estilos?|layout|responsive|responsivo|"
    r"m[oó]vil|mobile|tablet|scroll|viewport|media\s+queries?|overflow|alto|altura|"
    r"pegad[oa]|pegada|fixed|sticky|flex|grid)\b", re.I
)
_FRONTEND_LAYOUT = re.compile(
    r"\b(?:frontend|front-end|interfaz|ui|html|css|estilos?|layout|estructura|"
    r"contenedor|scroll|overflow|viewport|flex|grid|sticky|fixed)\b", re.I
)
_FILE_LOCATION = re.compile(
    r"\b(?:d[oó]nde|where)\b.{0,80}\b(?:est[aá]n|est[aá]|se\s+(?:encuentran|ubican)|ubicad[oa]s?|"
    r"localiz[ao]|archivo|archivos|estilos?|css)\b", re.I
)
_PERSISTENCE = re.compile(
    r"\b(?:guardan?|guardado|guardar|persistencia|persistir|backup|hist[oó]ricos?|historial|"
    r"almacenan?|almacenamiento|escriben?)\b", re.I
)
_DATABASE = re.compile(
    r"\b(?:base\s+de\s+datos|database|sqlite|sql|tabla|tablas|query|consulta|select|insert|update|delete)\b", re.I
)
_NETWORK = re.compile(
    r"\b(?:servidor|server|api|http|https|request|requests|post|get|endpoint|red|network|"
    r"enviar|env[ií]an?|subir|upload)\b", re.I
)
_SYNC = re.compile(r"\b(?:sincronizaci[oó]n|sincronizar|sync|sincroniza|replicar|réplica|replica)\b", re.I)
_PRINTING = re.compile(r"\b(?:imprimir|impresi[oó]n|impresora|printer|ticket|win32print|print)\b", re.I)
_ERROR = re.compile(r"\b(?:error|excepci[oó]n|traceback|fall[oa]|falla|crash|rompe|broken|bug)\b", re.I)
_DATA_FLOW = re.compile(
    r"\b(?:no\s+(?:aparecen?|muestran?|se\s+ven)|aparecen?|muestran?|visualiz|"
    r"datos?|flujo\s+de\s+datos|de\s+d[oó]nde\s+vienen)\b", re.I
)


def classify_research_intent(task: str, analysis: TaskAnalysis) -> ResearchIntent:
    """Classify investigation strategy without changing ranking weights globally."""

    frontend_responsive = bool(_FRONTEND_RESPONSIVE.search(task))
    frontend_layout = bool(_FRONTEND_LAYOUT.search(task))
    file_location = bool(_FILE_LOCATION.search(task))
    persistence = bool(_PERSISTENCE.search(task))
    database = bool(_DATABASE.search(task))
    network = bool(_NETWORK.search(task))
    sync = bool(_SYNC.search(task))
    printing = bool(_PRINTING.search(task))
    error = bool(_ERROR.search(task))
    data_flow = bool(_DATA_FLOW.search(task))

    # Explicit file-location questions are intentionally shallow.
    if file_location and not any((analysis.action_terms, analysis.flow_requested, data_flow)):
        return ResearchIntent("FILE_LOCATION", "DIRECT_FILE_LOOKUP", 0.96, ("location",))

    if frontend_responsive:
        signals = tuple(
            label for label, hit in (
                ("frontend", frontend_layout),
                ("responsive", True),
                ("css/layout", frontend_layout),
            ) if hit
        )
        return ResearchIntent("FRONTEND_RESPONSIVE", "FRONTEND_RESPONSIVE", 0.98, signals)

    if frontend_layout:
        return ResearchIntent("FRONTEND_LAYOUT", "FRONTEND_LAYOUT", 0.94, ("frontend", "layout"))

    if printing:
        return ResearchIntent("PRINTING", "BACKEND_FLOW", 0.93, ("printing",))

    if sync:
        return ResearchIntent("SYNC", "DATA_FLOW", 0.92, ("sync",))

    if database:
        return ResearchIntent("DATABASE", "DATA_FLOW", 0.94, ("database",))

    if data_flow and analysis.action_terms and analysis.action_terms[0] in {"show", "load"} and bool(re.search(r"\b(?:por\s+qu[eé]|porque|no\s+|no\s+aparecen?|no\s+se)\b", task, re.I)):
        return ResearchIntent("DATA_FLOW", "DATA_FLOW", 0.91, ("data-flow",))

    if persistence and analysis.action_terms:
        return ResearchIntent("PERSISTENCE", "PERSISTENCE", 0.96, ("persistence",))

    if network and analysis.action_terms:
        return ResearchIntent("BACKEND_FLOW", "BACKEND_FLOW", 0.95, ("network",))

    if error:
        return ResearchIntent("ERROR", "GENERAL_DIAGNOSTIC", 0.90, ("error",))

    if analysis.flow_requested or analysis.auto_flow:
        return ResearchIntent("BACKEND_FLOW", "BACKEND_FLOW", 0.90, ("flow",))

    return ResearchIntent("GENERAL_DIAGNOSTIC", "GENERAL_DIAGNOSTIC", 0.70, ())
