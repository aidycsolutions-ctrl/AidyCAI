# Configuración editable de proyectos

Edita únicamente `config/projects.json` para cambiar rutas, comandos, entornos virtuales, navegador, GitHub, deploy o workflow.

`venv: "auto"` busca primero `venv` y después `.venv` dentro del proyecto.

Para iniciar AIDYCAI sin PowerShell, haz doble clic en `AIDYCAI.bat`.

Para detener aplicaciones en Windows, AIDYCAI termina el árbol completo de procesos para evitar que Flask, workers o túneles hijos queden persistentes.
