# AIDYCAI

Capa local de inteligencia para desarrollo de software. No es un clon de Cursor.

La Fase 1 registra proyectos. La Fase 2 construye un índice local (SQLite + AST de Python + FTS5) para buscar código sin tokens ni LLM.

## Requisitos

- Windows (desarrollado y probado en Windows 11)
- Python 3.12

## Instalación

Desde `Documents\AIDYCAI`:

```text
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Ubicación de datos

El código fuente permanece en:

```text
Documents\AIDYCAI
```

Los datos generados van a `%LOCALAPPDATA%\AIDYCAI` (fuera de OneDrive):

```text
%LOCALAPPDATA%\AIDYCAI\
├── database\aidycai.sqlite
├── projects\<id>\index.sqlite
├── logs\
└── cache\
```

Para tests o una instalación alternativa:

```text
set AIDYCAI_DATA_DIR=C:\ruta\temporal
set AIDYCAI_SKIP_SEED=1
```

## Proyectos registrados por defecto

En el primer arranque (si el registro está vacío) se intentan registrar estas rutas reales:

| Nombre | Ruta |
|---|---|
| AIDYC | `Documents\Aidyc` |
| AIDYCWeb | `Documents\AidyCWeb\AidyC-web` |
| catalog-studio | `Documents\Deuna\catalog-studio` |
| deunacolombia | `Documents\Deuna\deunacolombia` |

Registrar o borrar un proyecto **nunca** copia ni elimina esas carpetas.

## Comandos

```text
aidycai project list
aidycai project info AIDYC
aidycai project add MiProyecto C:\ruta\original
aidycai project add MiProyecto C:\ruta\original --exclude uploads
aidycai project remove MiProyecto
aidycai project enable AIDYC
aidycai project disable AIDYC
aidycai project set-path AIDYC C:\nueva\ruta
aidycai system info
aidycai index AIDYC
aidycai index --all
aidycai index info AIDYC
aidycai search AIDYC "factura"
aidycai context AIDYC "¿Dónde se calcula el total de una factura?"
aidycai context AIDYC "¿Dónde se calcula el IVA?" --output context.json
```

La primera `index` analiza. La segunda, sin cambios en disco, debe reportar casi todos los archivos **sin cambios**.

Más detalle: [docs/index.md](docs/index.md) y [docs/context.md](docs/context.md).

La primera `index` analiza. La segunda, sin cambios en disco, debe reportar casi todos los archivos **sin cambios**.

Más detalle: [docs/index.md](docs/index.md).

Ejemplo:

```text
aidycai project list
aidycai project info AIDYC
```

## Estructura del código

```text
AIDYCAI/
├── pyproject.toml
├── README.md
├── docs/
├── src/aidycai/
│   ├── domain/            reglas y modelos
│   ├── application/       registro, índice, context engine
│   ├── infrastructure/    SQLite, scanner, AST Python, FTS5
│   └── cli/               Typer
└── tests/
```

El Core no importa Cursor, OpenAI, Anthropic, Ollama ni ningún SDK de LLM.

## Tests

```text
pytest
```

## Exclusiones del scanner

Por defecto ignora `.git`, `.venv`, `node_modules` y `__pycache__`. Cada proyecto puede añadir exclusiones extra (AIDYCWeb incluye `uploads`).
