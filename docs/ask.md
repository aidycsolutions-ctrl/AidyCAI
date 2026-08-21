# `aidycai ask`

Modo interactivo de investigación local. No usa LLM.

```powershell
aidycai ask AIDYC
```

Luego escribe preguntas como:

```text
Pregunta: ¿Por qué no aparecen los retiros de efectivo?
Pregunta: ¿Dónde se guardan los retiros?
Pregunta: ¿Qué función imprime los retiros?
```

AIDYCAI muestra un resumen corto de los archivos y símbolos relevantes y prepara el `ContextBundle`.

Comandos dentro de la sesión:

- `exportar`: guarda el último contexto como `context.txt`.
- `ayuda`: muestra los comandos.
- `salir`: termina la sesión.

La salida no intenta responder la pregunta todavía. Esa será la siguiente capa: conectar un proveedor LLM al `ContextBundle`.
