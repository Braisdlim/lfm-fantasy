"""Quién tiene a quién en la liga, y qué parte de tus puntos es realmente tuya.

En una liga de cinco, los puntos de un jugador que tienen los cinco **no cambian la
clasificación**: suben a todos a la vez. Lo que mueve posiciones es la diferencia. Por eso aquí no
se mira "cuántos puntos hace" sino "cuántos puntos hace que mis rivales no tengan también".

Tres cosas que se pueden decir en una frase:

- **Diferencial**: lo tengo yo y nadie más. Cada punto suyo es un punto de ventaja sobre los cuatro.
- **Neutralizado**: lo tenemos todos. Sus puntos no me acercan ni me alejan de nadie.
- **Amenaza**: lo tiene un rival y yo no. Cada punto suyo me cuesta terreno con ese rival.

La propiedad ya la recogemos entera (`league_squad_daily`, las cinco plantillas cada día), así que
esto no pide ni una petición nueva. Lo que **no** se puede saber es la propiedad en el conjunto del
juego: la API solo da las plantillas de tu liga. Todo lo de aquí es propiedad **dentro de tu liga**,
que además es lo único que decide tu clasificación.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

SQL_SQUADS = text("""
    SELECT s.player_id, s.team_id, t.is_me, coalesce(t.manager_name, t.team_name) AS manager
    FROM league_squad_daily s
    JOIN league_teams t USING (league_id, team_id)
    -- La última foto de cada equipo: el job ligero solo guarda la mía con el día nuevo.
    WHERE s.day = (SELECT max(m.day) FROM league_squad_daily m
                   WHERE m.league_id = s.league_id AND m.team_id = s.team_id)
      AND NOT EXISTS (SELECT 1 FROM league_squad_daily x WHERE x.player_id = s.player_id AND x.day > s.day)
""")

SQL_PLAYERS = text("""
    SELECT p.player_id, coalesce(p.nickname, p.name) AS name, p.position_id, c.name AS club,
           v.market_value::bigint AS value, v.points_total,
           a.start_prob, a.injured, a.suspended
    FROM players p
    LEFT JOIN teams c USING (team_id)
    LEFT JOIN player_value_daily v ON v.player_id = p.player_id
         AND v.day = (SELECT max(day) FROM player_value_daily WHERE source = 'laliga_api')
    LEFT JOIN player_availability a ON a.player_id = p.player_id
         AND a.day = (SELECT max(day) FROM player_availability)
""")

# Etiquetas, en el orden en que importan al mirarlas
DIFERENCIAL = "diferencial"
COMPARTIDO = "compartido"
NEUTRALIZADO = "neutralizado"
AMENAZA = "amenaza"
LIBRE = "libre"


@dataclass(frozen=True)
class Ownership:
    player_id: str
    mine: bool
    rivals: tuple[str, ...]  # nombres de los rivales que lo tienen
    label: str

    @property
    def rival_count(self) -> int:
        return len(self.rivals)


def classify(rows: list[tuple[str, str, bool, str]], *, rivals_total: int) -> dict[str, Ownership]:
    """Una etiqueta por jugador a partir de las plantillas del día.

    `rows` son tuplas (player_id, team_id, is_me, manager) tal como salen de `SQL_SQUADS`.
    `rivals_total` es cuántos rivales hay (los equipos de la liga menos el mío): hace falta para
    distinguir "lo tienen algunos" de "lo tienen todos", que es la diferencia entre pelear por
    puntos y estar empatado de antemano.
    """
    mios: set[str] = set()
    # conjunto y no lista: si la consulta repitiera una fila (dos días colándose, dos ligas), un
    # rival contado dos veces convertiría un diferencial en compartido sin que nada haya cambiado
    rivales: dict[str, set[str]] = {}
    for player_id, _team_id, is_me, manager in rows:
        if is_me:
            mios.add(player_id)
        else:
            rivales.setdefault(player_id, set()).add(manager)

    out: dict[str, Ownership] = {}
    for player_id in mios | set(rivales):
        quien = tuple(sorted(rivales.get(player_id, ())))
        mine = player_id in mios
        if mine and not quien:
            label = DIFERENCIAL
        elif mine and rivals_total and len(quien) >= rivals_total:
            label = NEUTRALIZADO
        elif mine:
            label = COMPARTIDO
        else:
            label = AMENAZA
        out[player_id] = Ownership(player_id, mine, quien, label)
    return out


def snapshot(conn: Connection) -> dict[str, Ownership]:
    """La propiedad de hoy, jugador a jugador. Los que no salen es que están libres."""
    filas = [(r.player_id, r.team_id, r.is_me, r.manager) for r in conn.execute(SQL_SQUADS)]
    equipos = {(r[1], r[2]) for r in filas}
    rivals_total = sum(1 for _tid, is_me in equipos if not is_me)
    return classify(filas, rivals_total=rivals_total)


def label_of(own: dict[str, Ownership], player_id: str) -> str:
    """La etiqueta de un jugador, contando que no estar en ninguna plantilla es estar libre."""
    o = own.get(player_id)
    return o.label if o else LIBRE


# --- Dos cosas comprobadas el 2026-09-09 que conviene no volver a deducir -----------------------
#
# 1. **Aquí no hay diferenciales que distingan nada.** Los cinco equipos de la liga tienen 57
#    jugadores entre todos sobre un censo de 674, y no comparten ni uno: los once míos salen
#    "diferencial". La etiqueta sirve para avisar el día que eso deje de ser cierto, no para
#    montarle una pantalla encima. La idea de "propiedad" viene de los fantasy de millones de
#    usuarios, donde un jugador lo tiene el 60 %; en una liga de cinco no se traslada.
#
# 2. **Sumar los puntos de la plantilla de cada rival engaña.** Sale casi al revés que la
#    clasificación: ismasenraa va primero con 238 puntos de liga y es el que menos suma (240),
#    y yo voy segundo sumando lo máximo (255). Normal: la liga cuenta lo que alineaste y lo que
#    tenías cuando puntuó, no lo que tienes hoy. La clasificación buena la da la API.
#
# Lo que sí aporta la propiedad es **si puedes fichar a alguien y a qué precio**: libre se puja,
# de un rival se paga cláusula. Para eso es `label_of`.
