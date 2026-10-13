"""Aplica schema.sql (idempotente). Uso: python -m lfm.db.migrate"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from lfm.db.session import engine

SCHEMA = Path(__file__).with_name("schema.sql")


def statements(sql: str) -> list[str]:
    """Parte el fichero en sentencias, respetando comentarios y cadenas.

    Antes era `sql.split(";")` y parecía suficiente hasta que un comentario llevó un punto y coma
    dentro (2026-09-09): partía la sentencia en dos y Postgres recibía media frase en castellano.
    Como el esquema se documenta en prosa, el separador tiene que saber dónde **no** mirar."""
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    en_cadena = False
    while i < n:
        c = sql[i]
        if en_cadena:
            buf.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":  # comilla escapada dentro de la cadena
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                en_cadena = False
            i += 1
        elif c == "'":
            en_cadena = True
            buf.append(c)
            i += 1
        elif sql.startswith("--", i):  # comentario de línea: se descarta entero
            salto = sql.find("\n", i)
            i = n if salto == -1 else salto
        elif sql.startswith("/*", i):  # comentario de bloque
            cierre = sql.find("*/", i)
            i = n if cierre == -1 else cierre + 2
        elif c == ";":
            out.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(c)
            i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def migrate() -> None:
    stmts = statements(SCHEMA.read_text(encoding="utf-8"))
    with engine().begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
    print(f"Esquema aplicado ({len(stmts)} sentencias).")


if __name__ == "__main__":
    migrate()
