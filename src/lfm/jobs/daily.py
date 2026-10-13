"""Job diario: se ejecuta tras la renovación del mercado de la liga.

    python -m lfm.jobs.daily [--dry-run [--save-fixture]] [--full-activity]

Orden: players → me → standing → squads → activity → market → calendar → saldo rivales →
alineaciones probables → recomendaciones → avisos por Telegram.
Unas 13 peticiones a la API por ejecución. Registra la ejecución en job_runs y avisa por Telegram
si falla.

`--dry-run` no toca la BD: pide players, standing, una plantilla, market y activity/0, imprime un
resumen de cada respuesta y vuelca el crudo a `.raw/` (ignorado por git; regla 2 sin base de datos).
Con `--save-fixture` además escribe `tests/fixtures/<nombre>.json` anonimizados (ver lfm.fixtures).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from lfm import fixtures
from lfm.analysis import alerts, bargains, calibration, cash, eleven, journal, rebound, recommend, rivals
from lfm.analysis import fixtures as forecast
from lfm.api.client import LaLigaClient
from lfm.collectors import calendar, league, players
from lfm.config import settings
from lfm.db.session import engine, save_raw
from lfm.jobs import guard
from lfm.notify import telegram
from lfm.sources import lineups
from lfm.valueday import value_day

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = REPO_ROOT / ".raw"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def _envelope(data: Any) -> str:
    if isinstance(data, list):
        return "list"
    if isinstance(data, dict):
        return f"dict{sorted(data)}"
    return type(data).__name__


def dry_run(*, save_fixture: bool = False) -> dict:
    """Recoge cada endpoint una vez, lo describe y lo vuelca a .raw/ sin base de datos."""
    day = value_day()
    RAW_DIR.mkdir(exist_ok=True)
    endpoints_seen: list[str] = []

    def on_response(endpoint: str, params: dict | None, payload: Any) -> None:
        endpoints_seen.append(endpoint)
        name = endpoint.strip("/").replace("/", "_")
        (RAW_DIR / f"{day}_{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    captured: dict[str, tuple[str, Any]] = {}  # nombre lógico → (endpoint, payload)

    def grab(name: str, fetch) -> Any:
        payload = fetch()
        captured[name] = (endpoints_seen[-1] if endpoints_seen else name, payload)
        return payload

    summary: dict = {"dry_run": True, "day": str(day), "raw_dir": str(RAW_DIR)}
    with LaLigaClient(on_response=on_response) as client:
        data = grab("players", client.players)
        items = players.extract_list(data)
        summary["envelope"] = _envelope(data)
        summary["players"] = players.summarize(items)
        summary["sample_rows"] = [players.normalize_player(p) for p in items[:3]]
        if settings.league_id:
            lid = settings.league_id
            standing = league.normalize_standing(grab("standing", lambda: client.standing(lid)))
            summary["standing"] = [
                {k: r[k] for k in ("position", "team_id", "manager_name", "points", "team_value")}
                for r in standing
            ]
            if standing:
                sq = league.normalize_squad(grab("team", lambda: client.team(lid, standing[0]["team_id"])))
                summary["team"] = {
                    "team_id": sq["team"]["team_id"],
                    "players": len(sq["players"]),
                    "clubs": len(sq["clubs"]),
                    "week_stats": len(sq["week_stats"]),
                    "shielded": sum(1 for p in sq["players"] if p["is_shielded"]),
                }
            market = [
                league.normalize_market(i)
                for i in players.extract_list(grab("market", lambda: client.market(lid)))
            ]
            summary["market"] = {"players": len(market), "kinds": dict(Counter(m["kind"] for m in market))}
            activity = [
                league.normalize_activity(i)
                for i in players.extract_list(grab("activity", lambda: client.activity(lid, 0)))
            ]
            summary["activity"] = {
                "items": len(activity),
                "types": dict(Counter(a["activity_type"] for a in activity)),
            }

    if save_fixture:
        summary["fixtures"] = {}
        for name, (endpoint, payload) in captured.items():
            meta = {
                "source": "laliga_api",
                "endpoint": endpoint,
                "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "total_items": fixtures.count_items(payload),
                "anonymized": True,
                "note": "Muestra real anonimizada con lfm.fixtures. "
                "Regenerar: python -m lfm.jobs.daily --dry-run --save-fixture",
            }
            sample = fixtures.Anonymizer().anonymize(fixtures.sample_for(name, payload))
            summary["fixtures"][name] = str(
                fixtures.write_fixture(FIXTURES_DIR / f"{name}.json", sample, meta)
            )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def _notify(status: str, error: str | None, summary: dict, *, day: date, quiet: bool) -> None:
    """Avisa por Telegram **fuera** de la recogida, y sin poder romperla.

    El 2026-09-08 dos ejecuciones se marcaron como fallidas con todos los datos ya guardados: lo
    que reventó fue componer el mensaje. Un aviso es la última milla, no el trabajo; si falla, se
    imprime y el job sigue siendo un éxito."""
    try:
        if status == "error":
            telegram.send(f"❌ <b>lfm daily</b> falló:\n<pre>{(error or '')[-1500:]}</pre>")
            return
        if quiet or not settings.league_id:
            return
        gaps = [date.fromisoformat(d) for d in summary.get("missing_days") or []]
        if gaps:
            telegram.send(alerts.gap_message(gaps))
        with engine().begin() as conn:
            telegram.send(alerts.daily_message(conn, league_id=settings.league_id, day=day))
    except Exception:  # noqa: BLE001
        print("[telegram] no se pudo componer el aviso:\n" + traceback.format_exc(), file=sys.stderr)


SQL_RECENT_DAILY = text(
    "SELECT status, error FROM job_runs WHERE job = 'daily' AND finished_at IS NOT NULL "
    "ORDER BY id DESC LIMIT 4"
)


def _huella(error: str | None) -> str:
    """La última línea del traceback: identifica el tipo de fallo sin el ruido de las rutas."""
    lineas = [line.strip() for line in (error or "").strip().splitlines() if line.strip()]
    return lineas[-1][:160] if lineas else ""


def _failure_message(error: str | None) -> str:
    """Un fallo suelto se reintenta solo; uno que se repite igual **no se va a arreglar solo**.

    El 2026-09-15 el mismo error tumbó los cinco intentos del día y la app pasó la tarde sin datos.
    Esperar a las 26 h del aviso de atasco fue esperar de más: al segundo intento con la misma
    huella ya se sabía que no era pasajero."""
    cabeza = "❌ <b>lfm daily</b> falló"
    try:
        with engine().begin() as conn:
            previos = conn.execute(SQL_RECENT_DAILY).all()
        huella = _huella(error)
        iguales = 1
        for r in previos:
            if r.status == "error" and _huella(r.error) == huella:
                iguales += 1
            else:
                break
        if iguales >= 2 and huella:
            cabeza = (
                f"🛑 <b>lfm daily</b> falla por {iguales}ª vez seguida con el mismo error: "
                f"<b>no es pasajero y reintentar no lo va a arreglar</b>"
            )
    except Exception:  # noqa: BLE001
        pass
    return f"{cabeza}:\n<pre>{(error or '')[-1400:]}</pre>"


# Cuánto esperar, dentro de la misma ejecución, a que LaLiga publique el mercado nuevo.
#
# LaLiga rota el mercado a las 19:21 pero a veces tarda en publicarlo, y mientras tanto devuelve el
# ciclo viejo ya cerrado o solo las ventas de managers. Antes eso se resolvía «en el siguiente
# intento programado», que llegaba (si llegaba) horas después: la app pasaba la tarde con un
# mercado cerrado y sin recomendaciones. Esperar aquí no depende de ningún reloj externo.
# Cada vuelta es una sola petición, así que el peor caso son 6 peticiones más; y el workflow tiene
# 30 minutos de límite, de ahí los 20 de espera.
MARKET_WAIT_MIN = 20
MARKET_POLL_SECONDS = 240
_sleep = time.sleep  # inyectable en los tests


def wait_for_market(recoger, collect, *, max_wait_min: float = MARKET_WAIT_MIN) -> dict | None:
    """Pide el mercado hasta que venga sano o se acabe la espera. Devuelve el último resumen."""
    deadline = time.monotonic() + max_wait_min * 60
    intentos = 0
    while True:
        intentos += 1
        out = recoger("market", collect)
        state = (out or {}).get("state")
        if out is not None and state == league.MARKET_OK:
            out["attempts"] = intentos
            return out
        if time.monotonic() + MARKET_POLL_SECONDS > deadline:
            if out is not None:
                out["attempts"] = intentos
            return out
        print(
            f"[recogida] mercado no disponible ({(out or {}).get('why') or 'error'}); "
            f"reintento en {MARKET_POLL_SECONDS // 60} min",
            file=sys.stderr,
        )
        _sleep(MARKET_POLL_SECONDS)


# El diario debe correr una vez por ciclo de mercado. Con varios intentos programados tras el
# cierre, el primero que llega hace las 13 peticiones y el resto salen sin gastar ninguna.
SKIP_IF_DONE_WITHIN_MIN = 12 * 60


def run(
    *,
    full_activity: bool = False,
    quiet: bool = False,
    skip_if_recent: bool = False,
    force: bool = False,
) -> dict:
    day = value_day()
    summary: dict = {"day": str(day)}

    if skip_if_recent:
        with engine().begin() as conn:
            ultimo = guard.recently_done(conn, "daily", minutes=SKIP_IF_DONE_WITHIN_MIN)
        if ultimo:
            print(json.dumps({"status": "skipped", "reason": f"ya se recogió a las {ultimo:%H:%M} UTC"}))
            return {"status": "skipped"}

    with engine().begin() as conn:
        run_id = conn.execute(text("INSERT INTO job_runs (job) VALUES ('daily') RETURNING id")).scalar_one()

    def on_response(endpoint, params, payload):
        save_raw("laliga_api", endpoint, params, payload)

    # --- 1. Recogida ---------------------------------------------------------------------------
    #
    # **Cada colector en su propia transacción.** Antes iban todos juntos, y el 2026-09-15 el fallo
    # al guardar las plantillas revirtió el mercado que ya se había leído bien: por eso la app se
    # quedó sin recomendaciones, no porque no se reintentara. Un endpoint roto solo puede costarte
    # lo suyo. Lo que sí se respeta son las dependencias de verdad: sin la clasificación no se sabe
    # a qué equipos pedir la plantilla.
    puestos: set[str] = set()
    fallos: dict[str, str] = {}

    def recoger(nombre: str, fn):
        """Un colector, en su transacción. Devuelve su resultado o None si se rompió."""
        try:
            with engine().begin() as conn:
                out = fn(conn)
            summary[nombre] = out
            return out
        except Exception:  # noqa: BLE001
            fallos[nombre] = traceback.format_exc(limit=3)
            print(f"[recogida] {nombre} falló:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return None

    # Comprobar si ya existen capturas de hoy para no gastar peticiones repetidas
    # en caso de reintento porque el mercado vino con retraso.
    skip_players = False
    skip_lineups = False
    skip_calendar = False
    if not force:
        try:
            with engine().begin() as conn:
                skip_players = bool(
                    conn.execute(
                        text(
                            "SELECT 1 FROM player_value_daily "
                            "WHERE day = :day AND source = 'laliga_api' LIMIT 1"
                        ),
                        {"day": day},
                    ).scalar()
                )
                skip_lineups = not lineups.refresh_due(conn)
                skip_calendar = bool(
                    conn.execute(
                        text("SELECT 1 FROM weeks WHERE fetched_at >= CURRENT_DATE LIMIT 1")
                    ).scalar()
                )
        except Exception:  # noqa: BLE001
            pass

    try:
        with LaLigaClient(on_response=on_response) as client:
            if skip_players:
                print(f"[recogida] players ya tiene datos de hoy ({day}), reutilizando.")
                summary["players"] = {"cached": True}
            else:
                recoger("players", lambda c: players.collect_players(client, c, day=day))

            if settings.league_id:
                lid = settings.league_id
                # **El mercado, lo primero.** Si LaLiga aún no ha rotado, tampoco ha procesado los
                # fichajes del cierre, así que plantillas, saldo y actividad vendrían igual de
                # viejos: se espera aquí a que el ciclo nuevo exista y luego se recoge todo.
                wait_for_market(recoger, lambda c: league.collect_market(client, c, league_id=lid, day=day))
                me = client.me()
                my_manager_id = str(me["id"]) if isinstance(me, dict) and me.get("id") is not None else None
                standing = recoger(
                    "standing",
                    lambda c: league.collect_standing(
                        client, c, league_id=lid, day=day, my_manager_id=my_manager_id
                    ),
                )
                if standing:
                    recoger(
                        "squads",
                        lambda c: league.collect_squads(
                            client, c, league_id=lid, team_ids=standing["team_ids"], day=day
                        ),
                    )
                recoger(
                    "activity",
                    lambda c: league.collect_activity(client, c, league_id=lid, full=full_activity),
                )

                if skip_lineups:
                    print(f"[recogida] lineups de FútbolFantasy ya recogidas hoy ({day}), reutilizando.")
                    summary["lineups"] = {"cached": True}
                else:
                    recoger("lineups", lambda c: lineups.collect(c, day=day))

                mi_equipo = (standing or {}).get("my_team_id")
                if mi_equipo:
                    try:
                        puestos = eleven.current_ids(client.lineup(mi_equipo))
                    except Exception:  # noqa: BLE001
                        fallos["lineup"] = traceback.format_exc(limit=3)

            if skip_calendar:
                print("[recogida] calendar ya recogido hoy, reutilizando.")
                summary["calendar"] = {"cached": True}
            else:
                recoger("calendar", lambda c: calendar.collect_calendar(client, c))
        error = None
    except Exception:  # noqa: BLE001
        # Aquí solo llega lo que rompe el propio cliente (login, red): eso sí para la recogida.
        fallos["cliente"] = traceback.format_exc()
        error = traceback.format_exc()

    # Falla el job solo si no se ha podido recoger **nada**; si se salvó parte, es un éxito parcial
    # y los análisis de después trabajan con lo que haya.
    if fallos:
        summary["collect_errors"] = sorted(fallos)
        summary["collect_error_details"] = fallos
    recogido = [k for k in ("players", "standing", "squads", "market", "lineups", "calendar") if k in summary]
    status = "ok" if recogido else "error"
    if status == "error" and error is None:
        error = "\n\n".join(f"[{k}]\n{v}" for k, v in fallos.items())

    # --- 2. Análisis ---------------------------------------------------------------------------
    #
    # Cada paso, aislado. Ninguno es imprescindible para el siguiente y todos se pueden rehacer,
    # así que uno roto no puede llevarse por delante a los demás ni marcar el job como fallido.
    # Se ejecutan aunque la recogida haya fallado: trabajan sobre el último día que haya.
    fallos: dict[str, str] = {}

    def paso(nombre: str, fn) -> None:
        try:
            with engine().begin() as conn:
                summary[nombre] = fn(conn)
        except Exception:  # noqa: BLE001
            fallos[nombre] = traceback.format_exc(limit=3)
            print(f"[analisis] {nombre} falló:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)

    paso("forecast", lambda c: forecast.save_forecast(c))
    if settings.league_id:
        lid = settings.league_id
        mi_equipo = (summary.get("standing") or {}).get("my_team_id")
        paso("cash", lambda c: cash.recompute(c, league_id=lid, day=day))
        paso("rivals", lambda c: rivals.recompute(c, league_id=lid, day=day))
        paso("bargains", lambda c: bargains.save(c, day=day))
        # antes de recomendar: el recomendador solo usa las señales de rebote que pasan hoy
        paso("rebound", lambda c: rebound.measure_and_save(c))
        paso(
            "recommendations",
            lambda c: recommend.recompute(c, league_id=lid, day=day, team_id=mi_equipo),
        )
        paso("calibration", lambda c: calibration.backfill(c))
        paso("journal", lambda c: journal.recompute(c, league_id=lid))
        if mi_equipo:
            paso("eleven", lambda c: eleven.save(c, team_id=mi_equipo, day=day, current=puestos))
        paso("missing_days", lambda c: [str(d) for d in alerts.missing_days(c, day=day)])
    if fallos:
        summary["analysis_errors"] = sorted(fallos)

    market_summary = summary.get("market") or {}
    cycle_end_str = market_summary.get("cycle_end")
    # Un mercado recién rotado expira mañana (~20-24h en el futuro; > 2h de margen)
    market_rotated = False
    if cycle_end_str:
        try:
            expires_dt = datetime.fromisoformat(str(cycle_end_str))
            market_rotated = (expires_dt - datetime.now(UTC)).total_seconds() > 3600 * 2
        except Exception:
            market_rotated = False
    elif not settings.league_id:
        market_rotated = True

    summary["market_rotated"] = market_rotated

    if status == "ok" and not market_rotated and settings.league_id:
        print(
            "[daily] El mercado aún no ha rotado a un ciclo nuevo en LaLiga; "
            "posponiendo aviso de Telegram al siguiente intento.",
            file=sys.stderr,
        )
    else:
        _notify(status, error, summary, day=day, quiet=quiet)

    with engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE job_runs SET finished_at = now(), status = :status, "
                "summary = CAST(:summary AS jsonb), error = :error WHERE id = :id"
            ),
            {"status": status, "summary": json.dumps(summary), "error": error, "id": run_id},
        )
    print(json.dumps({"status": status, **summary}, indent=2, ensure_ascii=False))
    if status == "error":
        print(error, file=sys.stderr)
        sys.exit(1)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no escribe en la BD; vuelca el crudo a .raw/")
    ap.add_argument(
        "--save-fixture",
        action="store_true",
        help="implica --dry-run: escribe tests/fixtures/<endpoint>.json anonimizados",
    )
    ap.add_argument(
        "--full-activity", action="store_true", help="recorre todo el feed aunque no haya novedades"
    )
    ap.add_argument("--quiet", action="store_true", help="no envía el resumen diario por Telegram")
    ap.add_argument(
        "--skip-if-recent",
        action="store_true",
        help="no hacer nada si ya hubo una pasada correcta hace poco (para programar varios intentos)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="fuerza la descarga de jugadores, alineaciones y calendario aunque ya existan hoy",
    )
    a = ap.parse_args()
    if a.dry_run or a.save_fixture:
        dry_run(save_fixture=a.save_fixture)
    else:
        run(
            full_activity=a.full_activity,
            quiet=a.quiet,
            skip_if_recent=a.skip_if_recent,
            force=a.force,
        )
