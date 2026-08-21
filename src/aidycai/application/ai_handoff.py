from __future__ import annotations

from dataclasses import asdict

from aidycai.domain.context_models import AIHandoff, ContextBundle


def build_ai_handoff(bundle: ContextBundle) -> AIHandoff:
    """Convert a completed ContextBundle into a provider-neutral handoff.

    The function is deliberately a pure in-memory transformation.  It reads
    no project files and has no access to SQLite, FTS, ranking, or the context
    engine, so producing a handoff cannot start a second investigation.
    """
    metadata = dict(getattr(bundle, "metadata", {}))
    analysis = bundle.analysis
    evidence = list(getattr(bundle, "evidence", []))
    evidence_summary = getattr(bundle, "evidence_summary", None)
    unresolved = list(metadata.get("flow_unresolved", []))

    return AIHandoff(
        protocol="aidycai-ai-handoff-v1",
        project={"id": bundle.project_id, "name": bundle.project_name},
        task=bundle.task,
        strategy=analysis.research_strategy,
        intent=asdict(analysis),
        selected_files=[asdict(item) for item in bundle.files],
        selected_symbols=[asdict(item) for item in bundle.symbols],
        relationships=[asdict(item) for item in bundle.relations],
        flow={
            "path": list(metadata.get("flow_path", [])),
            "terminal_edges": list(metadata.get("terminal_edges", [])),
            "required_symbols": list(metadata.get("flow_required_symbols", [])),
            "unresolved_relations": unresolved,
        },
        evidence={
            "records": [asdict(item) for item in evidence],
            "summary": asdict(evidence_summary) if evidence_summary is not None else {
                "strong_evidence": 0,
                "medium_evidence": 0,
                "weak_evidence": 0,
                "unresolved": 0,
            },
        },
        unresolved_relations=unresolved,
        limitations=list(bundle.limitations),
        statistics=asdict(bundle.statistics),
        confidence=analysis.intent_confidence,
        metadata=metadata,
    )
