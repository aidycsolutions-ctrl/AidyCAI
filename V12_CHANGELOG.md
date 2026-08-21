# V12 CHANGELOG

## Objetivo

V12 convierte preguntas abiertas de comportamiento en investigaciones dirigidas cuando la intención es suficientemente clara y mejora la GUI para presentar el resultado como una conversación humana.

## Cambios

- Detección determinista de preguntas de diagnóstico por acción (imprimir, guardar, cargar y enviar).
- Activación automática de investigación de flujo para preguntas como "¿por qué no se imprime...?".
- Inferencia conservadora del símbolo inicial usando el índice real, sin inventar funciones.
- Para impresión, seguimiento automático hasta terminales `win32print` / `WritePrinter` cuando el grafo lo permite.
- Corrección de resolución de símbolos duplicados cuando uno de los archivos está explícitamente excluido.
- Respuesta visible de la GUI convertida de resumen técnico a explicación humana breve basada en evidencia del índice.
- Conversación visual en dos lados: AIDYCAI a la izquierda y TÚ a la derecha.
- Diagnóstico técnico colapsado dentro de la conversación, con opción de desplegarlo.
- Se mantienen las pestañas técnicas de Contexto, Búsqueda, Detalles y Diagnóstico.
- Nuevas pruebas para intención automática, flujo automático y respuesta humana.

## Fuera de alcance

- No se modificaron reglas de ranking de archivos de forma general.
- No se modificó el tratamiento específico de `sales.html`.
- No se modificó la lógica de generación de un Context Engine semántico/LLM.
- No se modificaron funciones de ranking de negocio ni lógica de AIDYC/AIDYCWeb.
