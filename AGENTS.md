# AIDYCAI — instrucciones para agentes

## Propósito
AIDYCAI es una capa local de inteligencia para desarrollo. No es un clon de Cursor.
Su Core debe funcionar sin LLM, embeddings ni proveedores externos.

## Arquitectura
- `domain/`: modelos, excepciones y protocolos.
- `application/`: casos de uso y reglas.
- `infrastructure/`: SQLite, filesystem, AST, FTS5 y grafo.
- `cli/`: interfaz de línea de comandos.
- `gui/`: interfaz gráfica; solo presentación/adaptación del Core.

## Reglas
1. No modificar AIDYC, AIDYCWeb, catalog-studio ni deunacolombia.
2. No copiar código de proyectos externos al repositorio AIDYCAI.
3. El código de proyectos externos se referencia por sus rutas originales.
4. El Core no debe importar SDKs de Cursor, Kimi, OpenAI, Anthropic u Ollama.
5. La GUI y la CLI deben reutilizar los servicios de `application/`; no duplicar lógica.
6. Los datos persistentes viven en `%LOCALAPPDATA%\AIDYCAI`, no dentro de OneDrive.
7. Las operaciones de GUI que puedan tardar deben ejecutarse fuera del hilo principal y abrir su propio `AppContext`.
8. Antes de una modificación arquitectónica grande, presentar plan y detenerse para aprobación.
9. Ejecutar toda la suite de tests después de cambios.
10. No implementar edición automática, ejecución arbitraria de comandos ni agentes autónomos sin aprobación explícita.

## Estado
- Fase 1: registro de proyectos — terminada.
- Fase 2: índice incremental + AST + FTS5 + grafo — terminada.
- Fase 3: Context Engine + ContextBundle — terminada.
- GUI inicial: capa visual local sobre registro, índice, búsqueda y ContextBundle.
- Provider/LLM: todavía no implementado.

## Comandos principales
- `aidycai project list`
- `aidycai index AIDYC`
- `aidycai search AIDYC "texto"`
- `aidycai context AIDYC "pregunta"`
- `aidycai gui`
