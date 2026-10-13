"""El once que más puntos espera sacar, entre las formaciones que el juego permite.

Las siete formaciones están comprobadas el 2026-09-09 contra
`GET /v4/teams/lineup/formations?option=free`, que devuelve exactamente:

    ["5,4,1", "5,3,2", "4,5,1", "4,4,2", "4,3,3", "3,5,2", "3,4,3"]

Siempre con un portero, sin banquillo y sin entrenador: la misma llamada al once devuelve
`bench: {}` y `coach: 0` en el juego gratuito. Y no hay capitán, así que **no hay ninguna decisión
de multiplicador**: elegir el once es elegir quién juega y en qué dibujo, nada más.

Los puntos esperados salen de `analysis/points.py`, que ya los ajusta por probabilidad de ser
titular. Aquí no se vuelve a tocar esa cuenta: solo se reparte.

**Aviso que la pantalla tiene que dar.** Con once jugadores justos no hay nada que elegir: el once
es obligado y el módulo lo dice (`forced`). El 2026-09-09 la plantilla eran 1 portero, 3 defensas,
4 medios y 3 delanteros, así que la única formación posible era el 3-4-3 y jugaban los once. Lo
que sí decide algo entonces es el hueco más débil, que es una razón para fichar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lfm.analysis import fixtures as fx_mod
from lfm.analysis import points as pts_mod

# (defensas, medios, delanteros); el portero es siempre uno
FORMATIONS: tuple[tuple[int, int, int], ...] = (
    (5, 4, 1),
    (5, 3, 2),
    (4, 5, 1),
    (4, 4, 2),
    (4, 3, 3),
    (3, 5, 2),
    (3, 4, 3),
)

GOALKEEPER, DEFENDER, MIDFIELD, STRIKER = 1, 2, 3, 4
LINE_POSITIONS = (DEFENDER, MIDFIELD, STRIKER)


@dataclass(frozen=True)
class Pick:
    """Un jugador candidato. `xpts` ya viene multiplicado por su probabilidad de ser titular."""

    player_id: str
    name: str
    position_id: int
    xpts: float
    start_prob: float | None = None
    injured: bool = False
    suspended: bool = False


@dataclass(frozen=True)
class Eleven:
    formation: tuple[int, int, int]
    starters: tuple[Pick, ...]
    bench: tuple[Pick, ...]  # los que se quedan fuera, de mejor a peor
    xpts: float
    feasible: int  # cuántas formaciones podías montar con esta plantilla
    forced: bool  # si no había ninguna elección que tomar

    @property
    def label(self) -> str:
        return "-".join(str(n) for n in self.formation)

    @property
    def weakest(self) -> Pick | None:
        """El titular con menos puntos esperados: el hueco por el que se pierden más puntos."""
        return min(self.starters, key=lambda p: p.xpts) if self.starters else None


# Mínimos que exige cualquiera de las siete formaciones: un portero, tres defensas, tres medios y
# un delantero. Por debajo de eso no hay once válido que alinear, por buenos que sean los demás.
MINIMOS = (
    (GOALKEEPER, 1, "portero", "porteros"),
    (DEFENDER, 3, "defensa", "defensas"),
    (MIDFIELD, 3, "medio", "medios"),
    (STRIKER, 1, "delantero", "delanteros"),
)


def missing_for_eleven(picks: list[Pick]) -> list[str]:
    """Qué falta para poder alinear. Vacío si con esta plantilla se puede montar algún once.

    Decir «todavía no hay once calculado» cuando lo que pasa es que **no tienes portero** es lo
    contrario de ayudar: el hueco se traduce en cero puntos esa jornada y solo se arregla fichando.
    """
    hay = _by_position(_available(picks))
    faltan = []
    for pos, minimo, singular, plural in MINIMOS:
        tiene = len(hay.get(pos, []))
        if tiene < minimo:
            cuantos = minimo - tiene
            faltan.append(f"{cuantos} {singular if cuantos == 1 else plural}")
    disponibles = sum(len(v) for v in hay.values())
    if not faltan and disponibles < 11:
        faltan.append(f"{11 - disponibles} jugadores para llegar a once")
    return faltan


def _available(picks: list[Pick]) -> list[Pick]:
    """Fuera los que no pueden jugar. No es una preferencia: el juego no los deja alinear."""
    return [p for p in picks if not p.injured and not p.suspended]


def _by_position(picks: list[Pick]) -> dict[int, list[Pick]]:
    out: dict[int, list[Pick]] = {}
    for p in picks:
        out.setdefault(p.position_id, []).append(p)
    for lista in out.values():
        lista.sort(key=lambda p: -p.xpts)
    return out


def best(picks: list[Pick], formations: tuple[tuple[int, int, int], ...] = FORMATIONS) -> Eleven | None:
    """El mejor once posible, o `None` si la plantilla no da para ninguna formación.

    Devolver `None` en vez de un once a medias es a propósito: un once de nueve no existe en el
    juego, y enseñarlo haría creer que se puede alinear."""
    disponibles = _by_position(_available(picks))
    porteros = disponibles.get(GOALKEEPER, [])
    if not porteros:
        return None

    mejor: Eleven | None = None
    posibles = 0
    for f in formations:
        titulares = [porteros[0]]
        cabe = True
        for pos, n in zip(LINE_POSITIONS, f, strict=True):
            linea = disponibles.get(pos, [])
            if len(linea) < n:
                cabe = False
                break
            titulares.extend(linea[:n])
        if not cabe:
            continue
        posibles += 1
        total = sum(p.xpts for p in titulares)
        if mejor is None or total > mejor.xpts:
            elegidos = {p.player_id for p in titulares}
            banquillo = sorted((p for p in picks if p.player_id not in elegidos), key=lambda p: -p.xpts)
            mejor = Eleven(
                formation=f,
                starters=tuple(titulares),
                bench=tuple(banquillo),
                xpts=total,
                feasible=0,
                forced=False,
            )

    if mejor is None:
        return None
    # con una sola formación posible y nadie en el banquillo no hubo ninguna decisión que tomar
    sin_suplentes = not [p for p in mejor.bench if not p.injured and not p.suspended]
    return Eleven(
        formation=mejor.formation,
        starters=mejor.starters,
        bench=mejor.bench,
        xpts=mejor.xpts,
        feasible=posibles,
        forced=posibles == 1 and sin_suplentes,
    )


def changes(current: set[str], eleven: Eleven) -> tuple[tuple[Pick, ...], tuple[Pick, ...]]:
    """(los que hay que meter, los que hay que sacar) respecto al once que tienes puesto.

    `current` son los `player_id` que la API dice que tienes alineados ahora mismo."""
    entran = tuple(p for p in eleven.starters if p.player_id not in current)
    fuera = tuple(p for p in eleven.bench if p.player_id in current)
    return entran, fuera


# --- Con los datos de verdad -------------------------------------------------------------------

SQL_SQUAD = text("""
    SELECT p.player_id, coalesce(p.nickname, p.name) AS name, p.position_id, p.team_id AS club_id,
           v.status
    FROM league_squad_daily s
    JOIN league_teams lt ON lt.league_id = s.league_id AND lt.team_id = s.team_id
    JOIN players p ON p.player_id = s.player_id
    LEFT JOIN LATERAL (SELECT status FROM player_value_daily WHERE player_id=p.player_id
                       AND source='laliga_api' ORDER BY day DESC LIMIT 1) v ON true
    WHERE lt.is_me AND s.day = (SELECT max(s2.day) FROM league_squad_daily s2
                               WHERE s2.team_id=s.team_id AND s2.league_id=s.league_id)
""")

SQL_CLEAR = text("DELETE FROM lineup_daily WHERE team_id = :team_id AND day = CAST(:day AS date)")

SQL_SAVE = text(
    "INSERT INTO lineup_daily (team_id, day, player_id, chosen, current, xpts, formation, "
    "feasible, forced, computed_at) "
    "SELECT :team_id, CAST(:day AS date), r.player_id, r.chosen, r.current, r.xpts, :formation, "
    ":feasible, :forced, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, chosen boolean, "
    "current boolean, xpts numeric) "
    "ON CONFLICT (team_id, day, player_id) DO UPDATE SET chosen = EXCLUDED.chosen, "
    "current = EXCLUDED.current, xpts = EXCLUDED.xpts, formation = EXCLUDED.formation, "
    "feasible = EXCLUDED.feasible, forced = EXCLUDED.forced, computed_at = now()"
)


def picks_from(conn: Connection) -> list[Pick]:
    """Tu plantilla con sus puntos esperados, por el mismo camino que las recomendaciones.

    Se reutiliza `analysis/points.py` a propósito: si el once calculara los puntos por su cuenta,
    la misma pantalla podría decir que un jugador vale 4,3 y otra que 3,1."""
    squad = list(conn.execute(SQL_SQUAD))
    strength, mu, next_fixtures = fx_mod.load(conn, limit_weeks=1)
    history, pos_means = pts_mod.load(conn, player_ids=[row.player_id for row in squad])
    avail = pts_mod.availability(conn)
    out: list[Pick] = []
    for r in squad:
        a = avail.get(r.player_id) or {}
        e = pts_mod.expected(
            history.get(r.player_id, []),
            r.position_id,
            next_fixtures.get(r.club_id, []),
            pos_means,
            mu,
            strength,
            a.get("start_prob"),
        )
        out.append(
            Pick(
                player_id=r.player_id,
                name=r.name,
                position_id=r.position_id,
                xpts=e.xpts,
                start_prob=a.get("start_prob"),
                injured=bool(a.get("injured")) or r.status in ("injured", "out_of_league"),
                suspended=bool(a.get("suspended")) or r.status == "suspended",
            )
        )
    return out


SQL_CURRENT_CAPTURE = text(
    "SELECT jsonb_path_query_array(payload, '$.formation.goalkeeper[*].playerMaster.id') || "
    "jsonb_path_query_array(payload, '$.formation.defender[*].playerMaster.id') || "
    "jsonb_path_query_array(payload, '$.formation.midfield[*].playerMaster.id') || "
    "jsonb_path_query_array(payload, '$.formation.striker[*].playerMaster.id') "
    "FROM raw_snapshots WHERE source='laliga_api' AND endpoint LIKE :endpoint "
    "ORDER BY fetched_at DESC LIMIT 1"
)


def refresh(conn: Connection, *, team_id: str, day: date) -> dict:
    """Actualizar el once con datos ya recogidos; ninguna petición externa adicional.

    La comparación usa la última alineación realmente capturada por el diario.
    No afirmar que refleja cambios hechos después de esa captura.
    """
    ids = conn.execute(SQL_CURRENT_CAPTURE, {"endpoint": f"%/teams/{team_id}/lineup"}).scalar()
    return save(conn, team_id=team_id, day=day, current={str(pid) for pid in ids or []})


def save(conn: Connection, *, team_id: str, day: date, current: set[str] | None = None) -> dict:
    """Guarda los xPts de la plantilla incluso si hoy no cabe ningún once legal."""
    picks = picks_from(conn)
    once = best(picks)
    puestos = current or set()
    filas = [
        {
            "player_id": p.player_id,
            "chosen": once is not None and p in once.starters,
            "current": p.player_id in puestos,
            "xpts": round(p.xpts, 2),
        }
        for p in picks
    ]
    conn.execute(SQL_CLEAR, {"team_id": team_id, "day": day.isoformat()})
    conn.execute(
        SQL_SAVE,
        {
            "team_id": team_id,
            "day": day.isoformat(),
            "formation": once.label if once else None,
            "feasible": once.feasible if once else 0,
            "forced": once.forced if once else None,
            "rows": json.dumps(filas),
        },
    )
    if once is None:
        return {"eleven": None, "missing": missing_for_eleven(picks)}
    entran, salen = changes(puestos, once)
    return {
        "formation": once.label,
        "xpts": round(once.xpts, 2),
        "forced": once.forced,
        "feasible": once.feasible,
        "changes": [f"{a.name} por {b.name}" for a, b in zip(entran, salen, strict=False)],
    }


# El once que tienes puesto llega agrupado por línea. Comprobado el 2026-09-09: las claves son
# `goalkeeper`, `defender`, `midfield`, `striker`, más `coach` y `bench`, que en el juego gratuito
# vienen vacíos (`coach: 0`, `bench: {}`).
LINEUP_KEYS = ("goalkeeper", "defender", "midfield", "striker")


def current_ids(payload) -> set[str]:
    """Los `player_id` que tienes alineados ahora mismo, del `GET .../teams/{id}/lineup`."""
    if not isinstance(payload, dict):
        return set()
    formation = payload.get("formation")
    if not isinstance(formation, dict):
        return set()
    out: set[str] = set()
    for clave in LINEUP_KEYS:
        for hueco in formation.get(clave) or []:
            if not isinstance(hueco, dict):
                continue
            master = hueco.get("playerMaster")
            pid = master.get("id") if isinstance(master, dict) else None
            if pid is not None:
                out.add(str(pid))
    return out


def improvement(picks: list[Pick], candidate: Pick) -> float:
    """Cuántos puntos por jornada ganaría tu once si ficharas a este jugador.

    Se recalcula el mejor once con él dentro y se resta el de ahora. No hace falta ningún umbral
    inventado para decidir si un fichaje «vale la pena»: o entra en el once y suma, o no entra.
    Y respeta las formaciones solo: un cuarto defensa puede no aportar nada aunque sea bueno, si
    con esa plantilla no cabe un dibujo de cuatro atrás.
    """
    ahora = best(picks)
    con_el = best([*picks, candidate])
    if con_el is None:
        return 0.0
    return con_el.xpts - (ahora.xpts if ahora else 0.0)
