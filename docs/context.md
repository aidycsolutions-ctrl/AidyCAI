# Context Engine (Fase 3)

El motor convierte una tarea en un `ContextBundle` mínimo usando solo el índice local.

```text
Task → términos → FTS/símbolos/archivos → ranking → grafo → fragmentos → bundle
```

No hay LLM. Los pesos viven en `RankingWeights` (`application/ranking.py` + `ContextConfig`).

## Comandos

```text
aidycai context AIDYC "¿Dónde se calcula el total de una factura?"
aidycai context AIDYC "..." --output context.json
aidycai context AIDYC "..." --output context.txt
```

## Configuración (código)

- `max_files` (8)
- `max_primary_files` (4)
- `max_depth` (2) para imports salientes
- `incoming_depth` (1) para quien importa al candidato
- `context_lines_before` / `context_lines_after` (2)

## Ranking

Señales (la exacta de símbolo/qualified/filename pesa más que FTS de contenido):

- exact symbol / qualified symbol / exact filename
- symbol FTS / file content / path
- import graph / dependency / imported-by / same module

Cada archivo y símbolo guarda `reasons`.

## Limitaciones

- Glosario local (`factura` → invoice, `iva` → tax). No entiende frases complejas.
- El grafo solo sigue imports Python resueltos.
- PRIMARY lleva fragmentos de código; SECONDARY/REFERENCE suelen ir comprimidos a firmas.
- Estimación de tokens = caracteres / 4.


## Grafo de llamadas de funciones

El Context Engine analiza llamadas estáticas de funciones y métodos Python y las usa
como una señal más fuerte que una relación de importación. Las llamadas se guardan
en la metadata de los símbolos y permiten seguir una cadena como:

`guardar_retiro()` → `imprimir_ultimos_retiros()` → `imprimir_ticket_retiro()`

La resolución es conservadora: se siguen nombres únicos o coincidencias dentro del
mismo archivo para evitar falsos positivos.

### Reconstruir el índice

Como esta capacidad añade metadata a los símbolos, un índice creado con una versión
anterior debe reconstruirse una vez:

```text
aidycai index AIDYC --rebuild
```

Después, las indexaciones normales vuelven a ser incrementales.

## Flujo restringido

Las consultas que expresan una orden de flujo (`seguir`, `llamada`, `hasta`, `flujo`, etc.)
se analizan además como una intención estructurada. `EXCLUSIVAMENTE`, `SOLO` y equivalentes
activan modo estricto; `IGNORA`/`EXCLUYE` producen exclusiones duras antes de seleccionar archivos.

En modo estricto el motor:

1. resuelve el primer símbolo explícito como ancla del flujo;
2. sigue llamadas salientes, no callers/importers laterales;
3. incluye únicamente símbolos del camino resuelto;
4. respeta exclusiones como filtros duros;
5. no rellena hasta `max_files` con candidatos débiles;
6. cuando se solicita el terminal, puede continuar hasta detectar llamadas de salida como
   `win32print`, `WritePrinter` o escritura/envío de bytes, dentro de `flow_call_depth`.

El ranking genérico se conserva para consultas que no son de flujo restringido.

## Directed flow investigations

When a task explicitly requests an exclusive flow, AIDYCAI switches from generic candidate ranking to a directed call-path resolver. `EXCLUSIVAMENTE`/`SOLO` plus explicit function anchors or a terminal request can activate this mode even when the word `flujo` is omitted.

Strict flow mode:

- resolves a concrete start symbol;
- follows outgoing call edges only;
- treats explicitly named intermediate functions as ordered milestones;
- can stop at printer/byte-output terminal calls such as `win32print.WritePrinter`;
- applies excluded files as hard filters;
- does not expand incoming importers, same-module neighbors, or unrelated functions as flow roots;
- does not fill `max_files` with unrelated ranked candidates;
- reports unresolved flow segments instead of substituting semantically similar files.

The diagnostic output exposes the detected start, milestones, exclusions, resolved path, and terminal edge so the selection can be audited.
