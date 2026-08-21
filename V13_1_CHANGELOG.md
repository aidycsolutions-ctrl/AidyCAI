# AIDYCAI V13.1

## Objetivo

Corregir la resolución automática del símbolo inicial cuando una pregunta abierta contiene una acción y un objeto concreto.

## Cambios

- Se separan determinísticamente los términos del objeto de los términos de acción.
- La inferencia de flujo pondera mucho más la coincidencia del objeto solicitado en el nombre del símbolo.
- Se evita que módulos genéricos como `EnviarCompras.py` o `EnviarNotas.py` ganen una pregunta sobre retiros solo por contener `enviar`.
- El análisis expone `subject_terms` para el diagnóstico y el futuro handoff a IA externa.
- Se mantienen intactos el ranking general, Context Engine semántico, GUI y lógica de negocio.

## No incluido

- No conexión con proveedores de IA.
- No modificaciones de archivos de los proyectos indexados.
- No cambios específicos para `sales.html`.
