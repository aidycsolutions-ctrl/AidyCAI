# AIDYCAI V14

## Objetivo

Añadir una capa determinista de **Intención de investigación** para que AIDYCAI no trate todas las preguntas abiertas como búsquedas o flujos equivalentes.

## Cambios

- Se añade `ResearchIntent` con tipo, estrategia, confianza y señales.
- Se clasifican preguntas en estrategias como `FRONTEND_RESPONSIVE`, `FRONTEND_LAYOUT`, `FILE_LOCATION`, `BACKEND_FLOW`, `PERSISTENCE`, `DATA_FLOW`, `DATABASE`, `SYNC`, `PRINTING`, `ERROR` y `GENERAL_DIAGNOSTIC`.
- Las preguntas frontend/responsive incorporan vocabulario local de CSS/layout (`media`, `overflow`, `height`, `position`, `sticky`, `fixed`, `flex`, `grid`, `viewport`, `scroll`, `extends`).
- Las investigaciones frontend no realizan expansión automática del grafo Python, evitando que lógica backend desplace evidencia de HTML/CSS/JS.
- Las preguntas de localización de archivos permanecen deliberadamente poco profundas.
- El `ContextBundle`, el diagnóstico y el handoff exponen la intención de investigación.
- Las preguntas backend existentes conservan su resolución de flujo.
- Se añaden regresiones para frontend responsive, localización, envío, persistencia y flujo de datos.

## No incluido

- No conexión con proveedores externos.
- No edición automática de proyectos.
- No cambios en los archivos de AIDYC/AIDYCWeb u otros proyectos registrados.
- No cambios globales de pesos del ranking.
- No cambios en la lógica de negocio.
