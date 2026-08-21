# Datos y esquema (Fase 1)

## Directorio de datos

AIDYCAI no escribe índices, SQLite ni logs dentro de OneDrive.

- Código: `Documents\AIDYCAI`
- Datos: `%LOCALAPPDATA%\AIDYCAI`

Override: `AIDYCAI_DATA_DIR`. El seed automático se omite con `AIDYCAI_SKIP_SEED=1`.

## SQLite

Archivo: `%LOCALAPPDATA%\AIDYCAI\database\aidycai.sqlite`

Versión de esquema: `1` (tabla `schema_migrations`).

### `projects`

| Columna | Tipo | Notas |
|---|---|---|
| id | TEXT PK | slug del nombre (`AIDYC` → `aidyc`) |
| name | TEXT UNIQUE NOCASE | nombre visible |
| path | TEXT UNIQUE | ruta absoluta original |
| active | INTEGER 0/1 | activar/desactivar |
| created_at | TEXT | UTC ISO-8601 |
| updated_at | TEXT | UTC ISO-8601 |

### `project_settings`

| Columna | Tipo | Notas |
|---|---|---|
| project_id | TEXT PK, FK CASCADE | |
| key | TEXT PK | p.ej. `excludes` |
| value | TEXT | JSON u otro texto |

Eliminar un registro borra settings por `ON DELETE CASCADE`. No borra la carpeta del proyecto original.

## Evolución

Tablas futuras (tareas, memoria, context bundle) deben entrar como migraciones nuevas. El índice de código vive en un SQLite **por proyecto**: `projects/<id>/index.sqlite`. Ver [index.md](index.md).
