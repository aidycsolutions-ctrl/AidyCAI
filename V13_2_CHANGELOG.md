# AIDYCAI V13.2

## Objetivo

Completar la resolución del flujo dirigido después de que V13.1 ya identifica correctamente el símbolo inicial a partir de acción + objeto.

## Cambios

- El resolver de llamadas ahora puede resolver métodos `self.metodo()` dentro de la misma clase sin confundir métodos homónimos de otras clases.
- Las llamadas calificadas como `Clase.metodo()` dentro del mismo archivo reciben resolución local antes del fallback global.
- Las investigaciones conductuales automáticas siguen una cadena saliente determinista aunque no exista un terminal explícito en la pregunta.
- El recorrido automático se detiene ante bifurcaciones para no inventar una ruta.
- Las llamadas salientes que no pueden resolverse se registran como `no resuelta` en lugar de desaparecer silenciosamente.
- Los terminales fuertes detectados durante un flujo automático se conservan como evidencia aunque el usuario no haya solicitado explícitamente un terminal.
- Se mantienen las reglas conservadoras: las llamadas ambiguas no se resuelven por adivinación.

## Pruebas nuevas

- Resolución de `self.metodo()` con métodos homónimos en clases distintas.
- Reporte explícito de llamadas salientes no resueltas.
- Verificación de terminal HTTP detectado al final de un flujo automático.

## No incluido

- No integración con proveedores de IA.
- No cambios de ranking general.
- No cambios de GUI.
- No cambios de Context Engine semántico fuera del resolver de flujo.
- No modificaciones de archivos de los proyectos indexados.
- No cambios específicos para `sales.html`.
