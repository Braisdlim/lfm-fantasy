# LFM · decisiones explicables para fantasy

[English](README.md) · [Revisión en 5 minutos](docs/review.md) · [Arquitectura](docs/architecture.md) · [Arranque](docs/setup.md)

Proyecto personal full stack: una PWA que ayuda a decidir **a quién fichar, cuánto pujar y qué once alinear en la próxima jornada**. Python calcula; PostgreSQL conserva datos y resultados; SvelteKit presenta cifras, motivos y límites.

Para revisar el proyecto, empieza por el [recorrido de código y pruebas](docs/review.md) y las [decisiones de arquitectura](docs/decisions.md). La documentación técnica principal está en inglés; la interfaz conserva el español de la aplicación original.

![Pantalla de inicio con jugadores reales en una liga de ejemplo](docs/screenshots/home.png)

## Probarlo

Necesitas Docker y Compose. No necesitas cuenta de LaLiga, Neon ni claves:

```bash
git clone https://github.com/Braisdlim/lfm-fantasy.git
cd lfm-fantasy
docker compose up --build
```

Abre **http://localhost:5173**. La demo usa una muestra real del **13/10/2026**: **64 jugadores, 20 clubes, 5.107 precios históricos, 486 registros de puntos por jornada y 130 partidos**. Muestra estrellas y jugadores que destacan por puntos respecto a su valor. Tres equipos de ejemplo permiten probar el backend y simular fichajes.

Jugadores, clubes, precios, puntos y calendario son reales. Mánagers, saldos, pujas, cláusulas y operaciones pertenecen a una liga de ejemplo. La fecha y las fuentes se indican en la interfaz y la documentación. No guarda cambios desde la web; las fotos y escudos usan las URLs públicas originales. La demo funciona sin consultas a Neon ni a las APIs deportivas.

## Qué enseña técnicamente

- Recogida de datos con captura cruda previa a la normalización, contratos y reintentos.
- Recomendaciones deterministas con `reasons[]`, cifras, fuentes y supuestos.
- Optimización del once entre siete formaciones, con bajas y horizonte de una jornada.
- Simulación de varias compras y ventas con saldo y once resultantes.
- Consultas SQL por lotes, caché verificada, peticiones concurrentes agrupadas y protección ante cuota agotada.
- Pruebas unitarias, contratos de adaptadores, integración con PostgreSQL y verificación de la demo en CI.

## Leer el proyecto por dentro

| Documento | Qué explica |
| --- | --- |
| [Arquitectura](docs/architecture.md) | Flujo completo, módulos, tablas y responsabilidades |
| [Backend y modelos](docs/criterio.md) | Cómo decide, qué mide y qué sigue siendo un supuesto |
| [Despliegue](docs/deployment.md) | Python/Actions, PostgreSQL/Neon, web/Vercel y secretos |
| [Nuevos usuarios](docs/users.md) | Instancias aisladas hoy y cambios necesarios para un servicio compartido |
| [Caso de ingeniería](docs/engineering.md) | Incidencia de cuota, diagnóstico y optimizaciones comprobadas |
| [Recorrido con capturas](docs/walkthrough.md) | Inicio, mercado, plantilla, jugador y simulador |

La edición pública parte de una aplicación utilizada en privado. Tiene una historia Git nueva y no incluye las notas de la liga, credenciales ni capturas privadas. Las capturas muestran la demo funcionando con datos deportivos reales fechados.

El alcance es de **un único propietario**. No existe todavía registro de usuarios ni aislamiento multiusuario. Los pronósticos no garantizan resultados deportivos y la demo con liga de ejemplo no sirve como validación predictiva. Estas limitaciones también se documentan: forman parte del proyecto que se puede explicar en una entrevista.
