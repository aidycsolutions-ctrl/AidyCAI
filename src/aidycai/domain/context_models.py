from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ROLE_PRIMARY = "PRIMARY"
ROLE_SECONDARY = "SECONDARY"
ROLE_REFERENCE = "REFERENCE"


@dataclass(frozen=True)
class RankingWeights:
    exact_symbol: float = 14.0
    exact_qualified: float = 16.0
    exact_filename: float = 12.0
    symbol_fts: float = 6.0
    file_fts: float = 3.5
    path_match: float = 5.0
    text_partial: float = 2.0
    import_outgoing: float = 4.5
    import_incoming: float = 2.5
    same_module: float = 1.5
    function_call: float = 8.0


@dataclass(frozen=True)
class ContextConfig:
    max_files: int = 8
    max_primary_files: int = 4
    max_depth: int = 2
    incoming_depth: int = 1
    call_depth: int = 2
    flow_call_depth: int = 8
    # V16: a class constructor reached from a directed flow may expose one
    # additional local execution chain.  Keep this deliberately small so a
    # missing call never turns into a project-wide traversal.
    directed_expansion_depth: int = 3
    directed_expansion_max_symbols: int = 4
    causal_expansion_depth: int = 2
    causal_expansion_max_symbols: int = 4
    context_lines_before: int = 2
    context_lines_after: int = 2
    max_fragments_per_file: int = 4
    fts_limit: int = 40
    primary_score_ratio: float = 0.42
    weights: RankingWeights = field(default_factory=RankingWeights)


@dataclass(frozen=True)
class FlowSpec:
    strict: bool = False
    direction: str = "outgoing"
    start_symbols: tuple[str, ...] = ()
    target_symbols: tuple[str, ...] = ()
    terminal_terms: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()


@dataclass
class TaskAnalysis:
    task: str
    keywords: list[str]
    symbol_candidates: list[str]
    file_candidates: list[str]
    related_terms: list[str]
    search_queries: list[str]
    # Structured intent extracted from the user's wording. These fields are
    # deliberately deterministic so the context engine can enforce hard
    # constraints before ranking candidates.
    flow_requested: bool = False
    flow_only: bool = False
    follow_calls: bool = False
    flow_direction: str = "outgoing"
    flow_start_candidates: list[str] = field(default_factory=list)
    flow_target_candidates: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    terminal_requested: bool = False
    auto_flow: bool = False
    action_terms: list[str] = field(default_factory=list)
    subject_terms: list[str] = field(default_factory=list)
    flow_spec: FlowSpec = field(default_factory=FlowSpec)
    research_intent: str = "GENERAL_DIAGNOSTIC"
    research_strategy: str = "GENERAL_DIAGNOSTIC"
    intent_confidence: float = 0.0
    intent_signals: list[str] = field(default_factory=list)


@dataclass
class Fragment:
    line_start: int
    line_end: int
    content: str
    symbol_name: str | None = None
    compressed: bool = False


@dataclass
class SelectedSymbol:
    name: str
    qualified_name: str
    type: str
    rel_path: str
    line_start: int | None
    line_end: int | None
    role: str
    score: float
    reasons: list[str]
    signature: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SelectedFile:
    path: str
    score: float
    role: str
    reasons: list[str]
    fragments: list[Fragment] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)


@dataclass
class ContextRelation:
    source: str
    target: str
    kind: str
    reason: str


@dataclass
class ContextStatistics:
    candidate_files: int
    candidate_symbols: int
    selected_files: int
    selected_symbols: int
    selected_lines: int
    selected_chars: int
    available_chars: int
    reduction_ratio: float
    estimated_tokens: int
    graph_depth: int
    search_seconds: float
    total_seconds: float


@dataclass(frozen=True)
class EvidenceRecord:
    """A deterministic, auditable relationship supporting selected context."""

    source: str
    target: str | None
    kind: str
    confidence: str
    reason: str
    demonstrated: bool = True


@dataclass(frozen=True)
class ContextEvidenceSummary:
    """Compact quality counts; these are not a replacement for ranking."""

    strong_evidence: int = 0
    medium_evidence: int = 0
    weak_evidence: int = 0
    unresolved: int = 0


@dataclass
class ContextBundle:
    project_id: str
    project_name: str
    task: str
    analysis: TaskAnalysis
    files: list[SelectedFile]
    symbols: list[SelectedSymbol]
    relations: list[ContextRelation]
    statistics: ContextStatistics
    limitations: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    evidence_summary: ContextEvidenceSummary = field(default_factory=ContextEvidenceSummary)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        from aidycai.application.context_text import render_bundle_text

        return render_bundle_text(self)


@dataclass(frozen=True)
class AIHandoff:
    """Provider-neutral, serializable view of a completed ContextBundle.

    This is intentionally a transport boundary, not another research model.
    Its values are copied from the final bundle by the application layer and
    must never trigger selection, ranking, index access, or evidence creation.
    """

    protocol: str
    project: dict[str, Any]
    task: str
    strategy: str
    intent: dict[str, Any]
    selected_files: list[dict[str, Any]]
    selected_symbols: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    flow: dict[str, Any]
    evidence: dict[str, Any]
    unresolved_relations: list[Any]
    limitations: list[str]
    statistics: dict[str, Any]
    confidence: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        import json

        # Sorted object keys make independently generated handoffs comparable.
        # List order is left intact because it is the engine's selected order.
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
