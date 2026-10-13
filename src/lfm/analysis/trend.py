"""Duración de subidas con comprobación temporal antes de publicar una estimación.

Solo cuenta días consecutivos de la misma fuente. Una subida termina al bajar O
quedarse plana. Siete significa «al menos siete»: la ventana está censurada ahí.
No modifica la puja: es información adicional sobre el horizonte de la operación.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from lfm.analysis import drift

HORIZON = 7
MIN_SAMPLE = 100


@dataclass(frozen=True)
class Case:
    day: date
    bucket: str
    days: int


def cases_from(rows) -> list[Case]:
    segments: list[list] = []
    for row in rows:
        if (
            not segments
            or row.player_id != segments[-1][-1].player_id
            or row.day != segments[-1][-1].day + timedelta(days=1)
            or row.source != segments[-1][-1].source
        ):
            segments.append([])
        segments[-1].append(row)
    cases = []
    for segment in segments:
        values = [r.v for r in segment]
        for i in range(2, len(segment) - HORIZON):
            past = values[max(0, i - 39) : i + 1]
            if drift.streak(past) <= 0 or drift.unreliable(past):
                continue
            days = 0
            for j in range(i + 1, i + HORIZON + 1):
                if values[j] <= values[j - 1]:
                    break
                days += 1
            cases.append(Case(segment[i].day, drift.bucket_with_magnitude(past), days))
    return cases


def groups(cases: list[Case]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = defaultdict(list)
    for case in cases:
        result[case.bucket].append(case.days)
    return result


def validate(cases: list[Case], as_of: date) -> dict:
    """Cuatro cortes semanales; entrenamiento con resultados ya resueltos.

    Se comparan casos idénticos con mediana de todas las subidas y persistencia
    (seguir siete días). Debe mejorar ambos en las dos mitades del periodo.
    Ningún resultado cuyo final sea >= corte entra en entrenamiento.
    """
    halves: list[list[tuple[float, float, float]]] = [[], []]
    for index in range(4):
        cut = as_of - timedelta(days=35 - index * 7)
        training = [c for c in cases if c.day + timedelta(days=HORIZON) < cut]
        if len(training) < MIN_SAMPLE:
            continue
        table = groups(training)
        baseline = statistics.median(c.days for c in training)
        centers = {b: statistics.median(xs) for b, xs in table.items() if len(xs) >= MIN_SAMPLE}
        for case in cases:
            if not cut <= case.day < cut + timedelta(days=7) or case.bucket not in centers:
                continue
            if case.day + timedelta(days=HORIZON) >= as_of:
                continue
            halves[index // 2].append(
                (abs(centers[case.bucket] - case.days), abs(baseline - case.days), HORIZON - case.days)
            )
    metrics = []
    for half in halves:
        metrics.append(
            {
                "n": len(half),
                "mae": statistics.mean(x[0] for x in half) if half else None,
                "baseline_mae": statistics.mean(x[1] for x in half) if half else None,
                "persistence_mae": statistics.mean(x[2] for x in half) if half else None,
            }
        )
    passed = all(
        m["n"] >= MIN_SAMPLE and m["mae"] < min(m["baseline_mae"], m["persistence_mae"]) for m in metrics
    )
    return {"passed": passed, "halves": metrics, "as_of": as_of.isoformat(), "horizon": HORIZON}


def fit(rows, as_of: date) -> tuple[dict[str, list[int]], dict]:
    # Ni siquiera un llamante con datos futuros puede colarlos en la estimación.
    cases = cases_from([r for r in rows if r.day < as_of])
    return groups(cases), validate(cases, as_of)


def outlook(values: list[float], table: dict[str, list[int]], check: dict) -> dict:
    k = drift.streak(values)
    result = {"streak": k, "streak_censored": drift.censored(values), "horizon": HORIZON}
    if k <= 0:
        return {**result, "status": "not_rising"}
    sample = sorted(table.get(drift.bucket_with_magnitude(values), []))
    if drift.unreliable(values) or len(sample) < MIN_SAMPLE:
        return {**result, "status": "insufficient", "n": len(sample)}
    if not check["passed"]:
        return {**result, "status": "unvalidated", "n": len(sample)}
    return {
        **result,
        "status": "validated",
        "n": len(sample),
        "days": statistics.median(sample),
        "low_days": sample[int((len(sample) - 1) * 0.2)],
        "high_days": sample[int((len(sample) - 1) * 0.8)],
        "stop_within_3d": sum(x < 3 for x in sample) / len(sample),
        "validation": check,
    }


if __name__ == "__main__":  # pragma: no cover
    import json

    from sqlalchemy import text

    from lfm.db.session import engine

    with engine().connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        rows = conn.execute(
            text(
                "SELECT player_id, day, source, market_value::float8 AS v "
                "FROM player_value_daily WHERE market_value > 0 ORDER BY player_id, day"
            )
        ).all()
    day = max(r.day for r in rows)
    _, check = fit(rows, day)
    print(json.dumps(check, ensure_ascii=False, indent=2))
