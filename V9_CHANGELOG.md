# AIDYCAI v9

## Objetivo
Mejorar la experiencia de indexación y la estabilidad de la GUI sin modificar la lógica del Context Engine v8.

## Cambios
- Progreso de indexación por etapas y archivo actual.
- Conteo `hecho/total` visible en la GUI.
- Indexación automática cuando una consulta detecta que el proyecto todavía no tiene índice.
- Al terminar la indexación automática, la consulta continúa con `ContextBundle`.
- Todas las operaciones de fondo usan el mismo mecanismo de exclusión para evitar operaciones concurrentes desde la GUI.
- Corregido el cierre de `lambda` sobre excepciones capturadas en `except`, que provocaba `NameError: cannot access free variable 'exc'`.
- Mejorada la presentación del error y del estado de progreso.
- Añadida prueba del callback de progreso del indexador.

## No modificado
- Ranking y selección del Context Engine.
- Resolución del call graph v8.
- Reglas de `EXCLUSIVAMENTE` / `IGNORA`.
- Resolución de terminales.
