# LFM · decisiones explicables para fantasy

[English](README.md) · [Código y pruebas](docs/review.md) · [Arquitectura](docs/architecture.md) · [Capturas](docs/walkthrough.md)

**Proyecto personal full stack para decidir a quién fichar, cuánto pujar y qué once alinear en LaLiga Fantasy.**

Python recoge y analiza datos; PostgreSQL conserva evidencia y resultados; SvelteKit presenta recomendaciones con motivos numéricos, restricciones de saldo e incertidumbre.

**Python · PostgreSQL · SvelteKit · TypeScript · Docker · GitHub Actions**

## Tres problemas de ingeniería

| Problema | Solución | Evidencia |
| --- | --- | --- |
| Las lecturas históricas repetidas agotaron la cuota de transferencia | Consultas por lotes y cachés verificadas contra cambios de origen | [Caso de ingeniería](docs/engineering.md); [prueba PostgreSQL](tests/test_journal_batch.py) con resultados equivalentes y seis lecturas tanto para 4 como para 200 operaciones |
| El once debe respetar bajas y reglas del juego | Comparación de siete formaciones para la próxima jornada, conservando la incertidumbre | [Código](src/lfm/analysis/eleven.py), [pruebas de formaciones](tests/test_eleven.py) y [horizonte de una jornada](tests/test_fixtures_points.py) |
| Un cálculo fallido no debe borrar datos recién recogidos | Transacciones separadas y aislamiento de pasos de análisis | [Orquestación](src/lfm/jobs/light.py) y [pruebas de fallos](tests/test_light.py) |

![Once sugerido calculado con datos deportivos reales en una liga de ejemplo](docs/screenshots/eleven.png)

[Ver recomendaciones, históricos y simulador de fichajes →](docs/walkthrough.md)

## Probar la demo

Con Docker y Compose instalados:

```bash
git clone https://github.com/Braisdlim/lfm-fantasy.git
cd lfm-fantasy
docker compose up --build
```

Abre **http://localhost:5173**. Utiliza datos deportivos reales del **13/10/2026** y una liga de ejemplo. No necesita cuentas ni claves. Permite explorar y simular fichajes; los cambios de la web no se guardan. [Arranque y solución de problemas](docs/setup.md).

## Revisar por dentro

- [Arquitectura](docs/architecture.md): flujo de datos, módulos y responsabilidades.
- [Decisiones](docs/decisions.md): alternativas consideradas y sus costes.
- [Código y pruebas](docs/review.md): ejemplos concretos y qué verifica cada comprobación.
- [CI](https://github.com/Braisdlim/lfm-fantasy/actions/workflows/ci.yml): PostgreSQL, web, compilación, acceso, demo y cobertura; CodeQL y escaneo de secretos complementan las pruebas.

El alcance actual es de un propietario. Los pronósticos son estimaciones y la demo no demuestra precisión predictiva. La documentación técnica está en inglés; la interfaz conserva el español. El desarrollo ha utilizado asistencia de IA para implementación, investigación y documentación.

La instancia operativa permanece privada. [Procedencia de datos y condiciones de publicación](docs/publication.md); el repositorio no tiene actualmente una licencia de código abierto.
