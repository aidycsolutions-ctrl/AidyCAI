from __future__ import annotations

from aidycai.domain.context_models import (
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SECONDARY,
    ContextBundle,
    ContextRelation,
    ContextStatistics,
    SelectedFile,
    SelectedSymbol,
)


def render_bundle_text(bundle: ContextBundle) -> str:
    stats = bundle.statistics
    reduction_pct = f"{stats.reduction_ratio * 100:.1f}%"
    lines = [
        f"PROJECT: {bundle.project_name}",
        "",
        "TASK:",
        bundle.task,
        "",
        "PRIMARY FILES",
        "",
    ]
    primaries = [item for item in bundle.files if item.role == ROLE_PRIMARY]
    secondaries = [item for item in bundle.files if item.role == ROLE_SECONDARY]
    references = [item for item in bundle.files if item.role == ROLE_REFERENCE]
    if not primaries:
        lines.append("(none)")
        lines.append("")
    for item in primaries:
        lines.append(item.path)
        lines.append(f"score: {item.score:.2f}")
        lines.append("reason: " + "; ".join(item.reasons))
        for fragment in item.fragments:
            label = "signature" if fragment.compressed else f"Lines {fragment.line_start}-{fragment.line_end}"
            lines.append(label)
            lines.append(fragment.content.rstrip())
            lines.append("")
        if not item.fragments:
            lines.append("")
    lines.append("SECONDARY CONTEXT")
    lines.append("")
    if not secondaries and not references:
        lines.append("(none)")
        lines.append("")
    for item in secondaries + references:
        lines.append(f"{item.path} [{item.role}] score={item.score:.2f}")
        lines.append("reason: " + "; ".join(item.reasons))
        for fragment in item.fragments:
            lines.append(fragment.content.rstrip())
        lines.append("")
    if bundle.symbols:
        lines.append("SYMBOLS")
        lines.append("")
        for symbol in bundle.symbols:
            extra = f" L{symbol.line_start}" if symbol.line_start else ""
            lines.append(f"{symbol.role} {symbol.signature} ({symbol.rel_path}{extra})")
        lines.append("")
    lines.append("RELATIONSHIPS")
    lines.append("")
    if not bundle.relations:
        lines.append("(none)")
    for rel in bundle.relations:
        lines.append(f"{rel.source} -> {rel.target} ({rel.kind})")
    lines.append("")
    lines.append("EVIDENCE")
    lines.append("")
    if not bundle.evidence:
        lines.append("(none)")
    for item in bundle.evidence:
        target = f" -> {item.target}" if item.target else ""
        state = "demonstrated" if item.demonstrated else "unresolved"
        lines.append(f"{item.source}{target} ({item.kind}/{item.confidence}/{state})")
        lines.append(item.reason)
    summary = bundle.evidence_summary
    lines.append(
        f"Evidence summary: strong={summary.strong_evidence}, medium={summary.medium_evidence}, "
        f"weak={summary.weak_evidence}, unresolved={summary.unresolved}"
    )
    lines.append("")
    lines.append("STATISTICS")
    lines.append("")
    lines.append(f"Candidate files: {stats.candidate_files}")
    lines.append(f"Candidate symbols: {stats.candidate_symbols}")
    lines.append(f"Selected files: {stats.selected_files}")
    lines.append(f"Selected symbols: {stats.selected_symbols}")
    lines.append(f"Selected lines: {stats.selected_lines}")
    lines.append(f"Selected chars: {stats.selected_chars}")
    lines.append(f"Available chars: {stats.available_chars}")
    lines.append(f"Reduction: {reduction_pct}")
    lines.append(f"Estimated tokens: {stats.estimated_tokens}")
    lines.append(f"Graph depth: {stats.graph_depth}")
    lines.append(f"Search seconds: {stats.search_seconds:.3f}")
    lines.append(f"Total seconds: {stats.total_seconds:.3f}")
    if bundle.limitations:
        lines.append("")
        lines.append("LIMITATIONS")
        lines.append("")
        lines.extend(f"- {item}" for item in bundle.limitations)
    return "\n".join(lines).rstrip() + "\n"
