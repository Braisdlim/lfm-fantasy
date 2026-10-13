"""Qué «día de valor» es ahora. Una sola regla para todo el proyecto (2026-09-20).

LaLiga Fantasy cambia los valores de mercado **una vez al día, a las 00:15 hora de Madrid**. Hasta
el 2026-09-20 cada colector etiquetaba sus filas con la fecha UTC del momento de la captura, y eso
fallaba de dos maneras medidas:

- Entre las 00:15 de Madrid y medianoche UTC (22:15-24:00 UTC en verano) una captura trae ya los
  valores del día siguiente pero se guardaba con la fecha de hoy. Pasó el 15/09 a las 23:09 UTC:
  los valores del 16 entraron como del 15.
- La plantilla, releída cada hora, hacía lo mismo: el 19/09 a las 23:11 UTC guardó como «19» el
  valor del 20 de Mathew Ryan (30.291.742, bajando) mientras `player_value_daily` tenía el del 19
  (30.305.156, subiendo). Dos tablas, el mismo día, dos valores.

El día de valor es la fecha de Madrid, contando que el cambio llega a las 00:15. Con un margen:
hasta las 00:20 todavía se considera el día anterior. Y el reloj no basta: el colector de
`/players` comprueba además con el contenido que los valores sean de verdad nuevos
(`lfm.collectors.players.is_stale`).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
UPDATE_AT = (0, 20)  # 00:15 de LaLiga + 5 minutos de margen


def value_day(now: datetime | None = None) -> date:
    """El día cuyos valores de mercado están vigentes en el instante `now` (UTC si no trae zona)."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local = now.astimezone(MADRID)
    if (local.hour, local.minute) < UPDATE_AT:
        return local.date() - timedelta(days=1)
    return local.date()
