from __future__ import annotations

import time
import difflib
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from aidycai.application.ranking import (
    SIGNAL_DEPENDENCY,
    SIGNAL_EXACT_FILENAME,
    SIGNAL_EXACT_BASENAME,
    SIGNAL_EXACT_QUALIFIED,
    SIGNAL_EXACT_SYMBOL,
    SIGNAL_FILE_FTS,
    SIGNAL_FUNCTION_CALL,
    SIGNAL_IMPORT_IN,
    SIGNAL_IMPORT_OUT,
    SIGNAL_PATH,
    SIGNAL_SAME_MODULE,
    SIGNAL_SYMBOL_FTS,
    add_signal,
)
from aidycai.application.registry import ProjectRegistry
from aidycai.application.task_analysis import analyze_task
from aidycai.domain.context_models import (
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SECONDARY,
    ContextBundle,
    ContextConfig,
    ContextEvidenceSummary,
    FlowSpec,
    ContextRelation,
    ContextStatistics,
    Fragment,
    EvidenceRecord,
    SelectedFile,
    SelectedSymbol,
    TaskAnalysis,
)
from aidycai.domain.exceptions import IndexingError
from aidycai.domain.index_models import SymbolRecord
from aidycai.domain.models import Project
from aidycai.infrastructure.classify import decode_text
from aidycai.infrastructure.index_store import SqliteIndexStore
from aidycai.infrastructure.paths import DataLayout

_LIMITATIONS = [
    "Análisis de tarea determinista: no hay LLM ni embeddings.",
    "La expansión usa el grafo de imports Python resuelto; imports dinámicos no aparecen.",
    "Los fragmentos se recortan alrededor de símbolos; un archivo puede contener más código relevante.",
]


_PRESENTATION_SUFFIXES = frozenset({".html", ".htm", ".css", ".scss", ".js", ".ts"})
_TEMPLATE_REFERENCES = re.compile(
    r"(?:extends|include)\s+[\"']([^\"']+)[\"']|(?:href|src)\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResearchStrategyPolicy:
    """Selection constraints local to one research strategy.

    This policy deliberately runs after candidate collection. It never changes
    FTS, graph construction, or the global ranking weights.
    """

    allowed_paths: frozenset[str] | None = None
    preferred_paths: tuple[str, ...] = ()


class ContextEngine:
    """Task → search → rank → graph → select → compress → ContextBundle."""

    def __init__(
        self,
        layout: DataLayout,
        registry: ProjectRegistry,
        config: ContextConfig | None = None,
    ) -> None:
        self._layout = layout
        self._registry = registry
        self.config = config or ContextConfig()

    def analyze(self, task: str) -> TaskAnalysis:
        return analyze_task(task)

    def build(self, name_or_id: str, task: str) -> ContextBundle:
        started = time.perf_counter()
        project = self._registry.require(name_or_id)
        index_path = self._layout.project_index_path(project.id)
        if not index_path.exists():
            raise IndexingError(
                f"No hay índice para '{project.name}'. Ejecuta: aidycai index {project.name}"
            )
        analysis = analyze_task(task)
        store = SqliteIndexStore(index_path, project.id, project.name)
        try:
            search_started = time.perf_counter()
            file_scores, file_reasons, symbol_hits = self._collect(store, analysis)
            search_seconds = time.perf_counter() - search_started

            flow_symbols: dict[str, SymbolRecord] = {}
            flow_required_symbols: dict[str, SymbolRecord] = {}
            flow_paths: list[str] = []
            flow_unresolved: list[str] = []
            terminal_edges: list[tuple[str, str]] = []
            actual_flow_path: list[str] = []
            if analysis.flow_requested and analysis.follow_calls:
                if analysis.auto_flow and not analysis.flow_start_candidates:
                    self._infer_auto_flow_start(store, analysis, file_scores, symbol_hits)
                (
                    flow_paths,
                    flow_symbols,
                    flow_required_symbols,
                    flow_depth,
                    flow_unresolved,
                    terminal_edges,
                    actual_flow_path,
                ) = self._resolve_flow(store, analysis)
                graph_depth = flow_depth
                if flow_paths:
                    for path in flow_paths:
                        # A resolved directed flow is stronger evidence than a
                        # generic filename/FTS hit. Boost it before normal file
                        # selection so unrelated modules such as EnviarCompras
                        # cannot occupy the primary slots of a retiros flow.
                        file_scores[path] = file_scores.get(path, 0.0) + 20.0
                        file_reasons.setdefault(path, [])
                        if "flow path" not in file_reasons[path]:
                            file_reasons[path].append("flow path")
                    for symbol in [*flow_symbols.values(), *flow_required_symbols.values()]:
                        symbol_hits[symbol.qualified_name] = symbol
            else:
                # Python import/call expansion is useful for backend/data-flow
                # investigations but is noise for a frontend layout question.
                if analysis.research_intent in {"FRONTEND_RESPONSIVE", "FRONTEND_LAYOUT", "FILE_LOCATION"}:
                    graph_depth = 0
                else:
                    graph_depth = self._expand_graph(store, file_scores, file_reasons)
                    call_depth = self._expand_calls(store, file_scores, file_reasons)
                    graph_depth = max(graph_depth, call_depth)
                    self._boost_same_module(file_scores, file_reasons)

            policy = self._research_strategy_policy(project, store, analysis, flow_paths, file_reasons)
            self._apply_strategy_policy(file_scores, file_reasons, policy)
            if analysis.flow_only and flow_paths:
                selected_paths, roles = self._select_flow_files(flow_paths)
            else:
                selected_paths, roles = self._select_files(
                    file_scores,
                    file_reasons,
                    analysis=analysis,
                    preferred_paths=policy.preferred_paths,
                )
            preferred_flow_symbols = dict(flow_symbols)
            preferred_flow_symbols.update(flow_required_symbols)
            symbols = self._select_symbols(
                store, selected_paths, roles, symbol_hits, file_scores,
                preferred_symbols=preferred_flow_symbols,
            )
            files = self._build_files(project, store, selected_paths, roles, file_scores, file_reasons, symbols)
            relations = self._relations(
                store, selected_paths,
                flow_symbols=flow_symbols if analysis.flow_requested else None,
                terminal_edges=terminal_edges if analysis.flow_requested else None,
            )
            evidence, evidence_summary = self._build_evidence(
                project,
                store,
                analysis,
                files,
                symbols,
                relations,
                flow_symbols,
                terminal_edges,
                flow_unresolved,
            )
            available = sum(store.text_file_sizes().values())
        finally:
            store.close()

        selected_chars = sum(len(fragment.content) for item in files for fragment in item.fragments)
        selected_lines = sum(
            max(0, fragment.line_end - fragment.line_start + 1) for item in files for fragment in item.fragments
        )
        reduction = 0.0 if available <= 0 else max(0.0, 1.0 - (selected_chars / available))
        stats = ContextStatistics(
            candidate_files=len(file_scores),
            candidate_symbols=len(symbol_hits),
            selected_files=len(files),
            selected_symbols=len(symbols),
            selected_lines=selected_lines,
            selected_chars=selected_chars,
            available_chars=available,
            reduction_ratio=reduction,
            estimated_tokens=max(1, selected_chars // 4) if selected_chars else 0,
            graph_depth=graph_depth,
            search_seconds=search_seconds,
            total_seconds=time.perf_counter() - started,
        )
        return ContextBundle(
            project_id=project.id,
            project_name=project.name,
            task=task,
            analysis=analysis,
            files=files,
            symbols=symbols,
            relations=relations,
            statistics=stats,
            limitations=list(_LIMITATIONS),
            metadata={
                "max_files": self.config.max_files,
                "max_depth": self.config.max_depth,
                "call_depth": self.config.call_depth,
                "flow_call_depth": self.config.flow_call_depth,
                "directed_expansion_depth": self.config.directed_expansion_depth,
                "directed_expansion_max_symbols": self.config.directed_expansion_max_symbols,
                "causal_expansion_depth": self.config.causal_expansion_depth,
                "causal_expansion_max_symbols": self.config.causal_expansion_max_symbols,
                "flow_requested": analysis.flow_requested,
                "auto_flow": analysis.auto_flow,
                "action_terms": list(analysis.action_terms),
                "subject_terms": list(analysis.subject_terms),
                "flow_only": analysis.flow_only,
                "flow_start_candidates": list(analysis.flow_start_candidates),
                "flow_target_candidates": list(analysis.flow_target_candidates),
                "exclude_terms": list(analysis.exclude_terms),
                "research_intent": analysis.research_intent,
                "research_strategy": analysis.research_strategy,
                "intent_confidence": analysis.intent_confidence,
                "intent_signals": list(analysis.intent_signals),
                "flow_unresolved": list(flow_unresolved),
                "flow_path": list(actual_flow_path),
                "flow_required_symbols": [symbol.qualified_name for symbol in flow_required_symbols.values()],
                "terminal_edges": [list(item) for item in terminal_edges],
                "engine": "deterministic-v14-research-intent-object-action-directed-flow",
                "ai_handoff_protocol": "aidycai-ai-handoff-v1",
            },
            evidence=evidence,
            evidence_summary=evidence_summary,
        )

    def _collect(
        self, store: SqliteIndexStore, analysis: TaskAnalysis
    ) -> tuple[dict[str, float], dict[str, list[str]], dict[str, SymbolRecord]]:
        weights = self.config.weights
        file_scores: dict[str, float] = {}
        file_reasons: dict[str, list[str]] = {}
        symbol_hits: dict[str, SymbolRecord] = {}
        terms = [item.lower() for item in analysis.keywords + analysis.related_terms + analysis.symbol_candidates]

        for name in analysis.symbol_candidates:
            for symbol in store.find_symbols_named(name):
                symbol_hits[symbol.qualified_name] = symbol
                if symbol.qualified_name.lower() == name.lower():
                    add_signal(file_scores, file_reasons, symbol.rel_path, SIGNAL_EXACT_QUALIFIED, weights)
                else:
                    add_signal(file_scores, file_reasons, symbol.rel_path, SIGNAL_EXACT_SYMBOL, weights)

        # File candidates come from explicit filenames in the user's query.
        # Do not promote a generic token such as the extension ``html`` to an
        # exact filename match: that makes ``html.py`` outrank the requested
        # ``sales.html``. Keywords may still contribute a weaker path signal.
        for filename_query in analysis.file_candidates:
            query_name = Path(filename_query).name.lower()
            query_stem = Path(filename_query).stem.lower()
            # Search by basename so ``sales.html`` can also discover
            # ``sales.css`` / ``sales.js`` without treating ``html`` as a
            # standalone filename.
            for record in store.find_files_named(query_stem or filename_query):
                filename = Path(record.rel_path).name.lower()
                record_stem = Path(record.rel_path).stem.lower()
                if filename == query_name:
                    add_signal(file_scores, file_reasons, record.rel_path, SIGNAL_EXACT_FILENAME, weights)
                elif query_stem and record_stem == query_stem:
                    # Same basename with another extension is highly relevant
                    # for questions such as ``sales.html`` → ``sales.css``.
                    add_signal(file_scores, file_reasons, record.rel_path, SIGNAL_EXACT_BASENAME, weights)
                elif query_stem and query_stem in record.rel_path.lower():
                    add_signal(file_scores, file_reasons, record.rel_path, SIGNAL_PATH, weights)

        # Intent-specific evidence is deliberately local to this task. It
        # strengthens the investigation vocabulary without changing the
        # global ranking weights.
        if analysis.research_intent in {"FRONTEND_RESPONSIVE", "FRONTEND_LAYOUT"}:
            requested_stems = {
                Path(item).stem.lower()
                for item in analysis.file_candidates
                if Path(item).suffix.lower() in {".html", ".htm", ".css", ".scss", ".js", ".ts"}
            }
            for rel_path in store.list_files():
                lowered = rel_path.lower()
                suffix = Path(rel_path).suffix.lower()
                stem = Path(rel_path).stem.lower()
                if requested_stems and stem in requested_stems:
                    add_signal(file_scores, file_reasons, rel_path, SIGNAL_EXACT_BASENAME, weights, scale=1.35)
                if suffix in {".html", ".htm", ".css", ".scss", ".js", ".ts"} and any(
                    term.lower() in lowered for term in ("layout", "base", "template", "sales")
                ):
                    add_signal(file_scores, file_reasons, rel_path, SIGNAL_PATH, weights, scale=0.8)

        for stem in [*analysis.keywords, *analysis.related_terms]:
            stem_l = stem.lower()
            # Extension tokens are not useful standalone path candidates.
            if stem_l in {"html", "htm", "css", "scss", "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "md", "sql", "json"}:
                continue
            for record in store.find_files_named(stem):
                if stem_l in record.rel_path.lower():
                    add_signal(file_scores, file_reasons, record.rel_path, SIGNAL_PATH, weights)

        for query in analysis.search_queries:
            for hit in store.search(query, limit=self.config.fts_limit):
                if hit.kind == "symbol" and hit.qualified_name:
                    add_signal(file_scores, file_reasons, hit.rel_path, SIGNAL_SYMBOL_FTS, weights)
                    if hit.qualified_name not in symbol_hits:
                        symbol_hits[hit.qualified_name] = SymbolRecord(
                            id=0,
                            file_id=0,
                            type=hit.symbol_type or "symbol",
                            name=hit.symbol_name or hit.qualified_name,
                            qualified_name=hit.qualified_name,
                            line_start=hit.line_start,
                            line_end=hit.line_end,
                            metadata={},
                            rel_path=hit.rel_path,
                        )
                else:
                    add_signal(file_scores, file_reasons, hit.rel_path, SIGNAL_FILE_FTS, weights)

        for rel_path in list(store.list_files().keys()):
            lowered = rel_path.lower()
            if any(term and term in lowered for term in terms if len(term) > 3):
                add_signal(file_scores, file_reasons, rel_path, SIGNAL_PATH, weights)

        self._apply_exclusions(file_scores, file_reasons, analysis.exclude_terms)
        return file_scores, file_reasons, symbol_hits

    def _apply_exclusions(
        self, file_scores: dict[str, float], file_reasons: dict[str, list[str]], exclude_terms: list[str]
    ) -> None:
        """Apply hard file/module exclusions without substring collisions.

        A bare exclusion such as ``Retiros`` means the module/file stem
        ``Retiros.py``; it must not exclude ``retirosefectivo.py``. A filename
        with an extension is matched by exact filename. Explicit paths are
        matched by normalized relative path. Substring matching is deliberately
        forbidden because it makes ``Retiros.py`` collide with
        ``retirosefectivo.py``.
        """
        if not exclude_terms:
            return

        def matches(rel_path: str, raw_term: str) -> bool:
            term = raw_term.strip().replace("\\", "/").strip("/").lower()
            if not term:
                return False
            path = rel_path.replace("\\", "/").strip("/").lower()
            name = Path(path).name
            stem = Path(path).stem
            if "/" in term:
                return path == term
            if term.endswith(".py") or "." in term:
                return name == term
            return stem == term

        for path in list(file_scores):
            if any(matches(path, term) for term in exclude_terms):
                file_scores.pop(path, None)
                file_reasons.pop(path, None)

    def _research_strategy_policy(
        self,
        project: Project,
        store: SqliteIndexStore,
        analysis: TaskAnalysis,
        flow_paths: list[str],
        file_reasons: dict[str, list[str]],
    ) -> ResearchStrategyPolicy:
        """Return task-local selection constraints for the detected strategy.

        File location and presentation questions only need files that are
        directly connected by their names or explicit template references.
        A normal directed backend flow keeps its resolved path first and may
        retain only independently strong evidence beside it.
        """
        candidates = set(store.list_files())
        intent = analysis.research_intent

        if intent == "FILE_LOCATION":
            related = self._presentation_related_paths(project, candidates, analysis.file_candidates)
            return ResearchStrategyPolicy(allowed_paths=frozenset(related))

        if intent in {"FRONTEND_RESPONSIVE", "FRONTEND_LAYOUT"}:
            related = self._presentation_related_paths(project, candidates, analysis.file_candidates)
            if not related:
                # If the question does not name a view, frontend evidence can
                # still be investigated, but Python/backend files stay out.
                related = {
                    path for path in candidates
                    if Path(path).suffix.lower() in _PRESENTATION_SUFFIXES
                }
            return ResearchStrategyPolicy(allowed_paths=frozenset(related))

        if intent == "BACKEND_FLOW" and flow_paths and not analysis.flow_only:
            direct_signals = {
                SIGNAL_EXACT_SYMBOL,
                SIGNAL_EXACT_QUALIFIED,
                SIGNAL_EXACT_FILENAME,
                SIGNAL_EXACT_BASENAME,
            }
            direct_paths = {
                path
                for path, reasons in file_reasons.items()
                if direct_signals.intersection(reasons)
            }
            return ResearchStrategyPolicy(
                allowed_paths=frozenset(set(flow_paths) | direct_paths),
                preferred_paths=tuple(flow_paths),
            )

        return ResearchStrategyPolicy()

    def _apply_strategy_policy(
        self,
        file_scores: dict[str, float],
        file_reasons: dict[str, list[str]],
        policy: ResearchStrategyPolicy,
    ) -> None:
        """Apply an allow-list without changing candidate scores or weights."""
        if policy.allowed_paths is None:
            return
        for path in list(file_scores):
            if path not in policy.allowed_paths:
                file_scores.pop(path, None)
                file_reasons.pop(path, None)

    def _presentation_related_paths(
        self,
        project: Project,
        candidates: set[str],
        file_candidates: list[str],
    ) -> set[str]:
        """Find presentation files related by basename or explicit references.

        This is not an HTML/CSS parser. It only follows literal `extends`,
        `include`, `href`, and `src` values already present in project files.
        """
        requested = [Path(item) for item in file_candidates]
        requested_names = {item.name.lower() for item in requested}
        requested_stems = {item.stem.lower() for item in requested if item.stem}
        related = {
            path for path in candidates
            if Path(path).suffix.lower() in _PRESENTATION_SUFFIXES
            and (
                Path(path).name.lower() in requested_names
                or Path(path).stem.lower() in requested_stems
            )
        }
        if not related:
            return set()

        queue = deque(path for path in related if Path(path).suffix.lower() in {".html", ".htm"})
        inspected: set[str] = set()
        while queue:
            path = queue.popleft()
            if path in inspected:
                continue
            inspected.add(path)
            try:
                text = decode_text((project.path / path).read_bytes())
            except OSError:
                continue
            for match in _TEMPLATE_REFERENCES.finditer(text):
                raw_reference = next((value for value in match.groups() if value), "")
                target = self._resolve_presentation_reference(path, raw_reference, candidates)
                if target is None or target in related:
                    continue
                related.add(target)
                if Path(target).suffix.lower() in {".html", ".htm"}:
                    queue.append(target)
        return related

    @staticmethod
    def _resolve_presentation_reference(source: str, raw_reference: str, candidates: set[str]) -> str | None:
        reference = raw_reference.split("?", 1)[0].split("#", 1)[0].replace("\\", "/").strip()
        if not reference:
            return None
        normalized = reference.lstrip("/")
        relative = (Path(source).parent / normalized).as_posix()
        exact = [path for path in candidates if path == normalized or path == relative]
        if len(exact) == 1:
            return exact[0]
        by_name = [path for path in candidates if Path(path).name.lower() == Path(normalized).name.lower()]
        return by_name[0] if len(by_name) == 1 else None

    def _build_evidence(
        self,
        project: Project,
        store: SqliteIndexStore,
        analysis: TaskAnalysis,
        files: list[SelectedFile],
        symbols: list[SelectedSymbol],
        relations: list[ContextRelation],
        flow_symbols: dict[str, SymbolRecord],
        terminal_edges: list[tuple[str, str]],
        flow_unresolved: list[str],
    ) -> tuple[list[EvidenceRecord], ContextEvidenceSummary]:
        """Describe demonstrated evidence for the selected context only.

        This translates existing selection reasons, resolved relations and flow
        metadata into stable evidence labels. It deliberately does not create
        records for candidates that were discarded before the ContextBundle.
        """
        selected_paths = {item.path for item in files}
        records: list[EvidenceRecord] = []
        seen: set[tuple[str, str | None, str, str]] = set()

        def add(
            source: str,
            kind: str,
            confidence: str,
            reason: str,
            *,
            target: str | None = None,
            demonstrated: bool = True,
        ) -> None:
            if source not in selected_paths:
                return
            key = (source, target, kind, reason)
            if key in seen:
                return
            seen.add(key)
            records.append(EvidenceRecord(source, target, kind, confidence, reason, demonstrated))

        for item in files:
            reasons = set(item.reasons)
            if SIGNAL_EXACT_FILENAME in reasons:
                add(item.path, "DIRECT", "HIGH", "filename explicitly requested")
            if SIGNAL_EXACT_BASENAME in reasons:
                add(item.path, "DIRECT", "HIGH", "basename matches the requested file")
            if SIGNAL_EXACT_SYMBOL in reasons or SIGNAL_EXACT_QUALIFIED in reasons:
                add(item.path, "SYMBOL", "HIGH", "indexed symbol directly matches the task")
            if SIGNAL_SYMBOL_FTS in reasons:
                add(item.path, "SYMBOL", "MEDIUM", "indexed symbol is related to the task")
            if SIGNAL_FILE_FTS in reasons or SIGNAL_PATH in reasons:
                add(item.path, "TEXTUAL", "LOW", "path or file content matches task terms")

        for symbol in symbols:
            if "matched task term" in symbol.reasons:
                add(symbol.rel_path, "SYMBOL", "MEDIUM", f"selected symbol matches the task: {symbol.qualified_name}")
            if "flow path symbol" in symbol.reasons:
                add(symbol.rel_path, "FLOW", "HIGH", f"symbol belongs to the resolved flow: {symbol.qualified_name}")

        for source, target, kind in self._presentation_reference_relations(project, selected_paths):
            add(source, "REFERENCE", "HIGH", kind, target=target)

        for relation in relations:
            if relation.kind == "import":
                add(relation.source, "IMPORT", "MEDIUM", relation.reason, target=relation.target)

        symbol_paths = {item.qualified_name: item.rel_path for item in symbols}
        symbol_paths.update({item.qualified_name: item.rel_path for item in flow_symbols.values()})
        for symbol in flow_symbols.values():
            add(symbol.rel_path, "FLOW", "HIGH", f"symbol belongs to the resolved flow: {symbol.qualified_name}")
        flow_order = list(flow_symbols.values())
        for left, right in zip(flow_order, flow_order[1:]):
            left_ops = left.metadata.get("sql_operations", []) if isinstance(left.metadata, dict) else []
            read_resources = [
                str(op.get("resource")) for op in left_ops
                if isinstance(op, dict) and str(op.get("kind", "")).upper() == "SELECT" and op.get("resource")
            ]
            right_ops = right.metadata.get("sql_operations", []) if isinstance(right.metadata, dict) else []
            write_resources = [
                str(op.get("resource")) for op in right_ops
                if isinstance(op, dict) and str(op.get("kind", "")).upper() in {"INSERT", "UPDATE"} and op.get("resource")
            ]
            shared = sorted(set(read_resources) & set(write_resources))
            for resource in shared:
                add(
                    left.rel_path,
                    "FLOW",
                    "HIGH",
                    f"indexed SQL read of {resource} resolved to unique indexed writer {right.qualified_name}",
                    target=right.rel_path,
                )
                params = right.metadata.get("params", []) if isinstance(right.metadata, dict) else []
                if any(str(item).lower() == "turno" for item in params):
                    add(
                        right.rel_path,
                        "FLOW",
                        "HIGH",
                        f"indexed SQL writer {right.qualified_name} receives parameter turno for {resource}",
                    )

        for source_symbol, terminal in terminal_edges:
            source_path = symbol_paths.get(source_symbol)
            if source_path:
                add(source_path, "FLOW_TERMINAL", "HIGH", f"resolved flow reaches terminal: {terminal}", target=terminal)
        for unresolved in flow_unresolved:
            source_symbol, target = _unresolved_parts(unresolved)
            source_path = symbol_paths.get(source_symbol)
            if source_path:
                add(
                    source_path,
                    "UNRESOLVED",
                    "UNRESOLVED",
                    "static relation could not be resolved",
                    target=target,
                    demonstrated=False,
                )

        summary = ContextEvidenceSummary(
            strong_evidence=sum(item.confidence == "HIGH" for item in records),
            medium_evidence=sum(item.confidence == "MEDIUM" for item in records),
            weak_evidence=sum(item.confidence == "LOW" for item in records),
            unresolved=sum(item.kind == "UNRESOLVED" for item in records),
        )
        return records, summary

    def _presentation_reference_relations(
        self, project: Project, selected_paths: set[str]
    ) -> list[tuple[str, str, str]]:
        """Return literal presentation references whose endpoints are selected."""
        result: list[tuple[str, str, str]] = []
        for source in selected_paths:
            if Path(source).suffix.lower() not in {".html", ".htm"}:
                continue
            try:
                text = decode_text((project.path / source).read_bytes())
            except OSError:
                continue
            for match in _TEMPLATE_REFERENCES.finditer(text):
                raw_reference = next((value for value in match.groups() if value), "")
                target = self._resolve_presentation_reference(source, raw_reference, selected_paths)
                if target is None:
                    continue
                lowered = raw_reference.lower()
                if "stylesheet" in text[max(0, match.start() - 80):match.end() + 80].lower() or Path(target).suffix.lower() in {".css", ".scss"}:
                    reason = "template explicitly references stylesheet"
                elif "extends" in match.group(0).lower():
                    reason = "template explicitly extends parent layout"
                elif "include" in match.group(0).lower():
                    reason = "template explicitly includes related template"
                else:
                    reason = "template explicitly references presentation asset"
                result.append((source, target, reason))
        return result

    def _select_flow_files(self, flow_paths: list[str]) -> tuple[list[str], dict[str, str]]:
        ordered: list[str] = []
        for path in flow_paths:
            if path not in ordered:
                ordered.append(path)
        if self.config.max_files > 0:
            ordered = ordered[: self.config.max_files]
        return ordered, {path: ROLE_PRIMARY for path in ordered}

    @staticmethod
    def _path_excluded(rel_path: str, exclude_terms: list[str]) -> bool:
        """Return whether a path matches an explicit file/module exclusion.

        Matching is exact by default: ``Retiros`` matches ``Retiros.py`` but
        never ``retirosefectivo.py``. Relative paths remain exact as well.
        """
        path = rel_path.replace("\\", "/").strip("/").lower()
        name = Path(path).name
        stem = Path(path).stem
        for raw_term in exclude_terms:
            term = raw_term.strip().replace("\\", "/").strip("/").lower()
            if not term:
                continue
            if "/" in term:
                if path == term:
                    return True
            elif term.endswith(".py") or "." in term:
                if name == term:
                    return True
            elif stem == term:
                return True
        return False

    def _infer_auto_flow_start(
        self,
        store: SqliteIndexStore,
        analysis: TaskAnalysis,
        file_scores: dict[str, float],
        symbol_hits: dict[str, SymbolRecord],
    ) -> None:
        """Infer a useful flow root for a normal behavioral question.

        This is intentionally conservative: it only activates when the user
        describes a problem with an action (for example, ``no se imprime``).
        The root is chosen from indexed functions rather than inventing a
        symbol name. Explicit flow requests still take precedence.
        """
        if not analysis.auto_flow or analysis.flow_start_candidates:
            return

        functions: list[SymbolRecord] = []
        for rel_path in store.list_files():
            functions.extend(
                item for item in store.symbols_for_path(rel_path)
                if item.type in {"function", "method"}
                and not self._path_excluded(item.rel_path, analysis.exclude_terms)
            )
        if not functions:
            return

        # The object of the question is a hard semantic anchor for automatic
        # flow discovery.  Generic action words such as ``enviar`` or helper
        # vocabulary such as ``request`` must not outrank a function/file that
        # actually mentions the requested object (for example ``retiro``).
        object_terms = {
            term.lower()
            for term in (analysis.subject_terms or analysis.keywords + analysis.related_terms)
            if len(term) >= 4
        }
        action_aliases = {
            "print": ("imprimir", "imprime", "impres", "print", "printer", "ticket", "writeprinter"),
            "save": ("guardar", "guarda", "guardan", "save", "write", "backup", "dump", "almacena", "almacenar", "escribe"),
            "load": ("cargar", "carga", "cargan", "load", "leer", "read", "fetch", "obtiene", "obtener", "consultar", "consulta", "select"),
            "send": ("enviar", "envia", "envía", "envían", "send", "post", "request", "upload"),
            "show": ("mostrar", "muestra", "muestran", "aparece", "aparecen", "display", "visualiza", "ver", "obtener", "obtiene", "consultar", "consulta", "render", "template"),
        }
        aliases = action_aliases.get(analysis.action_terms[0], ()) if analysis.action_terms else ()
        # Build a light incoming-call index so an action root is preferred over
        # its lower-level helper. For example, ``enviar_efectivo_consignado``
        # should beat ``enviar_al_servidor`` when the former calls the latter.
        called_by: dict[str, int] = defaultdict(int)
        for source in functions:
            calls = source.metadata.get("calls", []) if isinstance(source.metadata, dict) else []
            for call in calls:
                short = call.rsplit(".", 1)[-1].lower() if isinstance(call, str) else ""
                for candidate in functions:
                    if candidate.name.lower() == short:
                        called_by[candidate.qualified_name.lower()] += 1

        ranked: list[tuple[float, SymbolRecord]] = []
        for symbol in functions:
            name = symbol.name.lower()
            qualified = symbol.qualified_name.lower()
            score = file_scores.get(symbol.rel_path, 0.0) * 0.35
            action_hit = bool(aliases and any(alias in name or alias in qualified for alias in aliases))
            if action_hit:
                score += 8.0
            object_hits = sum(1 for term in object_terms if term in name or term in qualified)
            score += min(14.0, object_hits * 5.0)
            if object_hits:
                # Matching the requested object in the symbol is substantially
                # stronger than matching the action alone. This prevents
                # EnviarCompras/EnviarNotas from winning a question about
                # sending retiros merely because they contain ``enviar``.
                score += 4.0
            calls = symbol.metadata.get("calls", []) if isinstance(symbol.metadata, dict) else []
            called_action = False
            if calls and aliases:
                called_action = any(
                    isinstance(call, str) and any(alias in call.lower() for alias in aliases)
                    for call in calls
                )
            if called_action:
                score += 2.5
            # Auto-flow roots must represent the requested action (or call an
            # action helper). Object-only classes such as ``Retiros`` are not
            # valid roots even when their name matches the requested object.
            if not action_hit and not called_action:
                continue
            # A candidate that is itself a helper called by another candidate
            # is less likely to be the user's entry point. Prefer a root when
            # the root also matches the requested action/object.
            incoming = called_by.get(qualified, 0)
            if action_hit and incoming == 0:
                score += 3.0
            elif action_hit and incoming > 0:
                score -= min(2.0, incoming * 0.5)
            if calls:
                score += 1.0
            if symbol.line_start is not None:
                score += 0.1
            ranked.append((score, symbol))

        ranked.sort(key=lambda pair: (pair[0], file_scores.get(pair[1].rel_path, 0.0)), reverse=True)
        if not ranked or ranked[0][0] <= 0:
            return
        best_score, best = ranked[0]
        # Do not force a graph if the best candidate is only a generic textual
        # hit. A small margin keeps ambiguous open questions on normal ranking.
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score < 4.0 or (second_score > 0 and best_score < second_score + 1.0):
            return

        analysis.flow_start_candidates[:] = [best.qualified_name]
        analysis.flow_spec = FlowSpec(
            strict=analysis.flow_only,
            direction=analysis.flow_direction,
            start_symbols=(best.qualified_name,),
            target_symbols=tuple(analysis.flow_target_candidates),
            terminal_terms=_terminal_terms_for_actions(analysis.action_terms) if analysis.flow_requested else (),
            excluded_terms=tuple(analysis.exclude_terms),
        )
        symbol_hits[best.qualified_name] = best

    def _resolve_flow(
        self, store: SqliteIndexStore, analysis: TaskAnalysis
    ) -> tuple[
        list[str],
        dict[str, SymbolRecord],
        dict[str, SymbolRecord],
        int,
        list[str],
        list[tuple[str, str]],
        list[str],
    ]:
        """Resolve a directed execution path from the requested start symbol.

        Strict flow mode is deliberately path-oriented, not ranking-oriented:
        explicit milestones must be reachable from the previous milestone and
        terminal requests stop at the first detected printer/byte-output sink.
        Unrelated callers, import neighbors and other functions in the same
        file never become flow roots.
        """
        all_symbols: list[SymbolRecord] = []
        for rel_path in store.list_files():
            all_symbols.extend(store.symbols_for_path(rel_path))
        functions = [item for item in all_symbols if item.type in {"function", "method"}]
        classes = [item for item in all_symbols if item.type == "class"]
        by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
        by_qualified: dict[str, SymbolRecord] = {}
        for symbol in functions:
            by_name[symbol.name.lower()].append(symbol)
            by_qualified[symbol.qualified_name.lower()] = symbol
        classes_by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
        for symbol in classes:
            classes_by_name[symbol.name.lower()].append(symbol)

        # Import bindings let the call resolver follow real Python call sites
        # such as ``import imprimir as imp; imp.imprimir_ticket(...)`` and
        # ``from imprimir import imprimir_ticket``. The previous resolver only
        # compared the short call name globally, which can miss aliases and
        # attribute-based calls or choose an unrelated same-named helper.
        file_records = store.list_files()
        file_by_id = {record.id: record.rel_path for record in file_records.values()}
        imports_by_file: dict[str, list[object]] = defaultdict(list)
        for item in store.list_imports():
            rel_path = file_by_id.get(item.file_id)
            if rel_path:
                imports_by_file[rel_path].append(item)

        def module_matches(rel_path: str, module: str) -> bool:
            normalized = module.replace("\\", "/").strip("/").lower()
            path = rel_path.replace("\\", "/").strip("/").lower()
            stem = Path(path).with_suffix("").as_posix()
            dotted = stem.replace("/", ".")
            return dotted == normalized or dotted.endswith("." + normalized) or Path(path).stem == normalized.rsplit(".", 1)[-1]

        def imported_candidates(source: SymbolRecord, call: str) -> list[SymbolRecord]:
            parts = call.split(".")
            if not parts:
                return []
            bindings = imports_by_file.get(source.rel_path, [])
            results: list[SymbolRecord] = []
            for item in bindings:
                module = getattr(item, "module", "") or ""
                names = list(getattr(item, "names", []) or [])
                alias = getattr(item, "alias", None)
                import_type = getattr(item, "import_type", "")
                resolved_path = getattr(item, "resolved_rel_path", None)

                if import_type == "import":
                    binding = alias or module.rsplit(".", 1)[-1]
                    if parts[0].lower() != binding.lower():
                        continue
                    wanted = parts[1:]
                    if not wanted:
                        continue
                    target_name = wanted[-1].lower()
                    for symbol in functions:
                        if symbol.name.lower() == target_name and (
                            (resolved_path and symbol.rel_path == resolved_path)
                            or module_matches(symbol.rel_path, module)
                        ):
                            results.append(symbol)

                elif import_type == "from":
                    for imported in names:
                        binding = alias or imported
                        if parts[0].lower() != binding.lower():
                            continue
                        # from module import function; call is simply function(...)
                        if len(parts) == 1:
                            target_name = imported.lower()
                        else:
                            # from module import Class as Alias; Alias.method(...)
                            target_name = parts[-1].lower()
                        for symbol in functions:
                            if symbol.name.lower() != target_name:
                                continue
                            if resolved_path and symbol.rel_path == resolved_path:
                                results.append(symbol)
                            elif module_matches(symbol.rel_path, module):
                                results.append(symbol)
            unique: dict[str, SymbolRecord] = {item.qualified_name.lower(): item for item in results}
            return list(unique.values())

        def resolve(name: str, source: SymbolRecord | None = None) -> list[SymbolRecord]:
            exact = by_qualified.get(name.lower())
            if exact and not self._path_excluded(exact.rel_path, analysis.exclude_terms):
                return [exact]
            exact_classes = [
                item for item in classes_by_name.get(name.rsplit(".", 1)[-1].lower(), [])
                if item.qualified_name.lower() == name.lower()
                and not self._path_excluded(item.rel_path, analysis.exclude_terms)
            ]
            if len(exact_classes) == 1:
                return exact_classes

            if source:
                imported = imported_candidates(source, name)
                if imported:
                    return imported

            short = name.rsplit(".", 1)[-1].lower()
            candidates = by_name.get(short, [])

            # ``self.foo()`` is represented by the AST as ``self.foo``. Resolve
            # that binding inside the caller's class before falling back to the
            # global short-name search. This is especially important when the
            # project contains several classes with a method named ``foo``.
            if source and name.lower().startswith("self."):
                owner = source.metadata.get("class") if isinstance(source.metadata, dict) else None
                if owner:
                    class_candidates = [
                        item for item in candidates
                        if item.rel_path == source.rel_path
                        and item.qualified_name.lower() == f"{str(owner).lower()}.{short}"
                    ]
                    if len(class_candidates) == 1:
                        return class_candidates

            # A class-qualified call in the same file (``Class.foo()``) can be
            # resolved without guessing among unrelated classes elsewhere.
            if source and "." in name and not name.lower().startswith("self."):
                qualifier = name.rsplit(".", 1)[0].lower()
                local_qualified = [
                    item for item in candidates
                    if item.rel_path == source.rel_path
                    and item.qualified_name.lower() == f"{qualifier}.{short}"
                ]
                if len(local_qualified) == 1:
                    return local_qualified

            # PythonAstAnalyzer stores function qnames relative to the module
            # (``Class.method`` / ``function``), so a user-supplied
            # ``module.function`` cannot be looked up literally. Prefer a
            # candidate whose file stem matches the module qualifier. This also
            # prevents an identically named function in Retiros.py from winning
            # over retirosefectivo.py merely because the short name is shared.
            if "." in name:
                module_hint = name.rsplit(".", 1)[0].lower().replace("\\", "/").strip("/")
                module_candidates = [
                    item
                    for item in candidates
                    if Path(item.rel_path).stem.lower() == module_hint
                    or Path(item.rel_path).with_suffix("").as_posix().lower() == module_hint
                ]
                module_candidates = [
                    item for item in module_candidates
                    if not self._path_excluded(item.rel_path, analysis.exclude_terms)
                ]
                if len(module_candidates) == 1:
                    return module_candidates
                if module_candidates:
                    candidates = module_candidates
                else:
                    # Be tolerant of a small module-name typo in a qualified
                    # anchor (for example ``retirarefectivo`` vs
                    # ``retirosefectivo``), but only when there is one clearly
                    # best file match. This is anchor resolution, not broad
                    # search expansion.
                    module_scores = []
                    for item in candidates:
                        stem = Path(item.rel_path).stem.lower()
                        ratio = difflib.SequenceMatcher(None, module_hint, stem).ratio()
                        module_scores.append((ratio, item))
                    module_scores.sort(key=lambda pair: pair[0], reverse=True)
                    if module_scores and module_scores[0][0] >= 0.80:
                        best = module_scores[0][0]
                        tied = [item for score, item in module_scores if score == best]
                        tied = [
                            item for item in tied
                            if not self._path_excluded(item.rel_path, analysis.exclude_terms)
                        ]
                        if len(tied) == 1:
                            return tied

            candidates = [
                item for item in candidates
                if not self._path_excluded(item.rel_path, analysis.exclude_terms)
            ]
            if source:
                same_file = [item for item in candidates if item.rel_path == source.rel_path]
                if len(same_file) == 1:
                    return same_file
            if len(candidates) == 1:
                return candidates

            # A constructor call such as ``VisualizacionValores()`` is a
            # statically demonstrable relation only when the indexed class
            # name has exactly one candidate.  Classes are intentionally not
            # folded into normal function-name matching: doing so would make
            # a function/class collision ambiguous rather than guessed.
            class_candidates = [
                item for item in classes_by_name.get(short, [])
                if not self._path_excluded(item.rel_path, analysis.exclude_terms)
            ]
            return class_candidates if len(class_candidates) == 1 else []

        def sql_read_resources(source: SymbolRecord) -> list[str]:
            operations = source.metadata.get("sql_operations", []) if isinstance(source.metadata, dict) else []
            return [
                str(operation.get("resource"))
                for operation in operations
                if isinstance(operation, dict)
                and str(operation.get("kind", "")).upper() == "SELECT"
                and operation.get("resource")
            ]

        def sql_causal_successors(source: SymbolRecord, unresolved: list[str] | None = None) -> list[SymbolRecord]:
            resources = list(dict.fromkeys(sql_read_resources(source)))
            if not resources:
                return []
            writers: dict[str, SymbolRecord] = {}
            ambiguous: list[str] = []
            for resource in resources:
                candidates = store.sql_writers(resource)
                if len(candidates) == 1:
                    writer = candidates[0]
                    writers[writer.qualified_name.lower()] = writer
                elif len(candidates) == 0:
                    if unresolved is not None:
                        unresolved.append(
                            f"{source.qualified_name} → SQL {resource}: no hay escritor indexado resoluble"
                        )
                else:
                    ambiguous.append(f"{resource} ({', '.join(item.qualified_name for item in candidates)})")
            if ambiguous:
                if unresolved is not None:
                    unresolved.append(
                        f"{source.qualified_name} → SQL: escritores ambiguos: {'; '.join(ambiguous)}"
                    )
                return []
            return [writers[key] for key in sorted(writers)]

        def sql_origin_successors(source: SymbolRecord, unresolved: list[str] | None = None) -> list[SymbolRecord]:
            params = source.metadata.get("params", []) if isinstance(source.metadata, dict) else []
            operations = source.metadata.get("sql_operations", []) if isinstance(source.metadata, dict) else []
            columns = {
                str(item).lower()
                for operation in operations if isinstance(operation, dict)
                for item in operation.get("columns", []) if isinstance(item, str)
            }
            if "turno" not in {str(item).lower() for item in params} and "turno" not in columns:
                return []
            callers = unique_callers(source)
            if len(callers) == 1:
                return callers
            if len(callers) > 1 and unresolved is not None:
                unresolved.append(
                    f"{source.qualified_name} → parámetro turno: múltiples llamadores candidatos"
                )
            return []

        def unique_callers(target: SymbolRecord) -> list[SymbolRecord]:
            candidates: list[SymbolRecord] = []
            for candidate in functions:
                if candidate.qualified_name.lower() == target.qualified_name.lower():
                    continue
                calls = candidate.metadata.get("calls", []) if isinstance(candidate.metadata, dict) else []
                for call in calls:
                    if not isinstance(call, str):
                        continue
                    resolved = resolve(call, candidate)
                    if any(item.qualified_name.lower() == target.qualified_name.lower() for item in resolved):
                        candidates.append(candidate)
                        break
            unique: dict[str, SymbolRecord] = {}
            for candidate in candidates:
                unique.setdefault(candidate.qualified_name.lower(), candidate)
            return list(unique.values())

        def successors(source: SymbolRecord, unresolved: list[str] | None = None) -> list[SymbolRecord]:
            if source.type == "class":
                constructors = [
                    item for item in by_name.get("__init__", [])
                    if item.rel_path == source.rel_path
                    and item.qualified_name.lower() == f"{source.qualified_name.lower()}.__init__"
                ]
                return constructors if len(constructors) == 1 else []
            calls = source.metadata.get("calls", []) if isinstance(source.metadata, dict) else []
            result: list[SymbolRecord] = []
            for call in calls:
                if not isinstance(call, str) or not call:
                    continue
                candidates = resolve(call, source)
                if not candidates:
                    if unresolved is not None and not _looks_terminal_for_action(call, analysis.action_terms):
                        unresolved.append(f"{source.qualified_name} → {call} (no resuelta)")
                    continue
                for target in candidates[:1]:
                    if target.qualified_name.lower() == source.qualified_name.lower():
                        continue
                    if self._path_excluded(target.rel_path, analysis.exclude_terms):
                        continue
                    result.append(target)
            if result:
                unique: dict[str, SymbolRecord] = {}
                for target in result:
                    unique.setdefault(target.qualified_name.lower(), target)
                return list(unique.values())
            origin = sql_origin_successors(source, unresolved)
            if origin:
                return origin
            return sql_causal_successors(source, unresolved)

        starts: list[SymbolRecord] = []
        for candidate in analysis.flow_start_candidates:
            starts.extend(resolve(candidate))
        if not starts:
            return [], {}, {}, 0, ["No se pudo resolver el símbolo inicial del flujo."], [], []
        start = starts[0]
        if self._path_excluded(start.rel_path, analysis.exclude_terms):
            return [], {}, {}, 0, [f"El símbolo inicial está en un archivo excluido: {start.rel_path}"], [], []

        target_records: list[SymbolRecord] = []
        required_not_path: dict[str, SymbolRecord] = {}
        unresolved: list[str] = []
        terminal_names = {"win32print", "writeprinter"}
        for candidate in analysis.flow_target_candidates:
            if candidate.rsplit(".", 1)[-1].lower() in terminal_names:
                continue
            resolved = resolve(candidate)
            if len(resolved) == 1:
                target_records.append(resolved[0])
            elif not resolved:
                unresolved.append(candidate)
            else:
                unresolved.append(f"{candidate} (ambiguo)")

        def shortest_path(source: SymbolRecord, wanted: SymbolRecord) -> list[SymbolRecord] | None:
            queue: deque[SymbolRecord] = deque([source])
            parent: dict[str, str | None] = {source.qualified_name.lower(): None}
            objects: dict[str, SymbolRecord] = {source.qualified_name.lower(): source}
            while queue:
                current = queue.popleft()
                if current.qualified_name.lower() == wanted.qualified_name.lower():
                    path: list[SymbolRecord] = []
                    key: str | None = current.qualified_name.lower()
                    while key is not None:
                        node = objects[key]
                        path.append(node)
                        key = parent[key]
                    path.reverse()
                    return path
                for nxt in successors(current, unresolved):
                    key = nxt.qualified_name.lower()
                    if key in parent:
                        continue
                    parent[key] = current.qualified_name.lower()
                    objects[key] = nxt
                    queue.append(nxt)
            return None

        def _unique_sql_read_branch(candidates: list[SymbolRecord]) -> SymbolRecord | None:
            """Choose a single local call branch that demonstrably reaches SQL.

            This is intentionally bounded and uses only indexed call/SQL metadata.
            It never searches files or FTS. If zero or multiple branches can reach
            an indexed SELECT, no branch is selected.
            """
            if len(candidates) <= 1:
                return candidates[0] if candidates else None

            max_depth = max(0, min(self.config.directed_expansion_depth, 8))
            max_symbols = max(0, min(self.config.directed_expansion_max_symbols, 32))
            if max_depth == 0 or max_symbols == 0:
                return None

            reaching: list[SymbolRecord] = []
            for candidate in candidates:
                queue: deque[tuple[SymbolRecord, int]] = deque([(candidate, 0)])
                seen = {candidate.qualified_name.lower()}
                inspected = 0
                found = False
                while queue and inspected < max_symbols:
                    current, depth = queue.popleft()
                    inspected += 1
                    if sql_read_resources(current):
                        found = True
                        break
                    if depth >= max_depth:
                        continue
                    for nxt in successors(current, None):
                        key = nxt.qualified_name.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        queue.append((nxt, depth + 1))
                if found:
                    reaching.append(candidate)

            return reaching[0] if len(reaching) == 1 else None

        def path_to_unique_end(source: SymbolRecord) -> list[SymbolRecord]:
            """Follow a deterministic outgoing chain for automatic behavioral flows.

            If a symbol has multiple outgoing calls, a branch may still be selected
            when exactly one indexed branch demonstrably reaches a SQL read. This
            extends V16 without turning the flow into a global search.
            """
            path: list[SymbolRecord] = [source]
            seen = {source.qualified_name.lower()}
            current = source
            max_steps = max(1, min(12, self.config.call_depth + 8))
            expansion_steps = 0
            expansion_symbols = 0
            causal_steps = 0
            causal_symbols = 0
            for _ in range(max_steps):
                successors_found = successors(current, unresolved)
                if len(successors_found) != 1:
                    if len(successors_found) > 1:
                        sql_branch = _unique_sql_read_branch(successors_found)
                        if sql_branch is not None:
                            nxt = sql_branch
                        else:
                            unresolved.append(
                                f"{current.qualified_name} tiene varias llamadas salientes; "
                                "ninguna o más de una rama alcanza una lectura SQL indexada"
                            )
                            break
                    else:
                        break
                else:
                    nxt = successors_found[0]
                key = nxt.qualified_name.lower()
                if key in seen:
                    break
                path.append(nxt)
                seen.add(key)
                current_resources = sql_read_resources(current)
                next_resources = sql_read_resources(nxt)
                if current_resources:
                    causal_steps += 1
                    causal_symbols += 1
                    if (
                        causal_steps > self.config.causal_expansion_depth
                        or causal_symbols > self.config.causal_expansion_max_symbols
                    ):
                        path.pop()
                        seen.remove(key)
                        unresolved.append(
                            f"{current.qualified_name} → expansión causal SQL limitada por profundidad/símbolos"
                        )
                        break
                # V16 is activated only after a uniquely resolved class has
                # entered the path.  Bound this local continuation separately
                # from the established V14/V15 flow depth.
                if current.type == "class" or expansion_steps:
                    expansion_steps += 1
                    expansion_symbols += 1
                    if (
                        not current_resources
                        and not next_resources
                        and (
                            expansion_steps >= self.config.directed_expansion_depth
                            or expansion_symbols >= self.config.directed_expansion_max_symbols
                        )
                    ):
                        break
                current = nxt
            return path

        def path_to_terminal(source: SymbolRecord) -> tuple[list[SymbolRecord] | None, tuple[str, str] | None]:
            queue: deque[SymbolRecord] = deque([source])
            parent: dict[str, str | None] = {source.qualified_name.lower(): None}
            objects: dict[str, SymbolRecord] = {source.qualified_name.lower(): source}
            terminal_edges: dict[str, tuple[str, str]] = {}
            while queue:
                current = queue.popleft()
                calls = current.metadata.get("calls", []) if isinstance(current.metadata, dict) else []
                for call in calls:
                    if isinstance(call, str) and _looks_terminal_for_action(call, analysis.action_terms):
                        path: list[SymbolRecord] = []
                        key: str | None = current.qualified_name.lower()
                        while key is not None:
                            node = objects[key]
                            path.append(node)
                            key = parent[key]
                        path.reverse()
                        return path, (current.qualified_name, call)
                for nxt in successors(current, unresolved):
                    key = nxt.qualified_name.lower()
                    if key in parent:
                        continue
                    parent[key] = current.qualified_name.lower()
                    objects[key] = nxt
                    queue.append(nxt)
            return None, None

        path: list[SymbolRecord] = [start]
        current = start
        for target in target_records:
            segment = shortest_path(current, target)
            if not segment:
                # A requested symbol is a context requirement, not necessarily
                # a graph waypoint. Keep it in the selected context without
                # fabricating an edge. The real directed path continues from
                # the last reachable node.
                required_not_path[target.qualified_name] = target
                unresolved.append(
                    f"{target.qualified_name} no es alcanzable desde {current.qualified_name}; "
                    "se incluye como símbolo solicitado, pero no se inventa una llamada"
                )
                continue
            path.extend(segment[1:])
            current = target

        terminal_edge: tuple[str, str] | None = None
        if analysis.terminal_requested:
            # Terminal discovery is independent from optional/review symbols.
            # A requested helper may be outside the execution path, but that
            # must not prevent us from following the real printing path to the
            # terminal sink.
            terminal_path, terminal_edge = path_to_terminal(current)
            if terminal_path:
                path.extend(terminal_path[1:])
            else:
                unresolved.append(f"{current.qualified_name} → terminal ({', '.join(analysis.flow_spec.terminal_terms)})")
        elif analysis.flow_requested:
            # Behavioral questions are directed even without an explicit
            # terminal. Follow a deterministic local chain so questions such
            # as "por qué no se envían" and "dónde se guardan" expose the
            # actual next functions instead of stopping at the root symbol.
            end_path = path_to_unique_end(current)
            path.extend(end_path[1:])
            # Even when the user did not explicitly request a terminal, record
            # a strong materialization sink if the final reachable symbol calls
            # one. This is evidence, not a forced terminal requirement.
            for node in reversed(path):
                calls = node.metadata.get("calls", []) if isinstance(node.metadata, dict) else []
                terminal_call = next(
                    (call for call in calls if isinstance(call, str) and _looks_terminal_for_action(call, analysis.action_terms)),
                    None,
                )
                if terminal_call:
                    terminal_edge = (node.qualified_name, terminal_call)
                    break

        # Deduplicate while preserving execution order.
        ordered_symbols: list[SymbolRecord] = []
        seen: set[str] = set()
        for symbol in path:
            key = symbol.qualified_name.lower()
            if key not in seen:
                seen.add(key)
                ordered_symbols.append(symbol)

        ordered_paths: list[str] = []
        flow: dict[str, SymbolRecord] = {}
        for symbol in ordered_symbols:
            flow[symbol.qualified_name] = symbol
            if symbol.rel_path not in ordered_paths:
                ordered_paths.append(symbol.rel_path)

        # Required symbols that are not on the directed path still need their
        # complete code because the user explicitly requested them. Their files
        # are selected as strict-flow context, but they are kept separate from
        # the actual path so the diagnostic never presents a fabricated edge.
        required_paths = list(ordered_paths)
        for symbol in required_not_path.values():
            if symbol.rel_path not in required_paths:
                required_paths.append(symbol.rel_path)

        depth = max(0, len(ordered_symbols) - 1)
        terminal_edges = [terminal_edge] if terminal_edge else []
        return (
            required_paths,
            flow,
            required_not_path,
            depth,
            unresolved,
            terminal_edges,
            [symbol.qualified_name for symbol in ordered_symbols],
        )


    def _expand_graph(
        self,
        store: SqliteIndexStore,
        file_scores: dict[str, float],
        file_reasons: dict[str, list[str]],
    ) -> int:
        outgoing = store.outgoing_map()
        incoming: dict[str, set[str]] = defaultdict(set)
        for src, targets in outgoing.items():
            for dst in targets:
                incoming[dst].add(src)
        seeds = [path for path, score in sorted(file_scores.items(), key=lambda item: item[1], reverse=True) if score > 0]
        if not seeds:
            return 0
        weights = self.config.weights
        max_depth = 0
        frontier: deque[tuple[str, int, str]] = deque()
        for seed in seeds[: self.config.max_primary_files]:
            frontier.append((seed, 0, "out"))
            frontier.append((seed, 0, "in"))
        visited: set[tuple[str, str]] = set()
        while frontier:
            node, depth, direction = frontier.popleft()
            key = (node, direction)
            if key in visited:
                continue
            visited.add(key)
            max_depth = max(max_depth, depth)
            if direction == "out" and depth >= self.config.max_depth:
                continue
            if direction == "in" and depth >= self.config.incoming_depth:
                continue
            nxt = outgoing.get(node, set()) if direction == "out" else incoming.get(node, set())
            signal = SIGNAL_DEPENDENCY if direction == "out" else SIGNAL_IMPORT_IN
            if direction == "out" and depth >= 0:
                signal = SIGNAL_IMPORT_OUT if depth >= 1 else SIGNAL_DEPENDENCY
            for neighbor in nxt:
                next_depth = depth + 1
                if direction == "out" and next_depth > self.config.max_depth:
                    continue
                if direction == "in" and next_depth > self.config.incoming_depth:
                    continue
                scale = 0.65**next_depth
                add_signal(
                    file_scores,
                    file_reasons,
                    neighbor,
                    SIGNAL_IMPORT_OUT if direction == "out" else SIGNAL_IMPORT_IN,
                    weights,
                    scale=scale,
                )
                if neighbor not in file_reasons or SIGNAL_DEPENDENCY not in file_reasons[neighbor]:
                    if direction == "out":
                        add_signal(file_scores, file_reasons, neighbor, SIGNAL_DEPENDENCY, weights, scale=scale)
                frontier.append((neighbor, next_depth, direction))
                max_depth = max(max_depth, next_depth)
        return max_depth

    def _expand_calls(
        self,
        store: SqliteIndexStore,
        file_scores: dict[str, float],
        file_reasons: dict[str, list[str]],
    ) -> int:
        """Expand the context through statically detected Python function calls.

        Calls are stored in symbol metadata by the AST analyzer. Resolution is
        deliberately conservative: a call is followed only when its short name
        maps to a unique symbol, or when a matching symbol exists in the same
        file. This avoids pulling unrelated helpers such as ``connect`` from
        arbitrary modules.
        """
        all_symbols: list[SymbolRecord] = []
        for rel_path in store.list_files():
            all_symbols.extend(store.symbols_for_path(rel_path))

        by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
        by_qualified: dict[str, SymbolRecord] = {}
        for symbol in all_symbols:
            if symbol.type not in {"function", "method"}:
                continue
            by_name[symbol.name.lower()].append(symbol)
            by_qualified[symbol.qualified_name.lower()] = symbol

        if not by_name:
            return 0

        ranked = sorted(file_scores.items(), key=lambda item: item[1], reverse=True)
        frontier: list[tuple[SymbolRecord, int]] = []
        seen_sources: set[tuple[str, str, int]] = set()

        # Start from the strongest files. This keeps the call graph focused on
        # the task instead of traversing the entire application.
        for rel_path, _score in ranked[: self.config.max_primary_files]:
            for symbol in store.symbols_for_path(rel_path):
                if symbol.type in {"function", "method"}:
                    frontier.append((symbol, 0))

        max_depth = 0
        for source, depth in frontier:
            key = (source.rel_path, source.qualified_name, depth)
            if key in seen_sources:
                continue
            seen_sources.add(key)
            if depth >= self.config.call_depth:
                continue

            calls = source.metadata.get("calls", []) if isinstance(source.metadata, dict) else []
            for call in calls:
                if not isinstance(call, str) or not call:
                    continue
                short_name = call.rsplit(".", 1)[-1].lower()
                candidates = by_name.get(short_name, [])
                if not candidates:
                    continue

                # Prefer same-file resolution. Otherwise follow only unique
                # names; ambiguous calls are too risky for context selection.
                same_file = [item for item in candidates if item.rel_path == source.rel_path]
                if len(same_file) == 1:
                    targets = same_file
                elif len(candidates) == 1:
                    targets = candidates
                else:
                    continue

                for target in targets:
                    if target.rel_path == source.rel_path and target.qualified_name == source.qualified_name:
                        continue
                    next_depth = depth + 1
                    scale = 0.78 ** (next_depth - 1)
                    add_signal(
                        file_scores,
                        file_reasons,
                        target.rel_path,
                        SIGNAL_FUNCTION_CALL,
                        self.config.weights,
                        scale=scale,
                    )
                    if target.rel_path not in file_reasons:
                        file_reasons[target.rel_path] = []
                    if target.qualified_name not in by_qualified:
                        by_qualified[target.qualified_name.lower()] = target
                    frontier.append((target, next_depth))
                    max_depth = max(max_depth, next_depth)

        return max_depth

    def _boost_same_module(self, file_scores: dict[str, float], file_reasons: dict[str, list[str]]) -> None:
        if not file_scores:
            return
        top = max(file_scores, key=file_scores.get)  # type: ignore[arg-type]
        parent = str(Path(top).parent)
        weights = self.config.weights
        for rel_path in list(file_scores):
            if str(Path(rel_path).parent) == parent and rel_path != top:
                add_signal(file_scores, file_reasons, rel_path, SIGNAL_SAME_MODULE, weights)

    def _select_files(
        self, file_scores: dict[str, float], file_reasons: dict[str, list[str]],
        analysis: TaskAnalysis | None = None,
        preferred_paths: tuple[str, ...] = (),
    ) -> tuple[list[str], dict[str, str]]:
        if not file_scores:
            return [], {}
        if analysis and analysis.flow_only:
            # Strict flow mode never falls back to generic ranking. If the call
            # graph could not resolve the requested flow, return no context
            # rather than inventing unrelated candidates.
            return [], {}
        ranked = sorted(file_scores.items(), key=lambda item: item[1], reverse=True)
        peak = ranked[0][1] or 1.0
        roles: dict[str, str] = {}
        primaries = [path for path in preferred_paths if path in file_scores]
        for path in primaries:
            roles[path] = ROLE_PRIMARY
        for path, score in ranked:
            if path in primaries:
                continue
            reasons = file_reasons.get(path, [])
            direct = any(
                item in reasons
                for item in (
                    SIGNAL_EXACT_SYMBOL,
                    SIGNAL_EXACT_QUALIFIED,
                    SIGNAL_EXACT_FILENAME,
    SIGNAL_EXACT_BASENAME,
                    SIGNAL_SYMBOL_FTS,
                    SIGNAL_FUNCTION_CALL,
                )
            )
            if (direct or score >= peak * self.config.primary_score_ratio) and len(primaries) < self.config.max_primary_files:
                primaries.append(path)
                roles[path] = ROLE_PRIMARY
        selected: list[str] = list(primaries)
        for path, _score in ranked:
            if path in selected:
                continue
            if len(selected) >= self.config.max_files:
                break
            selected.append(path)
            reasons = file_reasons.get(path, [])
            graph_only = SIGNAL_IMPORT_OUT in reasons or SIGNAL_IMPORT_IN in reasons or SIGNAL_DEPENDENCY in reasons
            if graph_only and path not in primaries:
                roles[path] = ROLE_SECONDARY if SIGNAL_IMPORT_OUT in reasons or SIGNAL_DEPENDENCY in reasons else ROLE_REFERENCE
            else:
                roles[path] = ROLE_SECONDARY
        return selected, roles

    def _select_symbols(
        self,
        store: SqliteIndexStore,
        selected_paths: list[str],
        roles: dict[str, str],
        symbol_hits: dict[str, SymbolRecord],
        file_scores: dict[str, float],
        preferred_symbols: dict[str, SymbolRecord] | None = None,
    ) -> list[SelectedSymbol]:
        chosen: list[SelectedSymbol] = []
        seen: set[str] = set()
        preferred_symbols = preferred_symbols or {}
        strict_flow_symbols = bool(preferred_symbols)
        peak = max(file_scores.values()) if file_scores else 1.0
        for path in selected_paths:
            for symbol in store.symbols_for_path(path):
                if strict_flow_symbols and symbol.qualified_name not in preferred_symbols:
                    continue
                if symbol.type in {"decorator", "module"} and symbol.qualified_name not in symbol_hits:
                    continue
                matched = (
                    symbol.qualified_name in symbol_hits
                    or symbol.name in {item.name for item in symbol_hits.values()}
                    or symbol.qualified_name in preferred_symbols
                )
                if not matched and roles.get(path) != ROLE_PRIMARY:
                    continue
                if not matched and symbol.type not in {"class", "function", "method"}:
                    continue
                if symbol.qualified_name in seen:
                    continue
                seen.add(symbol.qualified_name)
                role = roles.get(path, ROLE_SECONDARY)
                score = (file_scores.get(path, 0.0) / peak) if peak else 0.0
                reasons = []
                if symbol.qualified_name in preferred_symbols:
                    reasons.append("flow path symbol")
                elif matched:
                    reasons.append("matched task term")
                else:
                    reasons.append("structural neighbor in selected file")
                chosen.append(
                    SelectedSymbol(
                        name=symbol.name,
                        qualified_name=symbol.qualified_name,
                        type=symbol.type,
                        rel_path=path,
                        line_start=symbol.line_start,
                        line_end=symbol.line_end,
                        role=role,
                        score=round(score, 4),
                        reasons=reasons,
                        signature=_signature(symbol),
                        metadata=symbol.metadata,
                    )
                )
        chosen.sort(key=lambda item: item.score, reverse=True)
        return chosen

    def _build_files(
        self,
        project: Project,
        store: SqliteIndexStore,
        selected_paths: list[str],
        roles: dict[str, str],
        file_scores: dict[str, float],
        file_reasons: dict[str, list[str]],
        symbols: list[SelectedSymbol],
    ) -> list[SelectedFile]:
        peak = max(file_scores.values()) if file_scores else 1.0
        by_path: dict[str, list[SelectedSymbol]] = defaultdict(list)
        for symbol in symbols:
            by_path[symbol.rel_path].append(symbol)
        result: list[SelectedFile] = []
        for path in selected_paths:
            role = roles.get(path, ROLE_SECONDARY)
            score = (file_scores.get(path, 0.0) / peak) if peak else 0.0
            fragments = self._fragments(project, path, by_path.get(path, []), role)
            result.append(
                SelectedFile(
                    path=path,
                    score=round(score, 4),
                    role=role,
                    reasons=list(file_reasons.get(path, [])),
                    fragments=fragments,
                    symbols=[item.qualified_name for item in by_path.get(path, [])],
                )
            )
        return result

    def _fragments(
        self,
        project: Project,
        rel_path: str,
        symbols: list[SelectedSymbol],
        role: str,
    ) -> list[Fragment]:
        path = project.path / rel_path
        if not path.is_file():
            return [
                Fragment(line_start=1, line_end=1, content=_signature_block(symbols), compressed=True)
            ]
        try:
            text = decode_text(path.read_bytes())
        except OSError:
            return []
        lines = text.splitlines()
        if role in {ROLE_SECONDARY, ROLE_REFERENCE}:
            block = _signature_block(symbols) or "\n".join(lines[: min(8, len(lines))])
            return [
                Fragment(
                    line_start=symbols[0].line_start or 1 if symbols else 1,
                    line_end=symbols[0].line_end or 1 if symbols else min(8, len(lines)),
                    content=block,
                    compressed=True,
                )
            ]
        ranges: list[tuple[int, int, str | None]] = []
        for symbol in symbols[: self.config.max_fragments_per_file]:
            if not symbol.line_start:
                continue
            start = max(1, symbol.line_start - self.config.context_lines_before)
            end = min(len(lines), (symbol.line_end or symbol.line_start) + self.config.context_lines_after)
            ranges.append((start, end, symbol.qualified_name))
        if not ranges and lines:
            ranges.append((1, min(len(lines), 40), None))
        merged = _merge_ranges(ranges)
        fragments: list[Fragment] = []
        for start, end, name in merged[: self.config.max_fragments_per_file]:
            chunk = "\n".join(lines[start - 1 : end])
            fragments.append(Fragment(line_start=start, line_end=end, content=chunk, symbol_name=name))
        return fragments

    def _relations(
        self,
        store: SqliteIndexStore,
        selected: list[str],
        flow_symbols: dict[str, SymbolRecord] | None = None,
        terminal_edges: list[tuple[str, str]] | None = None,
    ) -> list[ContextRelation]:
        selected_set = set(selected)
        relations: list[ContextRelation] = []
        seen: set[tuple[str, str, str]] = set()

        for src, dst, module in store.list_edges():
            if dst and src in selected_set and dst in selected_set:
                key = (src, dst, "import")
                if key in seen:
                    continue
                seen.add(key)
                relations.append(
                    ContextRelation(source=src, target=dst, kind="import", reason=f"imports {module}")
                )

        # Expose the same call-graph information used by ranking so the
        # diagnostic UI can explain why a function-related file was selected.
        all_symbols: list[SymbolRecord] = []
        for rel_path in store.list_files():
            all_symbols.extend(store.symbols_for_path(rel_path))
        by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
        for symbol in all_symbols:
            if symbol.type in {"function", "method"}:
                by_name[symbol.name.lower()].append(symbol)

        for source in all_symbols:
            if source.rel_path not in selected_set or source.type not in {"function", "method"}:
                continue
            if flow_symbols is not None and source.qualified_name not in flow_symbols:
                continue
            calls = source.metadata.get("calls", []) if isinstance(source.metadata, dict) else []
            for call in calls:
                if not isinstance(call, str):
                    continue
                candidates = by_name.get(call.rsplit(".", 1)[-1].lower(), [])
                same_file = [item for item in candidates if item.rel_path == source.rel_path]
                targets = same_file if len(same_file) == 1 else (candidates if len(candidates) == 1 else [])
                for target in targets:
                    if target.rel_path not in selected_set or target.rel_path == source.rel_path:
                        continue
                    if flow_symbols is not None and target.qualified_name not in flow_symbols:
                        continue
                    key = (source.rel_path, target.rel_path, "call")
                    if key in seen:
                        continue
                    seen.add(key)
                    relations.append(
                        ContextRelation(
                            source=source.rel_path,
                            target=target.rel_path,
                            kind="call",
                            reason=f"{source.qualified_name} calls {target.qualified_name}",
                        )
                    )
        for source, terminal in terminal_edges or []:
            relations.append(
                ContextRelation(
                    source=source,
                    target=terminal,
                    kind="terminal",
                    reason=f"{source} reaches terminal {terminal}",
                )
            )
        return relations


def _signature(symbol: SymbolRecord | SelectedSymbol) -> str:
    metadata = getattr(symbol, "metadata", {}) or {}
    params = metadata.get("params") if isinstance(metadata, dict) else None
    is_async = bool(metadata.get("async")) if isinstance(metadata, dict) else False
    qname = symbol.qualified_name
    if symbol.type == "class":
        bases = metadata.get("bases") if isinstance(metadata, dict) else None
        suffix = f"({', '.join(bases)})" if bases else ""
        return f"class {qname}{suffix}"
    if symbol.type in {"function", "method"}:
        prefix = "async def" if is_async else "def"
        arglist = ", ".join(params) if isinstance(params, list) else ""
        return f"{prefix} {qname}({arglist})"
    if symbol.type == "constant":
        return f"{qname} = ..."
    return qname


def _unresolved_parts(value: str) -> tuple[str, str]:
    """Extract the source and potential target from an unresolved flow note."""
    source, separator, target = value.partition(" → ")
    if not separator:
        return value, value
    return source.strip(), target.strip()


def _signature_block(symbols: list[SelectedSymbol]) -> str:
    interesting = [item for item in symbols if item.type in {"class", "function", "method", "constant"}]
    return "\n".join(item.signature for item in interesting[:12])


def _merge_ranges(ranges: list[tuple[int, int, str | None]]) -> list[tuple[int, int, str | None]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: item[0])
    merged: list[tuple[int, int, str | None]] = [ordered[0]]
    for start, end, name in ordered[1:]:
        prev_start, prev_end, prev_name = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end), prev_name or name)
        else:
            merged.append((start, end, name))
    return merged


def _terminal_terms_for_actions(actions: list[str]) -> tuple[str, ...]:
    terms: list[str] = []
    mapping = {
        "print": ("win32print", "WritePrinter", "salida de bytes"),
        "save": ("write", "dump", "json", "sqlite", "execute", "commit", "open(..., \"w\")"),
        "send": ("requests", "post", "put", "send", "upload", "http"),
        "load": ("read", "json.load", "sqlite", "select", "fetch", "get"),
        "show": ("render", "template", "configure", "insert", "display"),
    }
    for action in actions:
        for term in mapping.get(action, ()):
            if term not in terms:
                terms.append(term)
    return tuple(terms)


def _looks_terminal_for_action(call: str, actions: list[str]) -> bool:
    if not isinstance(call, str):
        return False
    lowered = call.lower()
    if not actions:
        return _looks_terminal_call(call)
    markers: dict[str, tuple[str, ...]] = {
        "print": ("writeprinter", "rawprinter", "send_bytes", "sendbytes", "send_raw", "sendraw", "write_bytes", "writebytes", "printer.write"),
        "save": ("write", "dump", "json.dump", "to_json", "sqlite", "execute", "commit", "open", "save", "backup"),
        "send": ("requests.post", "requests.put", "requests.request", "post", "put", "send", "upload", "http", "urlopen"),
        "load": ("json.load", "read", "sqlite", "select", "fetch", "get", "load", "open"),
        "show": ("render", "render_template", "template", "configure", "insert", "display", "show", "pack", "grid"),
    }
    return any(marker in lowered for action in actions for marker in markers.get(action, ()))


def _looks_terminal_call(call: str) -> bool:
    """Return True only for a strong byte-output/print sink.

    Printer lifecycle calls such as OpenPrinter/StartDocPrinter/StartPagePrinter
    are intermediate operations. Treating them as terminals truncated directed
    investigations before the actual byte write. A flow investigation should
    continue through those calls until a real output sink is reached.
    """
    lowered = call.lower()
    strong_markers = (
        "writeprinter",
        "rawprinter",
        "send_bytes", "sendbytes",
        "send_raw", "sendraw",
        "write_bytes", "writebytes",
        "printer.write",
    )
    return any(marker in lowered for marker in strong_markers)


def _is_printer_lifecycle_call(call: str) -> bool:
    """Identify printer setup/lifecycle calls for diagnostics, not termination."""
    lowered = call.lower()
    return any(
        marker in lowered
        for marker in (
            "win32print.openprinter",
            "openprinter",
            "startdocprinter",
            "startpageprinter",
            "endpageprinter",
            "enddocprinter",
            "closeprinter",
        )
    )
