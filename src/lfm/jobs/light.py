"""Job ligero: solo lo que cambia durante el día.

    python -m lfm.jobs.light

Tres peticiones habituales a la API (mercado, mi equipo y actividad) frente a las trece del job
completo, más `/players` una vez al día en cuanto LaLiga publica los valores nuevos (00:15 de
Madrid). La cadencia la marca la decisión, no el reloj (docs/plan-app.md §D):

- El **valor de mercado** cambia una sola vez al día, a las 00:15 hora española. Pedirlo cada hora
  sería leer lo mismo, así que este job no lo toca: eso lo hace `lfm.jobs.daily`.
- Lo que sí cambia de forma continua es el **mercado** (pujas, ofertas, plazos, y el ciclo rota a
  la hora de la liga), **mi plantilla** (cláusulas, blindajes, estado de mis jugadores, saldo) y
  la **actividad** (compras y ventas que alteran el saldo rival).

No avisa por Telegram por un fallo suelto: se ejecuta 17 veces al día y perderse una pasada no
cuesta nada. Sí avisa cuando lleva tres seguidas fallando, que ya significa que el mercado no se
está actualizando. El estado de cada pasada queda en `job_runs` y en el propio workflow.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import UTC, datetime

from sqlalchemy import text

from lfm.analysis import cash, eleven, recommend, rivals, watchlist
from lfm.api.client import LaLigaClient
from lfm.collectors import league, players
from lfm.config import settings
from lfm.db.session import engine, save_raw
from lfm.jobs import guard
from lfm.notify import telegram
from lfm.sources import lineups
from lfm.valueday import value_day

SQL_HAS_VALUES = text(
    "SELECT EXISTS (SELECT 1 FROM player_value_daily "
    "WHERE day = CAST(:day AS date) AND source = 'laliga_api')"
)

SQL_MY_TEAM = text("SELECT team_id FROM league_teams WHERE league_id = :league_id AND is_me LIMIT 1")


def my_team_id(conn) -> str | None:
    return conn.execute(SQL_MY_TEAM, {"league_id": settings.league_id}).scalar()


CONSECUTIVE_FAILURES_TO_ALERT = 3

SQL_LAST_RUNS = text(
    "SELECT status FROM job_runs WHERE job = 'light' AND finished_at IS NOT NULL ORDER BY id DESC LIMIT :n"
)


def _notify_if_stuck(error: str | None) -> None:
    """Un fallo suelto de un job que corre 17 veces al día no es noticia; tres seguidos sí.

    Avisar en cada fallo convertiría el canal en ruido y acabarías silenciándolo, que es la peor
    forma de quedarte sin avisos. Como el job ligero solo recoge mercado y plantilla, perderse una
    pasada no cuesta nada: lo que hay que detectar es que **lleva rato sin recogerse**."""
    try:
        with engine().begin() as conn:
            ultimos = conn.execute(SQL_LAST_RUNS, {"n": CONSECUTIVE_FAILURES_TO_ALERT}).scalars().all()
        if len(ultimos) < CONSECUTIVE_FAILURES_TO_ALERT or any(s != "error" for s in ultimos):
            return
        telegram.send(
            f"⚠️ <b>lfm light</b> lleva {CONSECUTIVE_FAILURES_TO_ALERT} pasadas seguidas fallando; "
            f"el mercado no se está actualizando.\n<pre>{(error or '')[-1200:]}</pre>"
        )
    except Exception:  # noqa: BLE001
        print("[telegram] no se pudo avisar del fallo:\n" + traceback.format_exc(), file=sys.stderr)


SKIP_IF_DONE_WITHIN_MIN = 45  # con intentos cada 20 min, deja pasar aproximadamente uno por hora

# Cuánto puede pasar sin una recogida diaria correcta antes de avisar. El diario tiene cuatro
# intentos programados más el reloj de Cloudflare, así que 26 h significa que **han fallado todos**:
# o caducó el refresh token, o Actions dejó de disparar. Estando de viaje es lo único que no se
# arregla solo, y sin este aviso te enterarías al volver.
DAILY_STALE_HOURS = 26
STALE_ALERT_EVERY_HOURS = 12  # no repetirlo cada hora: sería ruido y acabarías silenciándolo

SQL_LAST_DAILY = text("SELECT max(started_at) FROM job_runs WHERE job = 'daily' AND status = 'ok'")

SQL_LAST_STALE_ALERT = text("SELECT max(created_at) FROM alerts WHERE kind = 'daily_stale'")

SQL_SAVE_STALE_ALERT = text(
    "INSERT INTO alerts (kind, dedupe_key, payload, sent_at) "
    "VALUES ('daily_stale', :key, CAST(:payload AS jsonb), now()) "
    "ON CONFLICT (dedupe_key) DO NOTHING"
)


def _notify_if_daily_stale() -> None:
    """Avisa si hace más de un día que no se recoge. Es el único fallo que no se arregla solo."""
    try:
        with engine().begin() as conn:
            ultimo = conn.execute(SQL_LAST_DAILY).scalar()
            if ultimo is None:
                return
            horas = (datetime.now(UTC) - ultimo).total_seconds() / 3600
            if horas < DAILY_STALE_HOURS:
                return
            aviso = conn.execute(SQL_LAST_STALE_ALERT).scalar()
            if aviso and (datetime.now(UTC) - aviso).total_seconds() / 3600 < STALE_ALERT_EVERY_HOURS:
                return
            clave = f"daily_stale:{datetime.now(UTC):%Y-%m-%dT%H}"
            conn.execute(
                SQL_SAVE_STALE_ALERT,
                {"key": clave, "payload": json.dumps({"hours": round(horas, 1)})},
            )
        telegram.send(
            f"⚠️ <b>lfm</b>: hace {horas:.0f} h que no se recoge nada "
            f"(la última vez, el {ultimo:%d/%m a las %H:%M} UTC).\n"
            "Han fallado los cuatro intentos del job diario y el reloj de Cloudflare. "
            "Lo más probable es que haya caducado el acceso a LaLiga."
        )
    except Exception:  # noqa: BLE001
        print("[telegram] no se pudo avisar del atasco:\n" + traceback.format_exc(), file=sys.stderr)


SQL_SAVE_VALUES_ALERT = text(
    "INSERT INTO alerts (kind, dedupe_key, payload, sent_at) "
    "VALUES ('values_missing', :key, CAST(:payload AS jsonb), now()) "
    "ON CONFLICT (dedupe_key) DO NOTHING"
)
VALUES_ALERT_AFTER_HOUR = 9  # hora de Madrid a partir de la cual faltar los valores ya es un fallo


def _notify_if_values_missing(day) -> None:
    """LaLiga cambia los valores a las 00:15. Si a media mañana seguimos sin ellos, el reloj está
    parado: sin esto, la app enseña los de ayer todo el día y parece que funciona."""
    try:
        from datetime import datetime as _dt

        from lfm.valueday import MADRID

        if _dt.now(MADRID).hour < VALUES_ALERT_AFTER_HOUR:
            return
        with engine().begin() as conn:
            if conn.execute(SQL_HAS_VALUES, {"day": day.isoformat()}).scalar():
                return
            conn.execute(
                SQL_SAVE_VALUES_ALERT,
                {"key": f"values_missing:{day}", "payload": json.dumps({"day": str(day)})},
            )
        telegram.send(
            f"⚠️ <b>lfm</b>: seguimos sin los valores de mercado del {day:%d/%m} "
            "(LaLiga los cambia a las 00:15). La app está enseñando los de ayer."
        )
    except Exception:  # noqa: BLE001
        print(
            "[telegram] no se pudo avisar de los valores que faltan:\n" + traceback.format_exc(),
            file=sys.stderr,
        )


# ¿Ya se hizo la recogida completa del ciclo de mercado que está vivo ahora?
SQL_DAILY_FOR_CYCLE = text(
    "SELECT 1 FROM job_runs WHERE job = 'daily' AND status = 'ok' "
    "  AND summary->'market'->>'cycle_end' = :cycle_end LIMIT 1"
)


def _run_daily_if_pending(cycle_end: str | None) -> dict | None:
    """El diario no depende ya de su propio cron: lo lanza el primer ligero que ve el ciclo nuevo.

    Es lo que hace que el sistema no necesite un reloj puntual para funcionar: GitHub se salta
    disparos, pero basta con que **alguno** llegue después de que el mercado rote. Si ese ciclo ya
    se recogió, no se hace nada y no cuesta ni una petición."""
    if not cycle_end:
        return None
    try:
        with engine().begin() as conn:
            if conn.execute(SQL_DAILY_FOR_CYCLE, {"cycle_end": cycle_end}).first():
                return None
        from lfm.jobs import daily as daily_job

        print(f"[light] el ciclo {cycle_end} aún no tiene recogida completa: lanzando el diario.")
        return daily_job.run(skip_if_recent=False)
    except SystemExit:  # daily sale con código 1 si no pudo recoger nada
        return {"status": "error"}
    except Exception:  # noqa: BLE001
        print("[light] no se pudo lanzar el diario pendiente:\n" + traceback.format_exc(), file=sys.stderr)
        return None


def run(*, skip_if_recent: bool = False) -> dict:
    day = value_day()
    summary: dict = {"day": str(day), "job": "light"}
    if not settings.league_id:
        print(json.dumps({"status": "skipped", "reason": "sin LEAGUE_ID"}))
        return {"status": "skipped"}

    if skip_if_recent:
        with engine().begin() as conn:
            ultimo = guard.recently_done(conn, "light", minutes=SKIP_IF_DONE_WITHIN_MIN)
        if ultimo:
            print(json.dumps({"status": "skipped", "reason": f"ya se recogió a las {ultimo:%H:%M} UTC"}))
            return {"status": "skipped"}

    with engine().begin() as conn:
        run_id = conn.execute(text("INSERT INTO job_runs (job) VALUES ('light') RETURNING id")).scalar_one()
        team_id = my_team_id(conn)

    def on_response(endpoint, params, payload):
        save_raw("laliga_api", endpoint, params, payload)

    # Cada colector en su transacción. El 2026-09-15 el fallo al guardar mi plantilla revirtió el
    # mercado que ya se había leído bien, y por eso la app pasó la tarde con las recomendaciones de
    # las 17:05: no es que no se reintentara, es que no había mercado nuevo del que calcularlas.
    fallos: dict[str, str] = {}

    def recoger(nombre: str, fn):
        try:
            with engine().begin() as conn:
                summary[nombre] = fn(conn)
            return True
        except Exception:  # noqa: BLE001
            fallos[nombre] = traceback.format_exc(limit=3)
            print(f"[recogida] {nombre} falló:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return False

    lid = settings.league_id
    try:
        with LaLigaClient(on_response=on_response) as client:
            recoger("market", lambda c: league.collect_market(client, c, league_id=lid))
            # Los valores cambian a las 00:15 y el diario no pasa hasta las 19:25: durante 19 horas la
            # app enseñaba como «hoy» el cambio de ayer (2026-09-20, Mathew Ryan: +56 k en pantalla
            # cuando ya había bajado 13 k). Una petición más, solo hasta tener los del día.
            with engine().begin() as c:
                tiene = c.execute(SQL_HAS_VALUES, {"day": day.isoformat()}).scalar()
            if not tiene:
                try:
                    with engine().begin() as c:
                        summary["players"] = players.collect_players(client, c, day=day)
                except players.StaleSnapshot as e:
                    summary["players"] = {"stale": str(e)}
                except Exception:  # noqa: BLE001
                    fallos["players"] = traceback.format_exc(limit=3)
            else:
                summary["players"] = {"cached": True}
            if team_id:
                recoger(
                    "squad",
                    lambda c: league.collect_squads(client, c, league_id=lid, team_ids=[team_id], day=day),
                )
            else:
                summary["squad"] = {"skipped": "mi equipo aún no está en league_teams; corre el job diario"}
            recoger("activity", lambda c: league.collect_activity(client, c, league_id=lid))
        error = None
    except Exception:  # noqa: BLE001
        fallos["cliente"] = traceback.format_exc()
        error = traceback.format_exc()

    # Independiente del login de LaLiga y del ciclo de mercado. Si el diario
    # falla parcialmente, el siguiente ligero puede recuperar las titularidades.
    recoger("lineups", lambda c: lineups.refresh(c, day=day))

    if fallos:
        summary["collect_errors"] = sorted(fallos)
        summary["collect_error_details"] = fallos
    # El mercado es lo que da sentido a esta pasada: si se ha guardado, la pasada sirvió.
    status = "ok" if "market" in summary else "error"
    if status == "error" and error is None:
        error = "\n\n".join(f"[{k}]\n{v}" for k, v in fallos.items())

    # Si el mercado ya rotó y nadie ha hecho la recogida completa de este ciclo, se hace aquí.
    mercado = summary.get("market") or {}
    if mercado.get("state") == league.MARKET_OK:
        pendiente = _run_daily_if_pending(mercado.get("cycle_end"))
        if pendiente is not None:
            summary["daily_lanzado"] = {k: pendiente.get(k) for k in ("status", "market_rotated")}

    # Recalcular la recomendación no cuesta ninguna petición y el mercado cambia cada hora, pero va
    # **fuera** de la transacción de la recogida: compartiéndola, un fallo aquí borraba también el
    # mercado que se acababa de leer, y eso se repetiría en las 17 pasadas del día.
    try:
        with engine().begin() as conn:
            summary["recommendations"] = recommend.recompute(
                conn, league_id=settings.league_id, day=day, team_id=team_id
            )
    except Exception:  # noqa: BLE001
        summary["recommendations"] = {"error": True}
        print("[light] no se pudo recalcular la recomendación:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)

    # Plantilla y titularidades pueden cambiar durante el día: el once no espera al diario.
    # Reutiliza fuentes ya guardadas y conserva una transacción independiente.
    if team_id:
        try:
            with engine().begin() as conn:
                summary["eleven"] = eleven.refresh(conn, team_id=team_id, day=day)
        except Exception:  # noqa: BLE001
            summary["eleven"] = {"error": True}
            print("[light] no se pudo recalcular el once:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)

    # Lista de seguimiento: con el mercado y las cláusulas recién leídos. Aislada como el resto del
    # análisis: si falla, la pasada sigue valiendo.
    try:
        with engine().begin() as conn:
            summary["watchlist"] = watchlist.check(conn, league_id=settings.league_id, send=telegram.send)
    except Exception:  # noqa: BLE001
        summary["watchlist"] = {"error": True}
        print("[light] no se pudo revisar la lista de seguimiento:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)

    # Actividad recién leída: el saldo rival no tiene que esperar al diario de la tarde.
    try:
        with engine().begin() as conn:
            summary["cash"] = cash.recompute(conn, league_id=settings.league_id, day=day)
    except Exception:  # noqa: BLE001
        summary["cash"] = {"error": True}
        print("[light] no se pudo recalcular el saldo rival:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)

    # El radar cruza los huecos de cada rival con el mercado, que cambia cada pasada.
    try:
        with engine().begin() as conn:
            summary["rivals"] = rivals.recompute(conn, league_id=settings.league_id, day=day)
    except Exception:  # noqa: BLE001
        summary["rivals"] = {"error": True}
        print("[light] no se pudo recalcular el radar de rivales:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)

    with engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE job_runs SET finished_at = now(), status = :status, "
                "summary = CAST(:summary AS jsonb), error = :error WHERE id = :id"
            ),
            {"status": status, "summary": json.dumps(summary), "error": error, "id": run_id},
        )
    print(json.dumps({"status": status, **summary}, indent=2, ensure_ascii=False))
    # Fuera del if: el caso que hay que detectar es justo que el ligero funcione y el diario no.
    _notify_if_daily_stale()
    _notify_if_values_missing(day)
    if status == "error":
        _notify_if_stuck(error)
        print(error, file=sys.stderr)
        sys.exit(1)
    return summary


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--skip-if-recent",
        action="store_true",
        help="no hacer nada si ya hubo una pasada correcta hace poco (para programar varios intentos)",
    )
    run(**vars(ap.parse_args()))
