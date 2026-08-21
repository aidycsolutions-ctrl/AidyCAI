from __future__ import annotations

import re

from aidycai.domain.context_models import FlowSpec, TaskAnalysis

_STOP = frozenset(
    {
        "a", "al", "an", "como", "con", "de", "del", "donde", "el", "en", "es", "esta", "este",
        "no", "porque", "porqué", "porqué",
        "for", "how", "in", "la", "las", "los", "of", "on", "o", "para", "por", "que", "se", "the",
        "to", "un", "una", "where", "y", "class", "def", "from", "import", "pass", "return", "self",
        "true", "false", "none", "dónde", "donde", "qué", "que",
    }
)
_RELATED: dict[str, tuple[str, ...]] = {
    "factura": ("invoice", "factur", "FacturaPDF", "facturar"),
    "facturas": ("invoice", "factura", "FacturaPDF"),
    "invoice": ("factura", "Invoice"),
    "iva": ("tax", "impuesto", "vat", "TAX_RATE", "calculate_tax"),
    "impuesto": ("iva", "tax", "calculate_tax"),
    "tax": ("iva", "calculate_tax", "TAX_RATE"),
    "pdf": ("imprimir", "FacturaPDF", "print"),
    "imprimir": ("pdf", "FacturaPDF"),
    "electronica": ("dian", "enviar_factura", "facturaelectronica", "xml"),
    "electrónica": ("dian", "enviar_factura", "facturaelectronica"),
    "enviar": ("send", "dian", "enviar_factura"),
    "envia": ("enviar", "enviar_factura"),
    "envía": ("enviar", "enviar_factura"),
    "total": ("calculate_total", "calcular"),
    "calcula": ("calculate", "calculate_total", "calculate_tax"),
    "calcular": ("calculate", "calculate_total"),
    "genera": ("generate", "pdf", "FacturaPDF"),
    "generar": ("generate", "pdf", "FacturaPDF"),
    "retiro": ("retiro", "retirar", "withdrawal"),
    "retiros": ("retiro", "retirar", "withdrawal"),
    "imprime": ("imprimir", "print", "printer", "WritePrinter"),
    "imprimen": ("imprimir", "print", "printer", "WritePrinter"),
    "impresión": ("imprimir", "print", "printer", "WritePrinter"),
    "impresion": ("imprimir", "print", "printer", "WritePrinter"),
    "guardar": ("save", "write", "dump", "backup"),
    "guarda": ("guardar", "save", "write", "backup"),
    "guardado": ("guardar", "save", "write", "backup"),
    "cargar": ("load", "read", "fetch"),
    "carga": ("cargar", "load", "read", "fetch"),
    "enviar": ("send", "request", "post"),
}
_TOKEN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ_][A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ_]*", re.UNICODE)
_FILE = re.compile(r"[A-Za-z0-9_\-]+\.(?:py|js|ts|html|css|md|sql|json)", re.IGNORECASE)
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")
_DOTTED_SYMBOL = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_EXCLUDE = re.compile(r"\b(?:ignora|ignore|excluye|excluir|excepto|excluding|omit|omitir|no\s+incluir)\b", re.IGNORECASE)
_FLOW = re.compile(r"\b(?:flujo|llamada|llamadas|seguir|sigue|hasta|camino|call\s+chain|trace)\b", re.IGNORECASE)
_EXCLUSIVE = re.compile(r"\b(?:exclusivamente|solamente|solo|únicamente|unicamente|only|exclusively)\b", re.IGNORECASE)
_TERMINAL = re.compile(r"\b(?:terminal|finalmente|hasta\s+la\s+funci[oó]n\s+que|hasta\s+llegar|win32print|bytes?\s+a\s+la\s+impresora)\b", re.IGNORECASE)
_BEHAVIOR = re.compile(
    r"\b(?:por\s+qu[eé]|porque|porqu[eé]|no\s+(?:se|lo|la|los|las|funciona|aparece|aparecen|aparezca|imprime|imprimen|guarda|guardan|carga|cargan|env[ií]a|env[ií]an|muestra|muestran|lee|leen)|no\s+funciona)\b",
    re.IGNORECASE,
)
_ACTIONS = {
    "print": re.compile(r"\b(?:imprimir|imprime|imprimen|impresi[oó]n|printer|print)\b", re.IGNORECASE),
    "save": re.compile(r"\b(?:guardar|guarda|guardan|guardado|guardando|save|escribir|escribe|escriben|almacenar|almacena|almacenan|backup)\b", re.IGNORECASE),
    "load": re.compile(r"\b(?:cargar|carga|cargan|load|leer|lee|leen|obtener|obtiene|obtienen|fetch)\b", re.IGNORECASE),
    "send": re.compile(r"\b(?:enviar|env[ií]a|env[ií]an|send|post)\b", re.IGNORECASE),
    "show": re.compile(r"\b(?:mostrar|muestra|muestran|mostrar|aparece|aparecen|visible|ver|visualizar|visualiza|display)\b", re.IGNORECASE),
}
_INCOMING = re.compile(r"\b(?:qui[eé]n\s+llama|llamado\s+por|callers?|incoming)\b", re.IGNORECASE)
_STOP_EXCLUDE = {"y", "o", "cualquier", "otro", "otra", "flujo", "flow", "archivo", "archivos", "funcion", "función", "funciones"}


def analyze_task(task: str) -> TaskAnalysis:
    raw_files = [match.group(0) for match in _FILE.finditer(task)]
    dotted = [
        match.group(0)
        for match in _DOTTED_SYMBOL.finditer(task)
        if not match.group(0).lower().endswith((".py", ".js", ".ts", ".html", ".css", ".md", ".sql", ".json"))
    ]
    tokens = _TOKEN.findall(task)
    keywords: list[str] = []
    symbol_candidates: list[str] = []
    explicit_symbols: list[str] = []
    related: list[str] = []

    for token in tokens:
        lowered = token.lower()
        if lowered in _STOP or len(token) < 2:
            continue
        if token not in keywords and lowered not in {item.lower() for item in keywords}:
            keywords.append(token)
        if _looks_like_symbol(token):
            if token not in symbol_candidates:
                symbol_candidates.append(token)
            if token not in explicit_symbols:
                explicit_symbols.append(token)
        for piece in _split_ident(token):
            if piece.lower() not in _STOP and len(piece) > 2 and piece not in keywords:
                keywords.append(piece)
        for extra in _RELATED.get(lowered, ()):
            if extra not in related:
                related.append(extra)
            if _looks_like_symbol(extra) and extra not in symbol_candidates:
                symbol_candidates.append(extra)

    file_candidates = list(raw_files)
    for token in keywords + related:
        if token.lower().endswith((".py", ".js", ".md")) and token not in file_candidates:
            file_candidates.append(token)

    until_targets = _extract_until_targets(task)
    requested_symbols = _extract_requested_symbols(task)
    if not requested_symbols:
        requested_symbols = [item for item in explicit_symbols if "_" in item]
    explicit_flow_symbols = []
    for item in dotted + requested_symbols + until_targets:
        if item not in explicit_flow_symbols:
            explicit_flow_symbols.append(item)
    action_terms = [name for name, pattern in _ACTIONS.items() if pattern.search(task)]
    action_vocab = {
        action
        for action in action_terms
    }
    action_surface_terms = set()
    for action in action_terms:
        action_surface_terms.update(
            token.lower()
            for token in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ_][A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ_]*", task)
            if _ACTIONS[action].search(token)
        )
    action_related = set()
    for action in action_terms:
        for alias in {
            "print": ("imprimir", "imprime", "impres", "print", "printer", "ticket", "writeprinter"),
            "save": ("guardar", "guarda", "guardan", "guardado", "guardando", "save", "write", "backup", "dump", "almacena", "almacenar", "escribe"),
            "load": ("cargar", "carga", "cargan", "load", "leer", "read", "fetch", "obtiene", "obtener"),
            "send": ("enviar", "envia", "envía", "envían", "send", "post", "request", "upload"),
            "show": ("mostrar", "muestra", "muestran", "aparece", "aparecen", "display", "visualiza", "ver"),
        }.get(action, ()):
            action_related.add(alias.lower())
    subject_terms = _extract_subject_terms(task, action_terms, keywords, related)
    # A behavioral question can be directed even when the user did not use
    # the word ``flujo``. Questions such as ``dónde se guardan`` are also
    # flow investigations: the user is asking where an action is materialized.
    behavioral_action = bool(action_terms) and (_BEHAVIOR.search(task) or re.search(r"\b(?:d[oó]nde|where)\b", task, re.IGNORECASE))
    auto_flow = bool(action_terms and behavioral_action) and not explicit_flow_symbols
    terminal_requested = bool(_TERMINAL.search(task)) or (auto_flow and "print" in action_terms)
    explicit_flow_intent = len(explicit_flow_symbols) >= 2 or terminal_requested
    flow_requested = bool(_FLOW.search(task)) or explicit_flow_intent or auto_flow
    flow_only = bool(_EXCLUSIVE.search(task)) and flow_requested
    follow_calls = bool(re.search(r"\b(?:seguir|sigue|llamada|llamadas|call\s+chain|trace)\b", task, re.IGNORECASE)) or explicit_flow_intent or auto_flow
    flow_direction = "incoming" if _INCOMING.search(task) else "outgoing"
    flow_symbols = []
    for item in explicit_flow_symbols:
        if item not in flow_symbols:
            flow_symbols.append(item)
    # A qualified symbol is a much stronger anchor than generic glossary terms.
    starts = dotted[:1] or ([explicit_flow_symbols[0]] if explicit_flow_symbols else [])
    start_tails = {item.rsplit(".", 1)[-1].lower() for item in starts}
    targets = [
        item for item in explicit_flow_symbols
        if item not in starts and item.rsplit(".", 1)[-1].lower() not in start_tails
    ]
    exclude_terms = _extract_exclusions(task)
    flow_spec = FlowSpec(
        strict=flow_only,
        direction=flow_direction,
        start_symbols=tuple(starts),
        target_symbols=tuple(targets),
        terminal_terms=("win32print", "WritePrinter") if terminal_requested else (),
        excluded_terms=tuple(exclude_terms),
    )

    queries = _search_queries(task, keywords, symbol_candidates, related)
    analysis = TaskAnalysis(
        task=task,
        keywords=keywords,
        symbol_candidates=symbol_candidates,
        file_candidates=file_candidates,
        related_terms=related,
        search_queries=queries,
        flow_requested=flow_requested,
        flow_only=flow_only,
        follow_calls=follow_calls,
        flow_direction=flow_direction,
        flow_start_candidates=starts,
        flow_target_candidates=targets,
        exclude_terms=exclude_terms,
        terminal_requested=terminal_requested,
        auto_flow=auto_flow,
        action_terms=action_terms,
        subject_terms=subject_terms,
        flow_spec=flow_spec,
    )

    # Intent is a strategy layer over the existing deterministic extraction.
    # It does not replace filename matching, ranking or graph resolution.
    from aidycai.application.research_intent import classify_research_intent

    intent = classify_research_intent(task, analysis)
    analysis.research_intent = intent.kind
    analysis.research_strategy = intent.strategy
    analysis.intent_confidence = intent.confidence
    analysis.intent_signals = list(intent.signals)

    # UI/layout intent wins over implicit action-flow inference. An explicit
    # user-requested flow is preserved.
    if intent.kind in {"FRONTEND_RESPONSIVE", "FRONTEND_LAYOUT"} and not analysis.flow_start_candidates and not analysis.terminal_requested:
        analysis.auto_flow = False
        analysis.flow_requested = bool(_FLOW.search(task))
        analysis.follow_calls = bool(re.search(r"\\b(?:seguir|sigue|llamada|llamadas|call\\s+chain|trace)\\b", task, re.IGNORECASE))

    # Frontend investigations need vocabulary that is otherwise absent from
    # symbol-oriented search. These terms are evidence hints, not global rank
    # changes, and only apply to frontend intent.
    if intent.kind in {"FRONTEND_RESPONSIVE", "FRONTEND_LAYOUT"}:
        frontend_terms = (
            "media", "media query", "overflow", "height", "min-height",
            "max-height", "position", "sticky", "fixed", "flex", "grid",
            "viewport", "scroll", "layout", "extends",
        )
        for term in frontend_terms:
            if term not in analysis.related_terms:
                analysis.related_terms.append(term)
            if term not in analysis.search_queries:
                analysis.search_queries.append(term)
        analysis.search_queries = analysis.search_queries[:24]

    return analysis


def _extract_subject_terms(
    task: str, action_terms: list[str], keywords: list[str], related: list[str]
) -> list[str]:
    """Extract the primary object of an action phrase, excluding destinations.

    For example, in ``se envían los retiros al servidor`` the object is
    ``retiros`` while ``servidor`` is a destination. This deterministic
    distinction is important when choosing a flow root: a helper named
    ``enviar_al_servidor`` must not beat the higher-level function that
    handles the requested object.
    """
    if not action_terms:
        return [item for item in [*keywords, *related] if len(item) >= 3]

    action_patterns = {
        "print": r"(?:imprimir|imprime|imprimen|impresi[oó]n|printer|print)",
        "save": r"(?:guardar|guarda|guardan|guardado|guardando|save|escribir|escribe|escriben|almacenar|almacena|almacenan|backup)",
        "load": r"(?:cargar|carga|cargan|load|leer|lee|leen|obtener|obtiene|obtienen|fetch)",
        "send": r"(?:enviar|env[ií]a|env[ií]an|send|post)",
        "show": r"(?:mostrar|muestra|muestran|aparece|aparecen|visible|ver|visualizar|visualiza|display)",
    }
    action_related = {
        alias.lower()
        for alias in {
            "print": ("imprimir", "imprime", "imprimen", "impresión", "printer", "print"),
            "save": ("guardar", "guarda", "guardan", "guardado", "guardando", "save", "escribir", "escribe", "escriben", "almacenar", "almacena", "almacenan", "backup"),
            "load": ("cargar", "carga", "cargan", "load", "leer", "lee", "leen", "obtener", "obtiene", "obtienen", "fetch"),
            "send": ("enviar", "envia", "envía", "envían", "send", "post"),
            "show": ("mostrar", "muestra", "muestran", "aparece", "aparecen", "visible", "ver", "visualizar", "visualiza", "display"),
        }.get(action_terms[0], ())
    }
    action_pattern = action_patterns.get(action_terms[0])
    if not action_pattern:
        return [item for item in [*keywords, *related] if len(item) >= 3]

    match = re.search(action_pattern, task, re.IGNORECASE)
    if not match:
        return [item for item in [*keywords, *related] if len(item) >= 3]

    tail = task[match.end():]
    boundary = re.search(
        r"\b(?:al|a|al\s+servidor|en|desde|por|para|con|mediante|hacia|hasta)\b",
        tail,
        re.IGNORECASE,
    )
    if boundary:
        tail = tail[:boundary.start()]

    raw_terms = _TOKEN.findall(tail)
    subject: list[str] = []
    for term in raw_terms:
        lowered = term.lower()
        if lowered in _STOP or lowered in action_related:
            continue
        if len(lowered) < 3:
            continue
        if lowered not in {item.lower() for item in subject}:
            subject.append(term)

    # Keep indexed glossary relations such as ``retiro`` when the user says
    # ``retiros``. They provide useful singular matching against symbols and
    # filenames such as ``retirosefectivo.py``.
    subject_lower = {item.lower() for item in subject}
    for term in related:
        lowered = term.lower()
        if lowered in subject_lower or lowered in action_related or len(lowered) < 3:
            continue
        if any(lowered in item.lower() or item.lower() in lowered for item in subject):
            subject.append(term)
            subject_lower.add(lowered)
    if subject:
        return subject

    return [
        item for item in [*keywords, *related]
        if len(item) >= 3 and item.lower() not in action_related
    ]


def _extract_requested_symbols(task: str) -> list[str]:
    """Extract function-like identifiers explicitly requested as code targets.

    Identifiers mentioned later as implementation details (for example
    ``lista_retiros``) are context requirements, not graph waypoints. The
    explicit request section is therefore treated separately from generic
    underscore-token detection.
    """
    result: list[str] = []
    match = re.search(r"\b(?:c[oó]digo|funciones?|m[eé]todos?)\s+(?:completo\s+de\s+)?(.+?)(?=\b(?:incluyendo|incluye|con)\b|[.!?]\s|$)", task, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(?:necesito|need)\s+(.+?)(?=\b(?:incluyendo|incluye|con)\b|[.!?]\s|$)", task, re.IGNORECASE)
    if not match:
        return result
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", match.group(1)):
        if "_" in token and token not in result:
            result.append(token)
    return result


def _extract_until_targets(task: str) -> list[str]:
    result: list[str] = []
    pattern = r"\b(?:hasta|until)\s+(?:la\s+)?(?:funci[oó]n\s+que\s+)?(?:finalmente\s+)?(?:ejecuta\s+)?([A-Za-z_][A-Za-z0-9_.]*)"
    for match in re.finditer(pattern, task, re.IGNORECASE):
        token = match.group(1).rstrip(".,;:")
        if token.lower() in {"funcion", "función", "que", "la", "el", "win32print", "writeprinter"}:
            continue
        if token not in result:
            result.append(token)
    return result


def _extract_exclusions(task: str) -> list[str]:
    result: list[str] = []
    for match in _EXCLUDE.finditer(task):
        tail = task[match.end():]
        tail = re.split(r"[!?;\n]|\.(?=\s+[A-ZÁÉÍÓÚÜÑ]|\s*$)|\by\s+cualquier\s+otro\b|\bbut\b|\bpero\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]
        cutoff = len(tail)
        for token_match in _TOKEN.finditer(tail):
            token = token_match.group(0)
            if "_" in token and _looks_like_symbol(token):
                cutoff = token_match.start()
                break
        exclusion_text = tail[:cutoff]
        for token in _FILE.findall(exclusion_text):
            if token.lower() not in {item.lower() for item in result}:
                result.append(token)
        for token in _TOKEN.findall(exclusion_text):
            lowered = token.lower()
            if lowered in _STOP_EXCLUDE or lowered in _STOP or len(token) < 3:
                continue
            if token.lower() not in {item.lower() for item in result} and token not in {"y", "and"}:
                result.append(token)
    return result


def _looks_like_symbol(token: str) -> bool:
    if "_" in token:
        return True
    if token[:1].isupper() and any(ch.islower() for ch in token):
        return True
    if token.isupper() and len(token) > 2:
        return True
    return False


def _split_ident(token: str) -> list[str]:
    if "_" in token:
        return [part for part in token.split("_") if part]
    return _CAMEL.findall(token) or [token]


def _search_queries(task: str, keywords: list[str], symbols: list[str], related: list[str]) -> list[str]:
    queries: list[str] = []
    for item in [*symbols, *related, *keywords]:
        if item and item not in queries:
            queries.append(item)
    important = [item for item in keywords if item.lower() not in _STOP]
    if len(important) >= 2:
        joined = " ".join(important[:4])
        if joined not in queries:
            queries.append(joined)
    return queries[:16]
