# AIDYCAI v10

## Ranking de archivos y exclusiones de entornos

- Excluye por defecto `venv`, `.venv`, `node_modules`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache` y `.git` durante el escaneo.
- Los nombres de archivo explícitos del usuario reciben coincidencia exacta de nombre; tokens de extensión como `html` ya no crean falsos `exact filename match` para `html.py`.
- Un archivo con el mismo basename y otra extensión recibe una señal fuerte (`exact basename match`), útil para consultas como `sales.html` → `sales.css`.
- Las palabras clave y términos relacionados siguen aportando coincidencias de ruta, pero con menor fuerza que un archivo explícitamente solicitado.
- Se mantiene intacta la lógica de Context Engine/call graph de V8/V9.
