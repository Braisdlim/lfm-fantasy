"""Avisos: detección de días sin snapshot y formato del resumen."""

from datetime import UTC, date, datetime

from lfm.analysis import alerts
from lfm.analysis.alerts import _fmt, gap_message, missing_days


class FakeConn:
    def __init__(self, days):
        self.days = days

    def execute(self, stmt, params):
        conn = self

        class R:
            def scalars(self_inner):
                return conn.days

        return R()


def test_missing_days_lists_only_the_gaps():
    today = date(2026, 9, 8)
    have = [today, date(2026, 9, 7), date(2026, 9, 5)]
    missing = missing_days(FakeConn(have), day=today, back=4)
    assert missing == [date(2026, 9, 6)]


def test_missing_days_ignores_dates_before_the_first_snapshot():
    # el colector arrancó hoy: los días anteriores los cubre el backfill, no son huecos
    today = date(2026, 9, 8)
    assert missing_days(FakeConn([today]), day=today, back=7) == []
    assert missing_days(FakeConn([]), day=today, back=7) == []


def test_missing_days_empty_when_every_day_is_there():
    today = date(2026, 9, 8)
    have = [date(2026, 9, 8 - i) for i in range(7)]
    assert missing_days(FakeConn(have), day=today, back=7) == []


def test_gap_message_names_the_days():
    msg = gap_message([date(2026, 9, 6), date(2026, 9, 4)])
    assert "04/09, 06/09" in msg and "huecos" in msg


def test_money_format_is_spanish():
    from decimal import Decimal

    assert _fmt(3_182_706) == "3,2 M"
    assert _fmt(Decimal("3182706")) == "3,2 M"  # psycopg devuelve Decimal en SUM()
    assert _fmt(104_300_000) == "104,3 M"
    assert _fmt(None) == "–"


# --- El mensaje diario: lo que hay que decidir antes del proximo cierre -------------------------


AHORA = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def snap(**kw):
    base = dict(
        day=date(2026, 9, 9),
        now=AHORA,
        cash=45_600_000.0,
        market_closes=datetime(2026, 9, 10, 17, 21, tzinfo=UTC),
        week_opens=datetime(2026, 9, 11, 19, 0, tzinfo=UTC),
        week=5,
    )
    return alerts.Snapshot(**{**base, **kw})


def compra(name, bid, start_prob=0.9, veredicto="Puja hasta 14,21 M: ganarias 7 de cada 10"):
    return alerts.Buy(
        name=name,
        bid=bid,
        club="Alaves",
        xpts=6.0,
        start_prob=start_prob,
        verdict="pujar",
        reasons=[{"code": "VEREDICTO", "text": veredicto}],
    )


def test_a_day_with_nothing_to_decide_says_so_and_stops():
    """Un aviso que no pide ninguna decision solo gasta atencion."""
    m = alerts.compose(snap())
    assert "Nada que decidir hoy." in m
    assert len(m) < 120


def test_the_buys_lead_and_never_repeat_the_bid_twice():
    """La cabecera decia 14,2 M y el motivo 14,21 M: la misma cifra con dos redondeos se lee
    como si fueran dos numeros distintos."""
    m = alerts.compose(snap(buys=[compra("A. Herrero", 14_209_316)]))
    assert "puja hasta 14,2 M" in m
    assert m.count("14,21 M") == 0
    assert "Ganarias 7 de cada 10" in m


def test_what_you_cannot_afford_is_not_offered():
    m = alerts.compose(snap(cash=5_000_000.0, buys=[compra("Caro", 40_000_000)]))
    assert "Caro" not in m
    assert "te cabe con el saldo" in m


def test_an_unknown_start_probability_is_said_out_loud():
    """El motor deja `start_prob` a None cuando la fuente no trae al jugador. Vender esos puntos
    como firmes seria justo lo contrario de lo que hace `recommend.py`."""
    m = alerts.compose(snap(buys=[compra("Sin dato", 1_000_000, start_prob=None)]))
    assert "Sin dato de si es titular" in m


def test_a_clause_worth_exactly_its_value_is_the_dangerous_one():
    """Ordenar por importe de clausula engaña: 35,2 M suena protegido y es su valor exacto."""
    s = snap(
        risks=[
            {"name": "Blanco", "clause": 25_300_000.0, "value": 18_800_000.0, "cuantos": 4},
            {"name": "Soria", "clause": 35_200_000.0, "value": 35_200_000.0, "cuantos": 3},
        ]
    )
    # gather ordena; aqui se comprueba la redaccion de cada caso
    m = alerts.compose(s)
    assert "Aunque pagaría 6,5 M más de lo que vale" in m  # su cláusula está por encima de su valor
    assert "nada le frena" in m


def test_a_difference_of_a_few_euros_is_the_same_number():
    """Sin umbral salia «se lo llevaria 0,0 M por debajo de su valor», que no dice nada."""
    m = alerts.compose(
        snap(risks=[{"name": "Bardeli", "clause": 5_800_000.0, "value": 5_800_186.0, "cuantos": 4}])
    )
    assert "0,0 M" not in m
    assert "nada le frena" in m


def test_the_lineup_block_only_shows_up_when_there_is_still_time_to_fix_it():
    problemas = {"lineup_changes": ["falta Boye"], "lineup_problems": ["Fort esta lesionado"]}
    lejos = alerts.compose(snap(week_opens=datetime(2026, 9, 20, 19, 0, tzinfo=UTC), **problemas))
    assert "Boye" not in lejos
    cerca = alerts.compose(snap(week_opens=datetime(2026, 9, 10, 6, 0, tzinfo=UTC), **problemas))
    assert "falta Boye" in cerca and "Fort esta lesionado" in cerca


def test_the_countdown_rolls_over_a_cycle_that_already_closed():
    """El mercado rota cada 24 h: sin esto la cuenta atras salia en negativo o desaparecia."""
    m = alerts.compose(
        snap(market_closes=datetime(2026, 9, 9, 17, 21, tzinfo=UTC), buys=[compra("X", 1_000_000)])
    )
    assert "El mercado cierra en 5 h" in m


def test_one_extra_option_is_said_in_singular():
    """«Hay 1 opciones más en la app» se lee mal y es lo que salia con cuatro recomendaciones."""
    buys = [compra(f"J{i}", 1_000_000) for i in range(4)]
    m = alerts.compose(snap(buys=buys))
    assert "Hay una opción más en la app." in m
    assert "1 opciones" not in m


def mejora(name, bid, cuanto, **kw):
    b = compra(name, bid, **kw)
    b.improves = cuanto
    return b


def test_when_nothing_improves_the_eleven_it_says_to_keep_the_money():
    """Es la conclusión que se quiere leer de un vistazo: comprar o guardar el saldo."""
    m = alerts.compose(snap(buys=[mejora("A", 1_000_000, 0.0), mejora("B", 2_000_000, 0.0)]))
    assert "Ninguna te mejora el once" in m
    assert "guarda el saldo" in m


def test_the_headline_and_the_list_agree_on_who_is_best():
    """El motor ordena por rentabilidad total, así que el que más mejora el once podía salir el
    tercero y la conclusión señalaba a alguien que no estaba arriba."""
    buys = [
        mejora("Herrero", 14_000_000, 0.0),
        mejora("Ejuke", 5_000_000, 0.4),
        mejora("Rueda", 4_000_000, 1.9),
    ]
    m = alerts.compose(snap(buys=buys))
    assert "Dos de las tres entrarían en tu once" in m
    assert m.index("Rueda") < m.index("Ejuke") < m.index("Herrero")
    assert m.count("1,9 punto") == 1  # la cifra, una sola vez


def test_a_buy_that_does_not_make_the_eleven_says_it_is_for_the_resale():
    m = alerts.compose(snap(buys=[mejora("Solo negocio", 1_000_000, 0.0)]))
    assert "No entraría en tu once: si pujas, es por la reventa" in m


def test_nothing_is_claimed_when_the_eleven_could_not_be_computed():
    """Sin once calculado no se afirma que no mejora: se calla."""
    m = alerts.compose(snap(buys=[compra("X", 1_000_000)]))
    assert "mejora el once" not in m
    assert "guarda el saldo" not in m


def test_one_point_is_singular():
    m = alerts.compose(snap(buys=[mejora("Uno", 1_000_000, 1.0)]))
    assert "La única opción que te cabe entraría en tu once." in m  # y no «Una de las Una»
    assert "1,0 punto por jornada" in m
    assert "1,0 puntos" not in m


def test_the_same_error_twice_is_not_a_passing_failure():
    """El 2026-09-15 el mismo error tumbo los cinco intentos del dia. Al segundo con la misma
    huella ya se sabia que reintentar no iba a arreglarlo."""
    from lfm.jobs import daily

    traza = "Traceback...\nsqlalchemy.exc.ProgrammingError: (CardinalityViolation) boom"
    assert daily._huella(traza) == "sqlalchemy.exc.ProgrammingError: (CardinalityViolation) boom"
    assert daily._huella(None) == ""
    assert daily._huella("   ") == ""


def test_a_squad_that_cannot_field_an_eleven_is_the_first_thing_said():
    """Sin portero no puntuas, y eso no lo arregla ninguna puja fina."""
    m = alerts.compose(snap(missing=["1 portero"], buys=[compra("X", 1_000_000)]))
    assert "te falta 1 portero" in m
    assert m.index("portero") < m.index("Compraría hoy")
