# Descripción para el currículum

## Versión breve

**LFM — Plataforma personal de análisis para LaLiga Fantasy**
Python · PostgreSQL · SvelteKit · TypeScript · Docker · GitHub Actions

PWA con pipeline de datos, recomendaciones explicables de compra y optimización del once entre siete formaciones. Incluye históricos, simulador de fichajes, pruebas de integración, control de consumo y demo reproducible con datos deportivos reales.

Repositorio: https://github.com/Braisdlim/lfm-fantasy

## Tres puntos técnicos

- Recogida y normalización de API/HTML en PostgreSQL, conservando evidencia y separando transacciones de colección y análisis.
- Modelos y reglas en Python con razones numéricas, incertidumbre, restricciones de saldo y disponibilidad; web que consulta resultados preparados.
- Consultas por lotes, caché verificada y protección ante cuotas; CI con PostgreSQL y demo Docker con datos reales fechados y una liga de ejemplo.

## Para una entrevista

Explica una decisión concreta: por qué guardar el crudo, cómo evitar que un análisis fallido borre una captura, por qué un percentil de pujas ganadoras no es una probabilidad de éxito, o cómo medir transferencia SQL antes de optimizar.

Sé preciso con el alcance: es una herramienta de un propietario. No tiene aún cuentas multiusuario independientes ni una validación predictiva reproducible con los datos de la demo. El repositorio diferencia el proyecto operativo privado de su edición pública revisada.
