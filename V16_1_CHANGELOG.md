# V16.1 — expansión causal SQL determinista

## Implementado

- Indexación estructurada de operaciones SQL estáticas detectables en Python.
- Índice inverso determinista de escritores `INSERT`/`UPDATE` por recurso SQL.
- Expansión `lector SQL → escritor único` dentro del flujo V16.
- Escritores ambiguos y recursos sin escritor quedan `UNRESOLVED` sin selección arbitraria.
- Continuación determinista hacia un llamador único cuando el escritor expone `turno` como parámetro/columna indexada.
- Límites independientes de profundidad y símbolos para la expansión causal SQL.
- Evidencia `FLOW` para los saltos SQL causales, manteniendo `EvidenceRecord`.
- Sin FTS lateral, embeddings, LLM ni búsqueda textual global para localizar escritores.
- Migración de índice V1 → V2 compatible con bundles anteriores.
- AIHandoff v1 permanece sin cambios de protocolo.

## No incluido

- Adaptadores externos Codex/OpenAI/Anthropic.
- Modificaciones al proyecto AIDYC analizado.
- Inferencia dinámica de SQL construido en runtime.
