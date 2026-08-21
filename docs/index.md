# Índice de proyecto (Fase 2)

AIDYCAI guarda un SQLite por proyecto, fuera de OneDrive:

```text
%LOCALAPPDATA%\AIDYCAI\projects\<id>\index.sqlite
```

El registro global sigue en `%LOCALAPPDATA%\AIDYCAI\database\aidycai.sqlite`.

## Comandos

```text
aidycai index AIDYC
aidycai index --all
aidycai index info AIDYC
aidycai search AIDYC "factura"
```

La primera indexación analiza archivos de código/texto. La segunda, si no hubo cambios de tamaño/mtime, no vuelve a leer ni a parsear esos archivos.

## Incrementalidad

1. Recorre el árbol respetando exclusiones.
2. Si `size` y `mtime` coinciden con el índice, el archivo se marca *sin cambios*.
3. Si no, se calcula SHA-256. Si el hash es igual, solo se actualizan metadatos.
4. Hash distinto → se reanaliza (AST en Python, FTS en texto/código).
5. Un archivo nuevo y uno eliminado con el **mismo hash único** se tratan como rename.

No hay watcher en esta fase.

## AST (solo Python)

Usa `ast` de la stdlib. Extrae imports, clases, funciones, métodos, constantes en MAYÚSCULAS y decoradores. No resuelve tipos ni semántica.

## FTS5

SQLite FTS5 indexa rutas, contenido de texto/código y nombres/qualified names de símbolos. Ranking con `bm25`. No hay embeddings.

## Exclusiones

Por defecto: `.git`, `.venv`, `node_modules`, `__pycache__`, más las del proyecto (`uploads` en AIDYCWeb).

Los binarios (imágenes, `.pyc`, PDF, etc., o bytes nulos) se registran como `binary` pero no se analizan como código.

## Limitaciones

- No hay parsers de JS/HTML/CSS; esos archivos entran a FTS, no a símbolos.
- Imports dinámicos (`importlib`, `__import__`) no se resuelven.
- No se usa `sys.path` ni paquetes instalados: solo archivos del proyecto.
- `from . import a, b` no crea un grafo perfecto por cada nombre.
- Rename solo si el hash es único a ambos lados.
- Un `.py` con sintaxis inválida queda en error y no aporta símbolos; el resto del proyecto sí se indexa.
