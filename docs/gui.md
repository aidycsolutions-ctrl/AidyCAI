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

En Windows, si descargaste el repositorio desde GitHub, ejecuta **Preparar_AIDYCAI.bat** una vez. Prepara el entorno e instala la GUI y crea AIDYCAI.lnk en el Escritorio con el icono del proyecto. El acceso directo vuelve a funcionar mientras el repositorio permanezca en la ubicación donde lo descargaste.

Al pulsar **Ejecutar**, AIDYCAI prepara un entorno Python separado por proyecto en %LOCALAPPDATA%\AIDYCAI\environments. Instala las dependencias de requirements.txt o de [project].dependencies en pyproject.toml la primera vez y vuelve a prepararlo si cambia el manifiesto. No crea .venv ni instala paquetes dentro de la carpeta original del proyecto. Si el proyecto no incluye ninguno de esos manifiestos, se crea el entorno vacío y AIDYCAI lo indica en el registro.

La GUI permite:

- seleccionar proyectos registrados;
- buscar repositorios Git en una carpeta elegida y agregarlos al registro;
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

## Encontrar proyectos descargados

Usa **Buscar proyectos en carpeta** en la barra lateral y elige la carpeta que contiene tus repositorios. AIDYCAI revisa esa carpeta y sus subcarpetas directas, incluyendo repositorios con un directorio o archivo \`.git\` (como los worktrees de Git). Puedes seleccionar varios y agregarlos juntos. La búsqueda no recorre carpetas profundas, entornos virtuales ni directorios de dependencias.

En un computador nuevo, descarga o clona tus repositorios en la carpeta que prefieras y repite este proceso. El registro de AIDYCAI es local al computador; agregar un proyecto solo guarda su ruta y no copia ni modifica sus archivos.

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
