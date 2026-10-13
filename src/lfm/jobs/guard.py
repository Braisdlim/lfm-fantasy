"""Evitar repetir trabajo cuando se programan varios intentos del mismo job.

El cron de GitHub Actions **no es puntual y se salta disparos**. Medido en este repo: el job diario
previsto a las 18:30 arrancó a las 21:18 (+169 min), y de los disparos horarios del job ligero
llegaron 2 de los 14 esperados entre el 8 y el 9 de septiembre.

La respuesta no es pedirle puntualidad, que no depende de nosotros, sino **programar más intentos**.
Eso solo es viable si los intentos de sobra son gratis: de ahí este guardián. El primer intento que
llega hace el trabajo y los demás salen sin gastar ni una petición a la API, que es lo que protege
el presupuesto de 50-100 peticiones al día de la regla 3 de CLAUDE.md.

Se aplica solo cuando lo pide quien invoca (`--skip-if-recent`), así que un `workflow_dispatch`
manual sigue ejecutando siempre.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

SQL_LAST_OK_DAILY = text(
    "SELECT max(started_at) FROM job_runs "
    "WHERE job = 'daily' AND status = 'ok' "
    "  AND COALESCE((summary->>'market_rotated')::boolean, true) = true "
    "  AND started_at > now() - CAST(:window AS interval)"
)

SQL_LAST_OK_OTHER = text(
    "SELECT max(started_at) FROM job_runs "
    "WHERE job = :job AND status = 'ok' AND started_at > now() - CAST(:window AS interval)"
)


def recently_done(conn: Connection, job: str, *, minutes: int) -> datetime | None:
    """Cuándo arrancó la última pasada correcta, si fue hace menos de `minutes`. Si no, `None`.

    Para el job diario, solo cuenta como completado si el mercado efectivamente rotó al nuevo ciclo
    (`market_rotated = true`). Si LaLiga iba con retraso a las 19:38, no bloquea el intento de las 20:27.
    """
    sql = SQL_LAST_OK_DAILY if job == "daily" else SQL_LAST_OK_OTHER
    return conn.execute(sql, {"job": job, "window": f"{minutes} minutes"}).scalar()
