"""Quién rinde por encima de lo que cuesta.

**Puntos por millón, a secas, no sirve.** Medido el 2026-09-09 sobre los 135 jugadores con al menos
tres partidos: la mediana baja de 3,18 p/M en el tramo de 1-5 M a 0,49 p/M por encima de 40 M, y lo
hace de forma monótona. Ordenar por esa cifra es ordenar por barato, y la lista se llena de
suplentes de 0,6 M que jugaron veinte minutos y sacaron un punto.

Lo que sí distingue es comparar a cada uno **con los que cuestan lo mismo y juegan en su puesto**:

    excedente = sus puntos − la mediana de puntos de sus vecinos de precio en su posición

Y se dice en una frase: *"hace 8 puntos más que los defensas que cuestan como él"*.

Se usa la mediana de los vecinos y no un ajuste global porque no supone ninguna forma para la
curva, aguanta los valores extremos y con 4 jornadas no hay datos para nada más fino.

**Esto describe, no predice.** Dice lo que ha rendido hasta ahora, no lo que rendirá. La regla de
`docs/criterio.md` —ninguna señal predictiva se publica sin superar su backtest hacia delante— se
aplica el día que esto quiera entrar en una recomendación automática; como filtro para mirar una
lista corta no hace falta, pero tampoco se puede presentar como pronóstico.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Un jugador que no juega no es un chollo por barato que sea. Los tres cortes salen de mirar la
# distribución real: sin ellos los diez primeros tenían 0 minutos y 0 % de probabilidad de salir.
MIN_MINUTES = 270  # tres partidos completos
MIN_START_PROB = 0.5
NEIGHBOURS = 11  # vecinos de precio con los que se compara; impar, para que la mediana sea un dato
# La ventana tiene que tener los mismos vecinos por debajo que por encima. Si se deja pegada al
# borde, al más caro de cada puesto se le compara solo con gente más barata y sale chollo siempre,
# y al más barato le pasa lo contrario. Quien no tiene vecinos por los dos lados no se juzga.
MIN_EACH_SIDE = 2


SQL_CANDIDATES = text("""
    SELECT p.player_id, coalesce(p.nickname, p.name) AS name, p.position_id,
           c.name AS club, v.market_value::bigint AS value, v.points_total,
           CASE WHEN a.fetched_at >= now() - interval '26 hours'
                AND a.start_prob >= 0 AND a.start_prob < 1 THEN a.start_prob END AS start_prob,
           a.minutes, a.games, a.injured, a.suspended
    FROM players p
    LEFT JOIN teams c USING (team_id)
    JOIN player_value_daily v ON v.player_id = p.player_id
         AND v.day = (SELECT max(day) FROM player_value_daily WHERE source = 'laliga_api')
    LEFT JOIN player_availability a ON a.player_id = p.player_id
         AND a.day = (SELECT max(day) FROM player_availability)
    WHERE v.market_value > 0
""")


@dataclass(frozen=True)
class Bargain:
    player_id: str
    name: str
    position_id: int | None
    club: str | None
    value: int
    points: int
    expected: float  # lo que hacen los que cuestan como él en su puesto
    surplus: float  # puntos de más (o de menos)
    peers: int  # con cuántos se ha comparado, para saber si fiarse

    @property
    def ratio(self) -> float | None:
        return self.points / self.expected if self.expected else None


def eligible(r) -> bool:
    """Solo entran los que juegan: si no, 'chollo' solo quiere decir 'barato'."""
    if not r.value or r.points_total is None:
        return False
    if r.injured or r.suspended:
        return False
    if (r.minutes or 0) < MIN_MINUTES:
        return False
    return (r.start_prob or 0) >= MIN_START_PROB


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def rank(rows: list, *, neighbours: int = NEIGHBOURS) -> list[Bargain]:
    """Cada jugador frente a los que cuestan lo mismo en su puesto, del que más aporta al que menos.

    Los vecinos se buscan **dentro de su posición**, porque un defensa y un delantero del mismo
    precio no puntúan igual, y siempre los mismos por debajo que por encima. Los de los extremos
    —el más caro y el más barato de cada puesto— se quedan fuera: no hay con quién compararlos sin
    inclinar la balanza. `peers` dice con cuántos se ha comparado cada uno.
    """
    aptos = [r for r in rows if eligible(r)]
    por_pos: dict[object, list] = {}
    for r in aptos:
        por_pos.setdefault(r.position_id, []).append(r)
    for grupo in por_pos.values():
        grupo.sort(key=lambda r: r.value)

    out: list[Bargain] = []
    for r in aptos:
        grupo = por_pos[r.position_id]
        i = grupo.index(r)
        # el ancho lo manda el lado que menos vecinos tiene, para que la ventana quede centrada
        lado = min(neighbours // 2, i, len(grupo) - 1 - i)
        if lado < MIN_EACH_SIDE:
            continue
        vecinos = [o for o in grupo[i - lado : i + lado + 1] if o is not r]
        esperado = _median([o.points_total for o in vecinos])
        out.append(
            Bargain(
                player_id=r.player_id,
                name=r.name,
                position_id=r.position_id,
                club=r.club,
                value=r.value,
                points=r.points_total,
                expected=esperado,
                surplus=r.points_total - esperado,
                peers=len(vecinos),
            )
        )
    return sorted(out, key=lambda b: -b.surplus)


def build(conn: Connection, *, neighbours: int = NEIGHBOURS) -> list[Bargain]:
    return rank(list(conn.execute(SQL_CANDIDATES)), neighbours=neighbours)


# --- Dejarlo escrito para la web ---------------------------------------------------------------

SQL_SAVE = text(
    "INSERT INTO player_bargain (player_id, day, points, expected, surplus, peers, computed_at) "
    "SELECT r.player_id, CAST(:day AS date), r.points, r.expected, r.surplus, r.peers, now() "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(player_id text, points int, "
    "expected numeric, surplus numeric, peers int) "
    "ON CONFLICT (player_id, day) DO UPDATE SET points = EXCLUDED.points, "
    "expected = EXCLUDED.expected, surplus = EXCLUDED.surplus, peers = EXCLUDED.peers, "
    "computed_at = now()"
)


def save(conn: Connection, *, day: date, neighbours: int = NEIGHBOURS) -> int:
    filas = [
        {
            "player_id": b.player_id,
            "points": b.points,
            "expected": round(b.expected, 2),
            "surplus": round(b.surplus, 2),
            "peers": b.peers,
        }
        for b in build(conn, neighbours=neighbours)
    ]
    if filas:
        conn.execute(SQL_SAVE, {"day": day.isoformat(), "rows": json.dumps(filas)})
    return len(filas)
