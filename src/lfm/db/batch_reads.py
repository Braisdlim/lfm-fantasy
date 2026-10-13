"""Agrupar lecturas existentes sin reescribir sus reglas SQL.

La envoltura LATERAL conserva cada consulta y sus parámetros; solo elimina
viajes de red. Los consumidores reciben los mismos escalares y filas.
"""

import json
import re

from sqlalchemy import text


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalar(self):
        return next(iter(self.rows[0].values())) if self.rows else None

    def first(self):
        return tuple(self.rows[0].values()) if self.rows else None

    def mappings(self):
        return MappingResult(self.rows)

    def all(self):
        return self.rows


class MappingResult:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class BatchReads:
    def __init__(self, conn):
        self.conn = conn
        self.results = {}

    @staticmethod
    def key(statement, params):
        return statement, tuple(sorted(params.items()))

    def prefetch(self, statement, parameters: list[dict], types: dict[str, str]):
        unique = {self.key(statement, p): p for p in parameters}
        if not unique:
            return
        # Solo identificadores del código, nunca nombres enviados por el usuario.
        if any(
            not re.fullmatch(r"[a-z_][a-z_0-9]*", name) or kind not in ("text", "int")
            for name, kind in types.items()
        ):
            raise ValueError("Columnas de lote inválidas")
        keys = list(unique)
        requests = [{"ord": i, **unique[key]} for i, key in enumerate(keys)]
        sql = re.sub(r"(?<!:):([a-z_][a-z_0-9]*)", lambda m: "request." + m[1], statement.text)
        columns = ", ".join(f"{name} {kind}" for name, kind in types.items())
        query = text(
            f"SELECT request.ord, result.* FROM jsonb_to_recordset(CAST(:requests AS jsonb)) "
            f"AS request(ord int, {columns}) CROSS JOIN LATERAL ({sql}) result ORDER BY request.ord"
        )
        grouped = {i: [] for i in range(len(keys))}
        for row in self.conn.execute(query, {"requests": json.dumps(requests)}).mappings():
            values = dict(row)
            grouped[values.pop("ord")].append(values)
        self.results.update({key: Result(grouped[i]) for i, key in enumerate(keys)})

    def execute(self, statement, params):
        # No caer silenciosamente a una consulta por jugador si falta un lote.
        return self.results[self.key(statement, params)]
