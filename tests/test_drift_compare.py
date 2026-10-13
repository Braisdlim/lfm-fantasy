"""El arnés de comparación corre de punta a punta sobre una historia sintética."""

import random
from datetime import date, timedelta
from types import SimpleNamespace

from lfm.analysis import drift


class FakeConn:
    def __init__(self, series, avail):
        self.series, self.avail = series, avail

    def execute(self, stmt, params=None):
        if stmt is drift.SQL_SERIES_DAYS:
            return self.series
        return self.avail


def test_compare_reports_every_model_and_the_sells_each_rule_would_send():
    rnd = random.Random(7)
    start = date(2026, 7, 1)
    rows, avail = [], []
    for pid in range(120):
        v = 5e6
        for d in range(80):
            v *= 1 + rnd.gauss(-0.002, 0.02)
            rows.append(SimpleNamespace(player_id=str(pid), day=start + timedelta(days=d), v=v))
        for d in range(60, 80):
            avail.append(
                SimpleNamespace(player_id=str(pid), day=start + timedelta(days=d), p=0.2 if d < 70 else 0.9)
            )
    out = drift.compare(FakeConn(rows, avail))
    assert out["cortes"] >= 5 and set(out["error_medio"]) == {
        "baseline",
        "racha (actual)",
        "racha + tamaño",
        "racha + tamaño (mediana)",
    }
    assert out["ventas_mandadas"]["candidato"]["n"] <= out["ventas_mandadas"]["actual"]["n"]
    assert out["salto_titularidad"]["ganan_titularidad"]["n"] > 0
