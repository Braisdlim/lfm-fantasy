"""Análisis: features, reglas y recomendaciones.

Principio (CLAUDE.md regla 5): toda recomendación devuelve `reasons: list[Reason]` con
código, texto, valor numérico y fuente. Nada de texto libre sin cifra detrás.

Módulos previstos:
- trends.py      variación de valor 1/3/7/30 d, aceleración, giros de tendencia
- cash.py        saldo estimado por rival desde league_activity (100 M + ingresos − gastos)
- clauses.py     cláusulas en riesgo (mías) y clausulables (ajenas) cruzadas con cash.py
- lineup.py      once propuesto con p_start y xpts externas (nunca por fecha del partido)
- alerts.py      genera filas en `alerts` con dedupe_key
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    code: str  # p. ej. 'value_drop_3d'
    text: str  # 'Ha bajado 1,2 M en 3 días'
    value: float | None = None
    source: str = "lfm"  # 'lfm' | 'analiticafantasy' | 'futbolfantasy' | 'manual_tier'
