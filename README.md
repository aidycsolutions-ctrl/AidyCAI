# AIDYCAI

AIDYCAI es el centro local de análisis, ejecución y gestión de los proyectos de desarrollo asociados a AIDYC.

## Estado actual

Esta versión incluye:

- Análisis causal determinista V14, V15, V16 y V16.1.
- `EvidenceRecord` y `AIHandoff v1`.
- Trazado causal de lector SQL → escritor SQL → símbolo determinante.
- Gestión de proyectos mediante configuración editable.
- Ejecución de proyectos desde la interfaz.
- Detención de procesos y procesos hijos en Windows.
- Apertura automática del navegador para proyectos web.
- Publicación Git/GitHub.
- Deploy mediante SSH cuando el proyecto lo tenga configurado.
- Recarga/reindexación.
- Preparación para compilación mediante GitHub Actions.
- Exploración y gestión centralizada de proyectos.

## Proyectos gestionados

La configuración de los proyectos NO está escrita directamente en el código.

Se encuentra en:

```text
config/projects.json
```

Esto permite cambiar rutas, comandos, entornos virtuales, URLs y capacidades sin modificar AIDYCAI.

Ejemplo conceptual:

```json
{
  "name": "AIDYCWeb",
  "path": "C:\ruta\del\proyecto",
  "python": "venv",
  "command": "python Aidyc_app.py",
  "url": "http://127.0.0.1:5000"
}
```

## Entornos virtuales

Para cada proyecto se puede indicar el entorno virtual que debe utilizarse.

AIDYCAI debe ejecutar directamente el `python.exe` del entorno virtual cuando esté configurado.

Por ejemplo:

```text
venv\Scripts\python.exe
```

o:

```text
.venv\Scripts\python.exe
```

No es necesario activar manualmente el entorno mediante PowerShell para ejecutar el proyecto desde AIDYCAI.

## Ejecutar proyectos

Desde la interfaz:

```text
▶ EJECUTAR
```

AIDYCAI inicia el comando configurado utilizando el entorno virtual del proyecto.

Para aplicaciones web configuradas con una URL, AIDYCAI espera a que el servidor esté disponible y puede abrir automáticamente el navegador.

## Detener proyectos

El botón:

```text
■ DETENER
```

termina el proceso del proyecto y, en Windows, su árbol de procesos.

Esto es especialmente importante para aplicaciones Flask/Werkzeug que pueden crear procesos hijos mediante el reloader.

La detención se ejecuta sin bloquear la interfaz principal de AIDYCAI.

Después de detener un proyecto, debe ser posible volver a utilizar:

```text
▶ EJECUTAR
```

sin cerrar AIDYCAI.

## Navegador

Las aplicaciones web pueden tener una URL configurada en `projects.json`.

Ejemplo:

```text
http://127.0.0.1:5000
```

AIDYCAI puede abrir esa dirección una vez que el servidor esté disponible.

## Publicación

Las operaciones Git se gestionan desde AIDYCAI utilizando la configuración del proyecto.

Las operaciones pueden incluir:

- comprobar cambios;
- guardar temporalmente cambios locales cuando corresponda;
- sincronizar con `origin/main`;
- commit;
- push.

## Deploy

Los proyectos que tengan deploy configurado pueden ejecutar el servicio SSH correspondiente.

Los proyectos sin deploy deben permanecer configurados como:

```text
deploy: false
```

No se deben introducir credenciales directamente en el código.

## GitHub Actions

AIDYCAI puede consultar un workflow configurado en GitHub y solicitar su ejecución cuando el proyecto tenga esa capacidad.

Las credenciales de GitHub deben proporcionarse mediante variables de entorno, por ejemplo:

```text
GITHUB_TOKEN
```

No guardar tokens dentro de `projects.json` ni dentro del código fuente.

## Análisis causal

El motor V16.1 permite continuar una cadena causal desde una lectura SQL hacia sus escritores cuando la relación puede resolverse determinísticamente.

Ejemplo:

```text
VisualizacionValores.__init__
    ↓
cargar_datos
    ↓
obtener_valores_ultimo_turno
    ↓
SQL_READ: Retiros_Caja
    ↓
SQL_WRITE: RegistrarRetiro.guardar_retiro
    ↓
TurnoService.obtener_turno_actual
```

Cuando existen varios escritores candidatos sin una resolución determinista, AIDYCAI no debe elegir arbitrariamente.

La cadena debe quedar como ambigua o no resuelta según corresponda.

## Compatibilidad

Las versiones V14, V15 y V16 existentes deben conservar su compatibilidad.

Los bundles anteriores deben poder seguir siendo procesados cuando no contengan información introducida posteriormente.

AIHandoff v1 mantiene su contrato de compatibilidad.

## Proyectos externos

AIDYCAI analiza y gestiona proyectos externos, pero sus cambios deben realizarse únicamente cuando el usuario los solicite explícitamente.

La implementación de AIDYCAI no debe modificar automáticamente:

- AIDYC
- AIDYCWeb
- Deuna

## Inicio de AIDYCAI

En Windows puede utilizarse el archivo:

```text
AIDYCAI.bat
```

para iniciar la aplicación sin tener que abrir PowerShell manualmente.

También puede ejecutarse desde el entorno virtual de AIDYCAI:

```powershell
cd "$HOME\OneDrive\Documents\AIDYCAI"
.\.venv\Scripts\Activate.ps1
pip install -e ".[gui]"
aidycai gui
```

## Estructura conceptual

```text
AIDYCAI/
├── config/
│   └── projects.json
├── aidycai/
│   ├── causal_v14.py
│   ├── causal_v15.py
│   ├── causal_v16.py
│   ├── causal_v16_1.py
│   ├── evidence.py
│   ├── ai_handoff.py
│   ├── indexer.py
│   ├── services/
│   ├── infrastructure/
│   └── ui/
├── tests/
├── main.py
└── AIDYCAI.bat
```

## Principios del proyecto

1. AIDYCAI debe trabajar de forma determinista siempre que sea posible.
2. No utilizar LLM, embeddings ni búsquedas laterales para resolver relaciones que ya pueden determinarse mediante el índice.
3. Mantener evidencia verificable de cada salto causal.
4. No seleccionar arbitrariamente entre candidatos ambiguos.
5. Mantener límites explícitos de profundidad y símbolos.
6. Mantener compatibilidad con versiones anteriores.
7. Mantener los proyectos externos aislados de las modificaciones de AIDYCAI.
8. Mantener las rutas, comandos y capacidades de los proyectos editables mediante configuración.
9. Evitar credenciales almacenadas en el código o archivos de configuración.
10. Las operaciones de ejecución, publicación y deploy deben poder controlarse desde una única interfaz.

## Próxima evolución

La evolución prevista del proyecto es convertir AIDYCAI progresivamente en un workspace de desarrollo integrado, incorporando:

- explorador de archivos;
- editor de código;
- búsqueda dentro de proyectos;
- integración directa entre editor y análisis causal;
- visualización de EvidenceRecord;
- generación de contexto para IA;
- navegador integrado para herramientas web de desarrollo;
- workflow centralizado de ejecutar, detener, publicar, deploy y compilar.

Estas funciones deben añadirse de forma incremental sin comprometer la estabilidad de V14/V15/V16/V16.1.
