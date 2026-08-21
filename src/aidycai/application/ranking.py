from __future__ import annotations

from aidycai.domain.context_models import RankingWeights

SIGNAL_EXACT_SYMBOL = "exact symbol match"
SIGNAL_EXACT_QUALIFIED = "qualified symbol match"
SIGNAL_EXACT_FILENAME = "exact filename match"
SIGNAL_EXACT_BASENAME = "exact basename match"
SIGNAL_SYMBOL_FTS = "symbol text match"
SIGNAL_FILE_FTS = "file content match"
SIGNAL_PATH = "path match"
SIGNAL_PARTIAL = "partial text match"
SIGNAL_IMPORT_OUT = "import graph relation"
SIGNAL_IMPORT_IN = "imported by selected file"
SIGNAL_DEPENDENCY = "dependency of selected symbol"
SIGNAL_SAME_MODULE = "same module"
SIGNAL_FUNCTION_CALL = "function call"


def weight_for(signal: str, weights: RankingWeights) -> float:
    mapping = {
        SIGNAL_EXACT_SYMBOL: weights.exact_symbol,
        SIGNAL_EXACT_QUALIFIED: weights.exact_qualified,
        SIGNAL_EXACT_FILENAME: weights.exact_filename,
        SIGNAL_EXACT_BASENAME: weights.exact_filename * 0.92,
        SIGNAL_SYMBOL_FTS: weights.symbol_fts,
        SIGNAL_FILE_FTS: weights.file_fts,
        SIGNAL_PATH: weights.path_match,
        SIGNAL_PARTIAL: weights.text_partial,
        SIGNAL_IMPORT_OUT: weights.import_outgoing,
        SIGNAL_IMPORT_IN: weights.import_incoming,
        SIGNAL_DEPENDENCY: weights.import_outgoing,
        SIGNAL_SAME_MODULE: weights.same_module,
        SIGNAL_FUNCTION_CALL: weights.function_call,
    }
    return mapping.get(signal, 1.0)


def add_signal(
    bucket: dict[str, float],
    reasons: dict[str, list[str]],
    key: str,
    signal: str,
    weights: RankingWeights,
    scale: float = 1.0,
) -> None:
    items = reasons.setdefault(key, [])
    if signal in items:
        return
    items.append(signal)
    bucket[key] = bucket.get(key, 0.0) + weight_for(signal, weights) * scale
