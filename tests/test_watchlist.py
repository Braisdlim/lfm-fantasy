"""Lista de seguimiento: cuándo avisa, cuándo no y qué dice."""

from datetime import UTC, datetime, timedelta

from lfm.analysis import watchlist as wl
from lfm.analysis.watchlist import Watched, compose, evaluate

AHORA = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
CICLO = datetime(2026, 9, 27, 17, 21, tzinfo=UTC)


def w(**kw):
    base = dict(player_id="p1", name="Pedri", max_price=5_000_000, value=4_800_000, cycle_end=CICLO)
    base.update(kw)
    return Watched(**base)


def test_in_the_market_under_the_limit_is_a_hit():
    v = evaluate(w(sale_price=4_500_000, market_kind="marketPlayerLeague", expires_at=CICLO), now=AHORA)
    assert v.state == "cumple"
    assert [h.kind for h in v.hits] == ["mercado"]
    assert "4,5 M" in v.hits[0].text and "tu máximo 5,0 M" in v.hits[0].text
    assert v.hits[0].closes == CICLO and "cierra" not in v.hits[0].text
    assert "cierra en 5 h" in compose([(v, v.hits[0])], cash=None, now=AHORA)


def test_over_the_limit_waits_and_says_why():
    v = evaluate(w(sale_price=6_000_000, market_kind="marketPlayerLeague"), now=AHORA)
    assert v.state == "espera" and not v.hits
    assert "por encima de tu máximo" in v.reasons[0]


def test_manager_sale_price_is_flagged_as_negotiable():
    v = evaluate(w(sale_price=4_000_000, market_kind="marketPlayerTeam", seller="Iago"), now=AHORA)
    assert "lo vende Iago" in v.hits[0].text and "se negocia" in v.hits[0].text


def test_open_clause_under_the_limit_is_a_hit():
    v = evaluate(w(owner_team="t9", owner="Iago", buyout_clause=4_900_000), now=AHORA)
    assert v.state == "cumple" and v.hits[0].kind == "clausula"
    assert v.hits[0].key == "watch:c:p1:t9:4900000"


def test_locked_or_shielded_clause_waits():
    locked = evaluate(
        w(owner_team="t9", buyout_clause=3e6, clause_locked_until=AHORA + timedelta(hours=5)), now=AHORA
    )
    assert locked.state == "espera" and "bloqueada hasta" in locked.reasons[0]
    shielded = evaluate(w(owner_team="t9", owner="Iago", buyout_clause=3e6, is_shielded=True), now=AHORA)
    assert shielded.state == "espera" and "blindada" in shielded.reasons[0]


def test_expired_lock_counts_as_open():
    v = evaluate(
        w(owner_team="t9", buyout_clause=3e6, clause_locked_until=AHORA - timedelta(minutes=1)), now=AHORA
    )
    assert v.state == "cumple"


def test_start_probability_gate():
    bajo = evaluate(w(sale_price=4e6, min_start_prob=0.6, start_prob=0.45), now=AHORA)
    assert bajo.state == "espera" and not bajo.hits
    assert "45 %" in bajo.reasons[0] and "60 %" in bajo.reasons[0]
    assert any("Precio a tiro" in r for r in bajo.reasons)

    sin_dato = evaluate(w(sale_price=4e6, min_start_prob=0.6, start_prob=None), now=AHORA)
    assert sin_dato.state == "espera" and "Sin previsión" in sin_dato.reasons[0]

    ok = evaluate(w(sale_price=4e6, min_start_prob=0.6, start_prob=0.7), now=AHORA)
    assert ok.state == "cumple"


def test_injured_never_triggers():
    v = evaluate(w(sale_price=1e6, injured=True), now=AHORA)
    assert v.state == "bloqueado" and not v.hits


def test_mine_is_not_a_target():
    assert evaluate(w(owner_team="me", owner_is_me=True, buyout_clause=1e6), now=AHORA).state == "tuyo"


def test_no_limit_means_any_price():
    v = evaluate(w(max_price=None, sale_price=40e6), now=AHORA)
    assert v.state == "cumple" and "tu máximo" not in v.hits[0].text


def test_market_key_changes_with_the_cycle_so_each_listing_warns_once():
    a = evaluate(w(sale_price=4e6), now=AHORA).hits[0].key
    b = evaluate(w(sale_price=4e6, cycle_end=CICLO + timedelta(days=1)), now=AHORA).hits[0].key
    assert a != b


def test_compose_links_the_player_and_says_what_is_missing(monkeypatch):
    monkeypatch.setattr("lfm.analysis.watchlist.APP_URL", "https://app.example")
    v = evaluate(w(sale_price=4.5e6, start_prob=0.8), now=AHORA)
    msg = compose([(v, v.hits[0])], cash=3e6)
    assert "/jugador/p1" in msg and "titular 80 %" in msg and "te faltan 1,5 M" in msg


def test_compose_without_app_url_does_not_send_a_placeholder_link(monkeypatch):
    monkeypatch.setattr("lfm.analysis.watchlist.APP_URL", "")
    v = evaluate(w(sale_price=4.5e6, start_prob=0.8), now=AHORA)
    msg = compose([(v, v.hits[0])], cash=3e6)
    assert "<a " not in msg
    assert "Pedri" in msg and "te faltan 1,5 M" in msg
    assert compose([], cash=None) is None


# --- check(): guarda el estado y solo avisa de lo nuevo ------------------------------------------


class Result:
    def __init__(self, value=None, rows=None):
        self.value, self.rows = value, rows or []

    def scalar(self):
        return self.value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Conn:
    def __init__(self, rows, sent=()):
        self.rows, self.sent, self.calls = rows, list(sent), []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if "to_regclass" in sql:
            return Result(True)
        if "FROM watchlist w" in sql:
            return Result(rows=self.rows)
        if "team_money" in sql:
            return Result(10e6)
        if sql.startswith("SELECT dedupe_key"):
            return Result(rows=self.sent)
        return Result()


def row(**kw):
    base = {f: None for f in Watched.__dataclass_fields__}
    base.update(
        player_id="p1",
        name="Pedri",
        max_price=5e6,
        watch_market=True,
        watch_clause=True,
        seller_is_me=False,
        owner_is_me=False,
        cycle_end=CICLO,
    )
    base.update(kw)
    return base


def test_check_sends_new_hits_once_and_records_them():
    conn = Conn([row(sale_price=4e6)])
    sent = []
    out = wl.check(conn, league_id="L", send=lambda m: sent.append(m) or True, now=AHORA)
    assert out["sent"] == 1 and len(sent) == 1
    assert any("INSERT INTO alerts" in s for s, _ in conn.calls)
    assert any("UPDATE watchlist SET state" in s and p["state"] == "cumple" for s, p in conn.calls if p)


def test_check_does_not_repeat_an_alert_already_sent():
    key = evaluate(w(sale_price=4e6), now=AHORA).hits[0].key
    conn = Conn([row(sale_price=4e6)], sent=[key])
    out = wl.check(conn, league_id="L", send=lambda m: (_ for _ in ()).throw(AssertionError), now=AHORA)
    assert out["new"] == 0 and out["sent"] == 0


def test_a_failed_send_is_retried_next_pass():
    conn = Conn([row(sale_price=4e6)])
    out = wl.check(conn, league_id="L", send=lambda m: False, now=AHORA)
    assert out["sent"] == 0
    assert not any("INSERT INTO alerts" in s for s, _ in conn.calls)
