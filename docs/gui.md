# GUI

La primera GUI de AIDYCAI es una capa de presentación sobre el Core existente.

## Instalación

```powershell
pip install -e ".[gui]"
```

Para desarrollo:

```powershell
pip install -e ".[dev,gui]"
```

## Ejecución

```powershell
aidycai gui
```

La GUI permite:

- seleccionar proyectos registrados;
- consultar el Context Engine;
- buscar en FTS5;
- indexar un proyecto;
- ver/exportar ContextBundles;
- abrir el primer archivo seleccionado con el editor predeterminado.

La GUI no modifica archivos de proyectos y no ejecuta comandos arbitrarios.

## Arquitectura

```text
GUI
 │
 ├── ProjectRegistry
 ├── IndexService
 └── ContextEngine
       │
       └── SQLite / filesystem
```

Cada operación de fondo abre un `AppContext` independiente para no compartir la conexión SQLite de la ventana principal entre hilos.

## Conversaciones y legibilidad

La GUI permite mantener varias conversaciones abiertas en la misma ventana. `+ Nueva conversación`
crea un contexto independiente y la lista lateral permite volver a cualquiera de las conversaciones
anteriores sin perder su consulta, resultados de búsqueda ni último `ContextBundle`.

La interfaz usa una paleta explícita de alto contraste para modo claro/oscuro: fondos neutros,
texto principal oscuro/claro, controles secundarios contrastados y azul reservado para acciones
principales. Esto evita depender de los grises predeterminados de CustomTkinter.

Las conversaciones son actualmente de sesión: se conservan mientras la ventana está abierta.

## V9: indexación visible y recuperación automática

La GUI muestra el progreso de indexación por etapas (`scan`, `prepare`, `analyze`, `graph`, `done`) y el archivo que se está procesando cuando está disponible.

Si se consulta un proyecto que todavía no tiene índice, la GUI inicia la indexación automáticamente y continúa con la construcción del contexto al terminar.

Las operaciones de fondo comparten un único estado de ocupación para evitar iniciar dos trabajos simultáneamente. Los callbacks de errores capturan la excepción antes de entregarla a Tkinter para evitar el problema de `free variable 'exc'`.
