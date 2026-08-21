# AIDYCAI V13

## Objetivo

Convertir preguntas abiertas de comportamiento en investigaciones dirigidas usando una combinación determinista de **objeto + acción + grafo de llamadas**, y preparar un contrato compacto y agnóstico de proveedor para conectar posteriormente un modelo externo de programación.

## Cambios

- Amplía la detección de acciones a guardar, cargar, enviar y mostrar, incluyendo conjugaciones frecuentes en español.
- Las preguntas del tipo `¿Dónde se guardan...?` pueden activar investigación dirigida aunque no contengan `por qué`.
- Las preguntas de comportamiento `¿Por qué no se envían...?` y `¿Por qué no aparecen...?` ahora siguen el grafo automáticamente.
- La inferencia del símbolo inicial pondera la relación entre objeto y acción y prefiere raíces de flujo sobre helpers internos.
- La detección de terminales de flujo se generaliza por acción; ya no depende exclusivamente de impresión/win32print.
- Se añade `aidycai.application.ai_handoff`, un protocolo compacto y neutral para futuras conexiones con Cursor/Kimi/ChatGPT/Claude u otro proveedor.
- El handoff incluye solo intención, evidencia seleccionada, camino de flujo, estadísticas y capacidades locales; no envía automáticamente el repositorio completo.
- Se mantiene la política de que cualquier escritura futura sobre archivos requiera una capacidad explícita.

## No incluido todavía

- No se conecta ningún proveedor de IA externo.
- No se modifican archivos del proyecto mediante IA.
- No se modifican Context Engine semántico, ranking de `sales.html`, ni lógica de negocio.
