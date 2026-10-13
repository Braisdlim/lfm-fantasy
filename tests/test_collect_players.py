"""collect_players escribe por lotes: una sentencia por tabla, con las filas como JSON.
Sin base de datos: una conexión falsa registra lo que se ejecuta."""

import json
import pathlib
from datetime import date

from lfm.collectors import players

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeConn:
    def __init__(self, latest=None, previous=None):
        self.calls: list[tuple[str, dict]] = []
        self.latest, self.previous = latest, previous or []

    def execute(self, stmt, params):
        sql = str(stmt)
        if sql.startswith("SELECT"):  # lecturas de comprobación: no cuentan como escrituras
            conn = self

            class R:
                def scalar(self_inner):
                    return conn.latest

                def __iter__(self_inner):
                    return iter(conn.previous)

            return R()
        self.calls.append((sql, params))


class FakeClient:
    def players(self):
        return json.loads((FIXTURES / "players.json").read_text(encoding="utf-8"))


def test_collect_players_runs_one_batched_statement_per_table():
    conn = FakeConn()
    summary = players.collect_players(FakeClient(), conn, day=date(2026, 9, 8), min_players=1)

    assert summary["players"] == 30 and summary["warnings_total"] == 0
    tables = [sql.split("INSERT INTO ")[1].split(" ")[0] for sql, _ in conn.calls if sql.startswith("INSERT")]
    assert tables == ["teams", "players", "player_week_stats", "player_value_daily"]
    # y a continuación el cambio del día siguiente, por si ya existía (rehacer un hueco)
    assert conn.calls[-1][0].startswith("UPDATE player_value_daily")
    assert all("jsonb_to_recordset" in sql for sql, _ in conn.calls if sql.startswith("INSERT"))

    _, players_params = conn.calls[1]
    rows = json.loads(players_params["rows"])
    assert len(rows) == 30 and rows[0]["player_id"] == "68" and rows[0]["team_id"] == "3"

    _, week_params = conn.calls[2]
    weeks = json.loads(week_params["rows"])
    assert len(weeks) == summary["week_rows"] > 30
    assert {"player_id", "week", "points"} == set(weeks[0])

    _, value_params = conn.calls[3]
    assert value_params["day"] == "2026-09-08"
    values = json.loads(value_params["rows"])
    assert all(isinstance(v["market_value"], int) for v in values)


def test_collect_players_skips_value_rows_without_market_value():
    class Client:
        def players(self):
            return [{"id": 1, "nickname": "A", "positionId": "1", "teamId": "3"}]

    conn = FakeConn()
    summary = players.collect_players(Client(), conn, day=date(2026, 9, 8), min_players=1)
    tables = [sql.split("INSERT INTO ")[1].split(" ")[0] for sql, _ in conn.calls if sql.startswith("INSERT")]
    assert tables == ["teams", "players"]  # sin weekPoints ni marketValue no hay más sentencias
    assert summary["warnings"] == ["sin marketValue: 1"]


def test_collect_players_refuses_a_half_answer_so_the_next_attempt_retries():
    # Guardar una respuesta a medias deja huecos y, peor, el reintento ve «ya hay valores de hoy»
    # y no vuelve a pedirlos.
    conn = FakeConn()
    try:
        players.collect_players(FakeClient(), conn, day=date(2026, 9, 8))
    except players.IncompleteResponse as e:
        assert "30 jugadores" in str(e)
    else:
        raise AssertionError("debía rechazar una respuesta con 30 jugadores")
    assert conn.calls == []


def test_a_snapshot_with_yesterdays_values_is_not_written_as_today():
    # Antes de las 00:15 de Madrid, o si LaLiga se retrasa, /players trae los valores de ayer.
    # Guardarlos con la fecha de hoy daba «cambio 0» a todos y un día de más en la serie.
    payload = [
        {"id": i, "nickname": f"J{i}", "positionId": "3", "teamId": "3", "marketValue": "1000"}
        for i in range(150)
    ]
    ayer = [type("R", (), {"player_id": str(i), "market_value": 1000}) for i in range(150)]

    class Api:
        def players(self_inner):
            return payload

    conn = FakeConn(latest=date(2026, 9, 7), previous=ayer)
    try:
        players.collect_players(Api(), conn, day=date(2026, 9, 8), min_players=1)
    except players.StaleSnapshot as e:
        assert "2026-09-07" in str(e)
    else:
        raise AssertionError("debía rechazar una captura idéntica al día anterior")
    assert conn.calls == []


def test_is_stale_uses_the_measured_daily_turnover():
    prev = {str(i): 100 for i in range(850)}
    nuevo_dia = {k: (v + 1 if int(k) < 570 else v) for k, v in prev.items()}  # 67 % cambia
    misma_foto = {k: (v + 1 if int(k) < 2 else v) for k, v in prev.items()}  # 0-2 cambian
    assert players.is_stale(nuevo_dia, prev)[0] is False
    assert players.is_stale(misma_foto, prev)[0] is True
    assert players.is_stale(misma_foto, {})[0] is False  # sin referencia no se afirma nada


def test_a_player_listed_twice_is_written_once():
    class Twice:
        def players(self_inner):
            return [{"id": 1, "nickname": "A", "positionId": "1", "teamId": "3", "marketValue": "5"}] * 2

    conn = FakeConn()
    players.collect_players(Twice(), conn, day=date(2026, 9, 8), min_players=1)
    valores = json.loads(
        next(p["rows"] for sql, p in conn.calls if "player_value_daily" in sql and sql.startswith("INSERT"))
    )
    assert len(valores) == 1
